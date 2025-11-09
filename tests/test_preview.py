# tests/test_preview.py
"""
Test suite for the `code_agent` utilities.

The focus is on the two public helpers:
* :func:`code_agent.file_generator.write_file` – writes a string to a file.
* :func:`code_agent.agents.base_agent.build_agent` – creates an agent instance.
"""

from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

# Import the helpers from the public API
from code_agent.agents.base_agent import build_agent, create_default_tools
from code_agent.exceptions import CodeAgentError
from code_agent.file_generator import write_file
from code_agent.main import create_llm


# --------------------------------------------------------------------------- #
# Helper fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def tmp_file(tmp_path: Path) -> Path:
    """Return a fresh, non‑existent file inside the temporary directory."""
    return tmp_path / "fresh.txt"


# --------------------------------------------------------------------------- #
# Tests for ``write_file``
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
        ("content", "expected"), [("hello world", "hello world"), ("", ""),  # empty string
                                  ("\n\n", "\n\n"),  # newlines only
                                  ], ids = ["normal", "empty", "newlines"], )
def test_write_file_basic(tmp_file: Path, content: str, expected: str) -> None:
    """Verify that ``write_file`` creates a file containing *content*."""
    for path_variant in (str(tmp_file), tmp_file):
        write_file(path_variant, content)
        assert tmp_file.exists(), f"File {tmp_file} should exist after writing"
        assert (tmp_file.read_text() == expected), f"File {tmp_file} should contain the expected content"
        # Clean up for the next iteration.
        tmp_file.unlink(missing_ok = True)


def test_write_file_overwrites(tmp_path: Path) -> None:
    """Writing to an existing file should replace its contents."""
    path = tmp_path / "overwrite.txt"
    write_file(path, "first")
    write_file(path, "second")
    assert path.read_text() == "second"


def test_write_file_to_directory(tmp_path: Path) -> None:
    """Attempting to write to a directory should raise an OSError."""
    with pytest.raises(CodeAgentError, match = "Cannot write to a directory"):
        write_file(tmp_path, "content")


def test_write_file_invalid_path() -> None:
    """Provide an invalid path (e.g. a file name with a null byte)."""
    invalid = "invalid\0name.txt"
    with pytest.raises(Exception):  # OSError on linux, ValueError on Windows
        write_file(invalid, "data")


# --------------------------------------------------------------------------- #
# Tests for agent creation
# --------------------------------------------------------------------------- #
@pytest.fixture
def dummy_llm() -> BaseChatModel:
    """A dummy LLM for testing agent creation."""

    class DummyLLM(BaseChatModel):
        def _generate(
                self, messages: list[BaseMessage], stop: list[str] | None = None, **kwargs: Any, ) -> ChatResult:
            return ChatResult(
                    generations = [ChatGeneration(
                            message = AIMessage(content = "Hello from DummyLLM")
                            )]
                    )

        def bind_tools(
                self, tools: list[BaseTool], **kwargs: Any
                ) -> Runnable[Any, BaseMessage]:
            return self

        @property
        def _llm_type(self) -> str:
            return "dummy-chat-model"

    return DummyLLM()


def test_build_agent_returns_runnable(
        tmp_path: Path, dummy_llm: BaseChatModel
        ) -> None:
    """Creating an agent with a valid path should return a LangChain Runnable."""
    # We need to load config and create tools to pass to build_agent
    tools = create_default_tools(root_dir = str(tmp_path), llm = dummy_llm)

    agent_runnable = build_agent(llm = dummy_llm, tools = tools)
    assert isinstance(
            agent_runnable, Runnable
            ), "build_agent should return a Runnable"
    assert agent_runnable is not None, "Agent Runnable should not be None"


def test_build_agent_with_invalid_config(tmp_path: Path) -> None:
    """Test that agent creation handles invalid configurations gracefully."""
    # Simulate an invalid config that might cause create_llm to fail
    invalid_cfg = {"ollama_model": "nonexistent", "ollama_port": "invalid"}

    # create_llm should return a FallbackLLM in case of error
    llm = create_llm(invalid_cfg)

    # build_agent should still return a Runnable, even with a fallback LLM
    tools = create_default_tools(root_dir = str(tmp_path), llm = llm)
    agent_runnable = build_agent(llm = llm, tools = tools)
    assert isinstance(
            agent_runnable, Runnable
            ), "build_agent should return a Runnable even with fallback LLM"

    # Test invocation to ensure it returns the error message
    response = agent_runnable.invoke(
            {"messages": [HumanMessage(content = "test")]}
            )
    final_message = response["messages"][-1]
    assert isinstance(final_message, AIMessage)
    assert "LLM unavailable" in final_message.content


# --------------------------------------------------------------------------- #
# Additional sanity checks
# --------------------------------------------------------------------------- #
def test_write_file_and_agent_integration(
        tmp_path: Path, dummy_llm: BaseChatModel
        ) -> None:
    """A quick integration test: write a file, then create an agent that uses it.

    Ensures that the agent can be instantiated after a file operation succeeds.
    """
    file_path = tmp_path / "data.txt"
    write_file(file_path, "agent data")

    tools = create_default_tools(root_dir = str(tmp_path), llm = dummy_llm)
    agent_runnable = build_agent(llm = dummy_llm, tools = tools)

    assert isinstance(
            agent_runnable, Runnable
            ), "build_agent should return a Runnable"
    assert agent_runnable is not None, "Agent Runnable should not be None"
