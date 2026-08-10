"""Unit tests for the LangChain create_agent implementation.

The tests verify that:

* the agent invokes tools correctly,
* a ``ToolMessage`` is produced when tools are called,
* normal AIMessage responses work,
* the graph handles LLM errors.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from langchain_core.utils.uuid import uuid7

from code_agent.graph import build_graph

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm() -> MagicMock:
    """Return a MagicMock that mimics a LangChain LLM for create_agent.

    The mock returns a tool call when the prompt contains the word
    ``"tool"`` (case-insensitive). Otherwise, it returns a plain
    ``AIMessage``.

    :return: The mock LLM.
    """
    mock = MagicMock()

    def _invoke(messages: list) -> AIMessage:
        """Return a tool call if the prompt contains the word ``"tool"``.

        Otherwise, return a plain ``AIMessage``.

        :param messages: The messages to process.
        :return: The response message.
        """
        prompt = str(messages[-1].content)
        if "tool" in prompt.lower():
            return AIMessage(
                content="",
                tool_calls=[{"name": "dummy", "args": {}, "id": "1"}],
            )
        return AIMessage(content="Hello, world!")

    mock.invoke.side_effect = _invoke
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


@pytest.fixture
def dummy_tool():
    """A simple dummy tool."""

    @tool
    def dummy() -> str:
        """A dummy tool that returns a string.

        :return: A dummy string.
        """
        return "dummy output"

    return dummy


@pytest.fixture
def agent_graph(mock_llm: MagicMock, dummy_tool) -> Any:
    """Create a CodeAgent wired with the mock LLM and an in-memory store.

    :param mock_llm: The mock LLM.
    :param dummy_tool: The dummy tool.
    :return: The agent graph.
    """
    return build_graph(llm=mock_llm, tools=[dummy_tool])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_agent_invokes_tool(agent_graph: Any) -> None:
    """The agent should call the tool and return a ``ToolMessage``.

    :param agent_graph: The agent graph to test.
    :return: None
    """
    config = {"configurable": {"thread_id": str(uuid7())}}
    state = {"messages": [HumanMessage(content="Please call a tool")]}

    final_state = agent_graph.invoke(state, config=config)

    tool_msgs = [
        m for m in final_state.get("messages", []) if isinstance(m, ToolMessage)
    ]
    assert (
        len(tool_msgs) >= 1
    ), "Expected at least one ToolMessage in the final state"

    # Verify that the tool call was made correctly.
    assert tool_msgs[0].name == "dummy"


def test_agent_returns_normal_ai_message(agent_graph: Any) -> None:
    """If the LLM does not request a tool, the agent should return a normal AIMessage."""
    config = {"configurable": {"thread_id": str(uuid7())}}
    state = {"messages": [HumanMessage(content="Say hello")]}

    final_state = agent_graph.invoke(state, config=config)

    ai_msgs = [
        m for m in final_state.get("messages", []) if isinstance(m, AIMessage)
    ]
    assert len(ai_msgs) >= 1
    assert ai_msgs[-1].content == "Hello, world!"


def test_graph_handles_llm_error(mock_llm: MagicMock, dummy_tool) -> None:
    """If the LLM raises an exception, the graph should propagate it."""
    mock_llm.invoke.side_effect = RuntimeError("LLM failure")
    graph = build_graph(llm=mock_llm, tools=[dummy_tool])
    config = {"configurable": {"thread_id": str(uuid7())}}
    state = {"messages": [HumanMessage(content="Trigger an error")]}

    with pytest.raises(RuntimeError, match="LLM failure"):
        graph.invoke(state, config=config)
