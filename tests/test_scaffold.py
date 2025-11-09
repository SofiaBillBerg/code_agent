"""Test suite for the *project scaffold* generator.

The tests exercise the public helper :func:`code_agent.scaffold.create_project_scaffold` and verify that the
expected directory structure is created, that the ``overwrite`` flag behaves correctly and that the
function raises a clear error when the ``root`` argument is not a directory.
"""

from pathlib import Path

import pytest

# Import the public API that the tests exercise
from code_agent.exceptions import CodeAgentError
from code_agent.scaffold import create_project_scaffold


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def scaffold_root(tmp_path: Path) -> Path:
    """Return a temporary directory that will act as the scaffold root.

    The fixture returns a :class:`pathlib.Path` instance so the tests can
    freely manipulate the filesystem without leaking temporary files.
    """
    return tmp_path


# ---------------------------------------------------------------------------
# Helper helpers
# ---------------------------------------------------------------------------


def _assert_expected_files(root: Path, project_name: str) -> None:
    """Assert that *root* contains the expected scaffold files and directories."""

    expected_dirs = ["docs", "docs/styles", f"src/{project_name}", "tests", ".github/workflows", ]

    expected_files = ["README.qmd", "requirements.txt", "docs/index.qmd", "tests/test_smoke.py",
                      f"src/{project_name}/__init__.py", ".github/workflows/ci.yml", ]

    for dir_path in expected_dirs:
        full_path = root / dir_path
        assert (full_path.is_dir()), f"Expected directory {dir_path} to be created"

    for file_path in expected_files:
        full_path = root / file_path
        assert full_path.is_file(), f"Expected file {file_path} to be created"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_create_project_scaffold_overwrite(scaffold_root: Path) -> None:
    """Verify that the ``overwrite`` flag controls whether existing files are replaced."""
    # Arrange: write a custom README that should be overwritten.
    readme_path = scaffold_root / "README.qmd"
    readme_path.write_text("original")

    # Act: create the scaffold with the overwrite flag.
    project_name = "my_project"
    root_str = create_project_scaffold(
            str(scaffold_root), project_name = project_name, overwrite = True
            )
    root = Path(root_str)

    # Assert: the root is returned as a Path and exists.
    assert isinstance(root, Path), "Returned root should be a pathlib.Path"
    assert root.exists() and root.is_dir(), "Root directory should exist"

    # The README should contain the new content.
    assert ("Generated scaffold" in readme_path.read_text()), "README.qmd content did not match the expected value"

    # All the default scaffold files should still be present.
    _assert_expected_files(root, project_name)


def test_create_project_scaffold_no_overwrite(scaffold_root: Path) -> None:
    """Verify that with overwrite=False, an error is raised if files exist."""
    # Arrange: write a custom README that should cause an error.
    readme_path = scaffold_root / "README.qmd"
    readme_path.write_text("original")

    # Act & Assert: create the scaffold without the overwrite flag.
    project_name = "my_project"
    with pytest.raises(FileExistsError):
        create_project_scaffold(
                str(scaffold_root), project_name = project_name, overwrite = False
                )


def test_create_project_scaffold_success(scaffold_root: Path) -> None:
    """The scaffold should create the expected directory structure when no file exists.

    The test simply calls :func:`create_project_scaffold` and verifies that
    the root directory and the default files are present.
    """
    project_name = "my_project"
    root_str = create_project_scaffold(
            str(scaffold_root), project_name = project_name
            )
    root = Path(root_str)
    assert isinstance(root, Path), "Returned root should be a pathlib.Path"
    assert root.exists() and root.is_dir(), "Root directory should exist"
    _assert_expected_files(root, project_name)


def test_create_project_scaffold_invalid_root(scaffold_root: Path) -> None:
    """Providing a file path instead of a directory should raise a ``CodeAgentError``.

    The test creates a file inside the temporary directory and then passes
    that file's path to :func:`create_project_scaffold`.  The function is
    expected to detect that the supplied path is not a directory and raise
    a clear ``CodeAgentError``.
    """
    file_as_root = scaffold_root / "not_a_dir.txt"
    file_as_root.write_text("oops")

    with pytest.raises(CodeAgentError):
        create_project_scaffold(
                str(file_as_root), project_name = "my_project", overwrite = True
                )

# ---------------------------------------------------------------------------
# End of file
# ---------------------------------------------------------------------------
