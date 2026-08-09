# tests/test_file_generator.py
"""
Unit tests for the low‑level file helpers in ``code_agent.file_generator``.

This is the canonical home for ``write_file`` and ``py_to_ipynb`` coverage;
other test modules exercise those helpers only incidentally (e.g. via the
CLI or agent integration tests), so the dedicated unit coverage lives here
to avoid duplication.
"""

from pathlib import Path

import pytest

from code_agent.exceptions import CodeAgentError
from code_agent.file_generator import py_to_ipynb, write_file


@pytest.fixture
def tmp_file(tmp_path: Path) -> Path:
    """Return a fresh, non‑existent file inside the temporary directory."""
    return tmp_path / "hello.txt"


def test_write_text_file(tmp_file: Path) -> None:
    """Writing a simple text file should succeed and contain the same content."""
    write_file(content="content", target=tmp_file)
    assert tmp_file.read_text() == "content"


def test_write_text_file_overwrite(tmp_file: Path) -> None:
    """Overwriting an existing file should replace its contents."""
    write_file(content="first", target=tmp_file)
    write_file(content="second", target=tmp_file, mode="w")
    assert tmp_file.read_text() == "second"


def test_write_file_to_directory(tmp_path: Path) -> None:
    """Attempting to write to a directory should raise ``CodeAgentError``."""
    with pytest.raises(CodeAgentError, match="Cannot write to a directory"):
        write_file(tmp_path, "content")


def test_write_file_invalid_path() -> None:
    """Provide an invalid path (e.g. a file name with a null byte)."""
    invalid = "invalid\0name.txt"
    with pytest.raises(Exception):  # OSError on linux, ValueError on Windows
        write_file(invalid, "data")


def test_script_to_notebook(tmp_path: Path) -> None:
    """The notebook should contain the original code as a code cell."""
    script_path = tmp_path / "script.py"
    script_path.write_text("print('hi')")
    nb_path = py_to_ipynb(script_path, tmp_path / "demo.ipynb")
    assert nb_path.exists()
    assert "print('hi')" in nb_path.read_text()
