"""
Unit tests for the public helpers in `code_agent.core`.
"""

import textwrap
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from code_agent.agents.base_agent import build_agent, create_default_tools
from code_agent.core import append_file, create_from_template
from code_agent.docs_generator import generate_quarto_docs
from code_agent.file_generator import py_to_ipynb, write_file


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


def test_create_and_append(tmp_path: Path, dummy_llm: BaseChatModel) -> None:
    # We need to create an agent to get the root_dir for tools
    tools = create_default_tools(root_dir = str(tmp_path), llm = dummy_llm)
    build_agent(
            llm = dummy_llm, tools = tools
            )  # Agent is not directly used here, but its creation sets up the context

    # Test creating a file
    file_path = tmp_path / "hello.md"
    write_file(file_path, "# Hi")
    assert file_path.exists()

    # Test appending to the file
    append_file(file_path, "\nMore")

    # Verify content
    content = file_path.read_text(encoding = "utf-8")
    assert "# Hi" in content
    assert "More" in content


def test_templates_and_nb(tmp_path: Path, dummy_llm: BaseChatModel) -> None:
    # Agent creation to ensure context is set up
    tools = create_default_tools(root_dir = str(tmp_path), llm = dummy_llm)
    build_agent(llm = dummy_llm, tools = tools)

    # Test template creation
    template_path = tmp_path / "template.txt"
    template_path.write_text("# {title}\nThis is a template.")

    output_path = tmp_path / "output.md"
    result_path = create_from_template(
            template_path, output_path, replace_vars = {"title": "Test Title"}
            )
    assert result_path.exists()

    # Test Python to notebook conversion
    py_path = tmp_path / "test.py"
    py_path.write_text('# %%\nprint("Hello, World!")\n')

    nb_path = tmp_path / "test.ipynb"
    result_nb = py_to_ipynb(py_path, nb_path)
    assert result_nb.is_file()


@pytest.fixture
def tmp_file(tmp_path: Path) -> Path:
    return tmp_path / "file.txt"


def test_write_and_append(tmp_file: Path) -> None:
    write_file(tmp_file, "line1\n")
    assert tmp_file.read_text() == "line1\n"

    append_file(tmp_file, "line2\n")
    assert tmp_file.read_text() == "line1\nline2\n"


def test_convert_py_to_nb(tmp_path: Path) -> None:
    """The notebook should contain the original code as a code cell."""
    script_path = tmp_path / "script.py"
    script = textwrap.dedent(
            """
                    def greet():
                        return "hello"
                    """
            )
    script_path.write_text(script)
    notebook_path = py_to_ipynb(script_path, tmp_path / "greet.ipynb")
    assert notebook_path.exists()
    content = notebook_path.read_text()
    # The JSON must include the source of the function
    assert "def greet()" in content
    assert "hello" in content


def test_generate_docs_no_llm(tmp_path: Path) -> None:
    """The docs generator should create a minimal output folder."""
    output_dir = tmp_path / "docs"
    docs = generate_quarto_docs(output_dir = output_dir, use_llm = False)
    assert output_dir.exists(), "Docs output directory should exist"
    # Basic check: a README.qmd file is produced
    assert len(docs) > 0
    assert (output_dir / "README.qmd").exists()
