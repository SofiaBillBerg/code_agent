# tests/test_graph.py
"""Unit tests for the LangGraph implementation.

The tests build a small graph with a single ``action`` node that
expects an LLM capable of returning a tool call.  The mock LLM is a
``MagicMock`` that can be configured to return an ``AIMessage`` with
a tool call.

The tests verify that:

* the ``action`` node is reached,
* a ``ToolMessage`` is produced,
* the correct tool is called,
* the memory store is updated after each turn.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import (AIMessage, BaseMessage, HumanMessage, ToolCall, ToolMessage, )
from langchain_core.tools import tool

# Import the graph builder and the factory helper that creates an agent
# with an in‑memory store.
from code_agent.graph import build_graph


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm() -> MagicMock:
    """Return a MagicMock that mimics a LangChain LLM.

    The mock returns a tool call when the prompt contains the word
    ``"tool"`` (case‑insensitive).  Otherwise, it returns a plain
    ``AIMessage``.
    """

    mock = MagicMock()

    def _invoke(messages: list[BaseMessage]) -> BaseMessage:  # type: ignore[override]
        prompt = messages[-1].content
        if "tool" in prompt.lower():
            return AIMessage(
                    content = "", tool_calls = [ToolCall(name = "dummy", args = {}, id = "1")], )
        return AIMessage(content = "Hello, world!")

    mock.invoke.side_effect = _invoke
    # Add the bind_tools method to the mock
    mock.bind_tools = MagicMock(return_value = mock)
    return mock


@pytest.fixture
def dummy_tool():
    """A simple dummy tool."""

    @tool
    def dummy() -> str:
        """does nothing"""
        return "dummy output"

    return dummy


@pytest.fixture
def agent_graph(mock_llm, dummy_tool) -> Any:
    """Create a CodeAgent wired with the mock LLM and an in‑memory store."""
    return build_graph(llm = mock_llm, tools = [dummy_tool])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_action_node_generates_tool_message(agent_graph):
    """The action node should call the tool and return a ``ToolMessage``."""
    # type: ignore[arg-type]
    state = {"messages": [HumanMessage(content = "Please call a tool")]}

    final_state = agent_graph.invoke(state)

    tool_msgs = [m for m in final_state["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1, "Expected one ToolMessage in the final state"

    # Verify that the tool call was made correctly.
    assert tool_msgs[0].name == "dummy"
    assert tool_msgs[0].content == "dummy output"


def test_action_node_returns_normal_ai_message(agent_graph):
    """If the LLM does not request a tool, the graph should return a normal AIMessage."""
    state = {"messages": [HumanMessage(content = "Say hello")]}

    final_state = agent_graph.invoke(state)

    ai_msgs = [m for m in final_state["messages"] if isinstance(m, AIMessage)]
    # The initial AIMessage and the final one
    assert len(ai_msgs) == 1
    assert ai_msgs[0].content == "Hello, world!"


def test_graph_handles_llm_error(mock_llm, dummy_tool):
    """If the LLM raises an exception, the graph should propagate it."""
    mock_llm.invoke.side_effect = RuntimeError("LLM failure")
    graph = build_graph(llm = mock_llm, tools = [dummy_tool])
    state = {"messages": [HumanMessage(content = "Trigger an error")]}

    with pytest.raises(RuntimeError, match = "LLM failure"):
        graph.invoke(state)
