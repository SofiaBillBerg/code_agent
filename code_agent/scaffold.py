"""
Simple project scaffold generator for starting new projects from this template.
Creates a minimal layout: `docs/`, `src/<name>/`, `tests/`, `.GitHub/workflows/`, `requirements.txt`,
and sample files. Intentionally conservative and idempotent.
"""

from __future__ import annotations

from pathlib import Path

from .exceptions import CodeAgentError
from .file_generator import write_file

DEFAULT_REQUIREMENTS = """# basic runtime requirements
pandas
nbformat
"""

WORKFLOW_CONTENT = """name: CI

on:
  push:
    branches: [ main, master ]
  pull_request:
    branches: [ main, master ]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
      - name: Run tests
        run: |
          pytest -q
"""


def _create_directories(root_path: Path, project_name: str) -> None:
    """Create the directory structure for the project."""
    dirs = [root_path / "docs" / "styles", root_path / "src" / project_name, root_path / "tests",
            root_path / ".github" / "workflows", ]
    for d in dirs:
        try:
            d.mkdir(parents = True, exist_ok = True)
        except OSError as exc:
            raise CodeAgentError(
                    f"Failed to create directory {d}: {exc}"
                    ) from exc


def _create_files(root_path: Path, project_name: str, overwrite: bool) -> None:
    """Create the files for the project."""
    files_to_create = {"README.qmd": f"# {project_name}\n\nGenerated scaffold.",
            "requirements.txt": DEFAULT_REQUIREMENTS,
            "docs/index.qmd": f"---\ntitle: {project_name}\nformat: html\n---\n\n# "
                              f"{project_name}\n\nGenerated docs "
                              f"index.", "tests/test_smoke.py": "def test_smoke():\n    assert True\n",
            f"src/{project_name}/__init__.py": "# sample package init\n",
            ".github/workflows/ci.yml": WORKFLOW_CONTENT, }

    for file, content in files_to_create.items():
        path = root_path / file
        if overwrite or not path.exists():
            try:
                write_file(path, content)
            except CodeAgentError as exc:
                raise CodeAgentError(f"Failed to write {file}: {exc}") from exc


def create_project_scaffold(
        root: str, project_name: str = "project", overwrite: bool = False, ) -> str:
    """
    Create a minimal project scaffold in the given directory.
    """
    root_path = Path(root).expanduser().resolve()

    try:
        root_path.mkdir(parents = True, exist_ok = True)
    except OSError as exc:
        raise CodeAgentError(
                f"Failed to create root directory {root_path}: {exc}"
                ) from exc

    if not overwrite and any(
            (root_path / p).exists() for p in ["README.qmd", "src", "tests"]
            ):
        raise FileExistsError(f"Project already exists at {root_path}")

    _create_directories(root_path, project_name)
    _create_files(root_path, project_name, overwrite)

    return str(root_path)


# convenience wrapper for CLI
if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("root", nargs = "?", default = ".")
    p.add_argument("--name", default = "project")
    p.add_argument("--overwrite", action = "store_true")
    args = p.parse_args()
    try:
        create_project_scaffold(
                args.root, project_name = args.name, overwrite = args.overwrite
                )
        print("Scaffold created at", Path(args.root).resolve())
    except (CodeAgentError, FileExistsError) as e:
        print(f"❌ Error creating scaffold: {e}")
