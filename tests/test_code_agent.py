"""Minimal test-suite for the *code_agent* package.

The tests exercise the public API: the file helpers, the CLI, the
scaffold generator and a very small dummy agent.  They run under
``pytest`` and use the ``tmp_path`` fixture to keep the file system
clean.

The test suite is intentionally small but covers the core
behaviour.  Feel free to add more tests as you extend the
implementation.
"""

from __future__ import annotations

import json

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_core.utils.uuid import uuid7
from typer.testing import CliRunner

from code_agent.agents.base_agent import build_agent
from code_agent.cli import app as cli_app
from code_agent.file_generator import (
    append_file,
    create_file,
    create_from_template,
    write_file,
)
from code_agent.main import load_config
from code_agent.scaffold import create_project_scaffold


@pytest.fixture
def runner() -> CliRunner:
    """
    Runner.
    :return: Description of return value.

    Example::

        >>> result = runner()
    """
    return CliRunner()


# ---------------------------------------------------------------------------
# Tests for the core helpers
# ---------------------------------------------------------------------------


def test_create_file_overwrite(tmp_path: Path) -> None:
    """Test if overwrite works.

    :param tmp_path: Temporary directory path from pytest.
    :return: None
    """
    p = tmp_path / "foo.py"
    create_file(p, "a = 1")
    with pytest.raises(Exception):  # ruff: ignore[assert-raises-exception]
        create_file(p, "b = 2")
    # overwrite=True should succeed
    create_file(p, "b = 2", overwrite=True)
    assert p.read_text() == "b = 2"


def test_append_file(tmp_path: Path) -> None:
    """Test if append_file works.

    :param tmp_path: Temporary directory path from pytest.
    :return: None
    """
    p = tmp_path / "log.txt"
    write_file(p, "first line\n")
    append_file(p, "second line\n")
    assert p.read_text() == "first line\nsecond line\n"


def test_create_from_template(tmp_path: Path) -> None:
    """Test if create_from_template works.

    :param tmp_path: Temporary directory path from pytest.
    :return: None
    """
    template = tmp_path / "template.txt"
    template.write_text("Hello, {name}!")
    dest = tmp_path / "dest.txt"
    create_from_template(template, dest, replace_vars={"name": "Alice"})
    assert dest.read_text() == "Hello, Alice!"


def test_create_project_scaffold(tmp_path: Path) -> None:
    """Test if create_project_scaffold works.

    :param tmp_path: Temporary directory path from pytest.
    :return: None
    """
    root = tmp_path / "myproj"
    scaffold_path = create_project_scaffold(str(root), "myproj")
    scaffold = Path(scaffold_path)
    assert scaffold.exists()
    assert (scaffold / "src" / "myproj" / "__init__.py").exists()
    assert (scaffold / "tests" / "test_smoke.py").exists()


# ---------------------------------------------------------------------------
# Tests for the CLI
# ---------------------------------------------------------------------------


def test_cli_create(runner: CliRunner, tmp_path: Path) -> None:
    """Test the `create` subcommand.

    :param runner: CliRunner instance from pytest.
    :param tmp_path: Temporary directory path from pytest.
    :return: None
    """
    file_path = tmp_path / "new.txt"
    result = runner.invoke(
        cli_app, ["create", str(file_path), "--content", "Hello"]
    )
    assert result.exit_code == 0
    assert file_path.read_text() == "Hello"


def test_cli_append(runner: CliRunner, tmp_path: Path) -> None:
    """Test the `append` subcommand.

    :param runner: CliRunner instance from pytest.
    :param tmp_path: Temporary directory path from pytest.
    :return: None
    """
    file_path = tmp_path / "out.txt"
    write_file(file_path, "first\n")
    result = runner.invoke(
        cli_app, ["append", str(file_path), "--content", "second\n"]
    )
    assert result.exit_code == 0
    assert file_path.read_text() == "first\nsecond\n"


def test_cli_scaffold(runner: CliRunner, tmp_path: Path) -> None:
    """Test the `scaffold` subcommand.

    :param runner: CliRunner instance from pytest.
    :param tmp_path: Temporary directory path from pytest.
    :return: None
    """
    result = runner.invoke(
        cli_app, ["scaffold", str(tmp_path), "--name", "demo"]
    )
    assert result.exit_code == 0
    assert (tmp_path / "src" / "demo").exists()
    assert (tmp_path / "tests").exists()
    assert (tmp_path / "requirements.txt").exists()
    assert (tmp_path / "README.qmd").exists()


def test_cli_py2ipynb(runner: CliRunner, tmp_path: Path) -> None:
    """Test the `py2ipynb` subcommand.

    :param runner: CliRunner instance from pytest.
    :param tmp_path: Temporary directory path from pytest.
    :return: None
    """
    py_file = tmp_path / "app.py"
    py_file.write_text("# %%\nprint('hi')")
    nb_file = tmp_path / "app.ipynb"
    result = runner.invoke(cli_app, ["py2ipynb", str(py_file), str(nb_file)])
    assert result.exit_code == 0
    assert nb_file.is_file()


