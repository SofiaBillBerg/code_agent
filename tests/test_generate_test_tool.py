"""Unit test for the ``GenerateTestTool`` LangChain tool.

The test exercises the following behavior:
1. A Python file containing a simple function can be supplied.
2. The tool writes a ``tests/`` directory next to the input file.
3. Inside that directory a ``test_<module>.py`` file is generated.
"""

import textwrap

from pathlib import Path

import pytest

# Import the tool from the public API
from code_agent.tools.generate_test_tool import GenerateTestTool


@pytest.fixture
def sample_py(tmp_path: Path) -> Path:
    """Create a tiny Python module that can be used as input.

    :param tmp_path: Temporary directory.
    :return: Path to a sample Python file.
    """
    file = tmp_path / "sample.py"
    file.write_text(
        textwrap.dedent(
            """
                            def add(a, b):
                                '''
                                Add two numbers together.

                                :param a: First number.
                                :param b: Second number.
                                :return: Sum of a and b.
                                '''
                                return a + b
                            """
        )
    )
    return file


def test_generate_test_tool_executes(sample_py: Path) -> None:
    """Running the tool should create a tests/ directory with a test module.

    :param sample_py: Path to a sample Python file.
    :return: None
    """
    tool = GenerateTestTool(root_dir=sample_py.parent)
    # The tool returns a string confirming the test file was created.
    result, _ = tool._run(str(sample_py))  # _run returns a tuple
    assert "Generated test scaffold" in result, (
        "Tool should confirm test file creation"
    )

    # Verify that the tests folder exists
    tests_dir = sample_py.parent / "tests"
    assert tests_dir.exists() and tests_dir.is_dir()

    # Look for a generated test file
    test_files = list(tests_dir.glob("test_*.py"))
    assert test_files, "No test file was generated"

    assert "def test_sample_smoke" in test_files[0].read_text()


def test_generate_test_tool_invalid_file(tmp_path: Path) -> None:
    """Providing a non-Python file should raise an error.

    :param tmp_path: Temporary directory.
    :return: None
    """
    non_py = tmp_path / "not_py.txt"
    non_py.write_text("just text")
    tool = GenerateTestTool(root_dir=tmp_path)
    with pytest.raises(ValueError, match="is not a Python file"):
        tool._run(str(non_py))
