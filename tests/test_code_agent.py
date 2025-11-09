"""Minimal test‑suite for the *code_agent* package.

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

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from typer.testing import CliRunner

from code_agent.agents.base_agent import build_agent
from code_agent.cli import app as cli_app
from code_agent.core import (append_file, create_file, create_from_template, create_project_scaffold, py_to_ipynb, )
from code_agent.file_generator import write_file
from code_agent.main import load_config


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# Tests for the core helpers
# ---------------------------------------------------------------------------


def test_write_and_read(tmp_path: Path) -> None:
    p = tmp_path / "hello.txt"
    write_file(p, "Hello, world!")
    assert p.read_text(encoding = "utf-8") == "Hello, world!"


def test_create_file_overwrite(tmp_path: Path) -> None:
    p = tmp_path / "foo.py"
    create_file(p, "a = 1")
    with pytest.raises(Exception):
        create_file(p, "b = 2")
    # overwrite=True should succeed
    create_file(p, "b = 2", overwrite = True)
    assert p.read_text() == "b = 2"


def test_append_file(tmp_path: Path) -> None:
    p = tmp_path / "log.txt"
    write_file(p, "first line\n")
    append_file(p, "second line\n")
    assert p.read_text() == "first line\nsecond line\n"


def test_create_from_template(tmp_path: Path) -> None:
    template = tmp_path / "template.txt"
    template.write_text("Hello, {name}!")
    dest = tmp_path / "dest.txt"
    create_from_template(template, dest, replace_vars = {"name": "Alice"})
    assert dest.read_text() == "Hello, Alice!"


def test_py_to_ipynb(tmp_path: Path) -> None:
    src = tmp_path / "script.py"
    src.write_text("# %%\nprint('hello')")
    nb = py_to_ipynb(src, src.with_suffix(".ipynb"))
    assert nb.suffix == ".ipynb"
    assert nb.is_file()


def test_create_project_scaffold(tmp_path: Path) -> None:
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
    file_path = tmp_path / "new.txt"
    result = runner.invoke(
            cli_app, ["create", str(file_path), "--content", "Hello"]
            )
    assert result.exit_code == 0
    assert file_path.read_text() == "Hello"


def test_cli_append(runner: CliRunner, tmp_path: Path) -> None:
    file_path = tmp_path / "out.txt"
    write_file(file_path, "first\n")
    result = runner.invoke(
            cli_app, ["append", str(file_path), "--content", "second\n"]
            )
    assert result.exit_code == 0
    assert file_path.read_text() == "first\nsecond\n"


def test_cli_scaffold(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(
            cli_app, ["scaffold", str(tmp_path), "--name", "demo"]
            )
    assert result.exit_code == 0
    assert (tmp_path / "src" / "demo").exists()
    assert (tmp_path / "tests").exists()
    assert (tmp_path / "requirements.txt").exists()
    assert (tmp_path / "README.qmd").exists()


def test_cli_py2ipynb(runner: CliRunner, tmp_path: Path) -> None:
    py_file = tmp_path / "app.py"
    py_file.write_text("# %%\nprint('hi')")
    nb_file = tmp_path / "app.ipynb"
    result = runner.invoke(cli_app, ["py2ipynb", str(py_file), str(nb_file)])
    assert result.exit_code == 0
    assert nb_file.is_file()


def test_cli_docs(runner: CliRunner, tmp_path: Path) -> None:
    # Create output directory
    output_dir = tmp_path / "docs"
    output_dir.mkdir()

    # Create a simple README.qmd to test overwrite behavior
    (output_dir / "README.qmd").write_text("Test content")

    # Run the command
    result = runner.invoke(
            cli_app, ["docs", f"--output-dir={str(output_dir)}"]
            )

    # Check results
    assert result.exit_code == 0
    assert (output_dir / "README.qmd").exists()
    assert (output_dir / "CODE_AGENT.qmd").exists()
    assert (output_dir / "FILES.qmd").exists()


# ---------------------------------------------------------------------------
# Tests for the agent factory (LLM‑independent)
# ---------------------------------------------------------------------------


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


def test_build_agent_returns_runnable(tmp_path: Path) -> None:
    """Verify that build_agent returns a LangChain Runnable."""
    dummy_llm_instance = DummyLLM()
    # No tools needed for this basic test
    agent_runnable = build_agent(dummy_llm_instance, [])
    assert isinstance(
            agent_runnable, Runnable
            ), "build_agent should return a Runnable"
    assert agent_runnable is not None, "Agent Runnable should not be None"

    # Test a basic invocation
    result = agent_runnable.invoke(
            {"messages": [HumanMessage(content = "test")]}
            )
    final_message = result["messages"][-1]
    assert isinstance(final_message, AIMessage)
    assert final_message.content == "Hello from DummyLLM"


def test_load_config(tmp_path: Path) -> None:
    cfg_file = tmp_path / "llm_config.json"
    cfg_file.write_text(json.dumps({"model": "gpt-oss:20b"}))
    # Convert Path to string before passing to load_config
    cfg = load_config(str(cfg_file))
    assert cfg["model"] == "gpt-oss:20b"