def test_cli_docs(runner: CliRunner, tmp_path: Path) -> None:
    """Test the `docs` subcommand.

    :param runner: CliRunner instance from pytest.
    :param tmp_path: Temporary directory path from pytest.
    :return: None
    """
    # Create output directory
    output_dir = tmp_path / "docs"
    output_dir.mkdir()

    # Create a simple README.qmd to test overwrite behavior
    (output_dir / "README.qmd").write_text("Test content")

    # Run the command
    result = runner.invoke(cli_app, ["docs", f"--output-dir={output_dir!s}"])

    # Check results
    assert result.exit_code == 0
    assert (output_dir / "README.qmd").exists()
    assert (output_dir / "CODE_AGENT.qmd").exists()
    assert (output_dir / "FILES.qmd").exists()


# ---------------------------------------------------------------------------
# Tests for the agent factory (LLM-independent)
# ---------------------------------------------------------------------------


class DummyLLM(BaseChatModel):
    """A dummy LLM for testing purposes.

    It always returns the same message, regardless of input.

    Attributes:
        _identifying_params: A dictionary of identifying parameters.
        :meta private:
    """

    @property
    def _identifying_params(self) -> dict[str, Any]:
        """Access a dictionary of identifying parameters.

        :return: An empty dictionary.
        """
        return {}

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> ChatResult:  # ty: ignore[invalid-method-override]
        """Generate a dummy chat response.

        :param messages: List of messages (ignored).
        :param stop: Stop sequences (ignored).
        :param kwargs: Additional keyword arguments (ignored).
        :return: A dummy ChatResult.
        """
        return ChatResult(
            generations=[
                ChatGeneration(message=AIMessage(content="Hello from DummyLLM"))
            ]
        )

    def bind_tools(
        self, tools: list[BaseTool], **kwargs: Any
    ) -> Runnable[Any, BaseMessage]:  # ty: ignore[invalid-method-override]
        """Bind tools to the LLM (dummy implementation).

        :param tools: List of tools to bind.
        :param kwargs: Additional keyword arguments.
        :return: The LLM instance itself.
        """
        return self

    @property
    def _llm_type(self) -> str:
        """Access the type of llm.

        :return: The type of the language model.
        """
        return "dummy-chat-model"


def test_build_agent_returns_runnable(tmp_path: Path) -> None:
    """Verify that build_agent returns a LangChain Runnable.

    :param tmp_path: Temporary directory path from pytest.
    :return: None
    """
    dummy_llm_instance = DummyLLM()
    # No tools needed for this basic test
    agent_runnable = build_agent(dummy_llm_instance, [])
    assert isinstance(agent_runnable, Runnable), (
        "build_agent should return a Runnable"
    )
    assert agent_runnable is not None, "Agent Runnable should not be None"

    # Test a basic invocation
    config = {"configurable": {"thread_id": str(uuid7())}}
    result = agent_runnable.invoke(
        {"messages": [HumanMessage(content="test")]},
        config=config,  # ty: ignore[invalid-argument-type]
    )
    final_message = result["messages"][-1]
    assert isinstance(final_message, AIMessage)
    assert final_message.content == "Hello from DummyLLM"


def test_load_config(tmp_path: Path) -> None:
    """Test the ``load_config`` function.

    :param tmp_path: Temporary directory path from pytest.
    :return: None
    """
    cfg_file = tmp_path / "llm_config.json"
    cfg_file.write_text(json.dumps({"model": "gpt-oss:20b"}))
    # Convert Path to string before passing to load_config
    cfg = load_config(str(cfg_file))
    assert cfg["model"] == "gpt-oss:20b"


# ---------------------------------------------------------------------------
# Tests for persistent agent streaming behavior
# ---------------------------------------------------------------------------


def test_persistent_agent_chat_streams_when_supported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the runnable supports ``astream_events``, ``PersistentAgent.chat`` should stream content.

    :param tmp_path: Temporary directory path from pytest.
    :param monkeypatch: Monkeypatch fixture from pytest.
    :return: None
    """
    from code_agent.agents.persistent_agent import PersistentAgent

    state_file = tmp_path / "state.json"
    monkeypatch.setattr(PersistentAgent, "_state_file", state_file)

    streamed_text = "streamed reply"
    agent_runnable = MagicMock()
    agent_runnable.astream_events.return_value = iter([
        {
            "event": "on_chat_model_stream",
            "data": {"chunk": MagicMock(content=streamed_text)},
        }
    ])

    agent = PersistentAgent(llm=MagicMock(), tools=[])
    agent.agent = agent_runnable
    agent.thread_id = "thread-123"
    agent.conversation_history = []

    response = agent.chat("hello")

    assert response == streamed_text
    assert state_file.exists()


def test_persistent_agent_chat_falls_back_to_invoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When streaming is unavailable, ``PersistentAgent.chat`` should fall back to ``invoke``.

    :param tmp_path: Temporary directory path from pytest.
    :param monkeypatch: Monkeypatch fixture from pytest.
    :return: None
    """
    from code_agent.agents.persistent_agent import PersistentAgent

    state_file = tmp_path / "state.json"
    monkeypatch.setattr(PersistentAgent, "_state_file", state_file)

    agent_runnable = MagicMock()
    message = MagicMock()
    message.content = "blocking reply"
    agent_runnable.invoke.return_value = {"messages": [message]}
    del agent_runnable.astream_events

    agent = PersistentAgent(llm=MagicMock(), tools=[])
    agent.agent = agent_runnable
    agent.thread_id = "thread-456"
    agent.conversation_history = []

    response = agent.chat("hello")

    assert response == "blocking reply"
