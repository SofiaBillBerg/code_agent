# tests/test_file_generator.py
"""
Unit tests for the low‑level file helpers in ``code_agent.file_generator``.
"""

from pathlib import Path

import pytest

# Import the helpers from the package
from code_agent.file_generator import py_to_ipynb, write_file


@pytest.fixture
def tmp_file(tmp_path: Path) -> Path:
    """Return a fresh, non‑existent file inside the temporary directory."""
    return tmp_path / "hello.txt"


def test_write_text_file(tmp_file: Path) -> None:
    """Writing a simple text file should succeed and contain the same content."""
    write_file(content = "content", target = tmp_file)
    assert tmp_file.read_text() == "content"


def test_write_text_file_overwrite(tmp_file: Path) -> None:
    """Overwriting an existing file should replace its contents."""
    write_file(content = "first", target = tmp_file)
    write_file(content = "second", target = tmp_file, mode = "w")
    assert tmp_file.read_text() == "second"


def test_script_to_notebook(tmp_path: Path) -> None:
    """The notebook should contain the original code as a code cell."""
    script_path = tmp_path / "script.py"
    script_path.write_text("print('hi')")
    nb_path = py_to_ipynb(script_path, tmp_path / "demo.ipynb")
    assert nb_path.exists()
    assert "print('hi')" in nb_path.read_text()
