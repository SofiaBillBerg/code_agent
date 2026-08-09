"""Tool to generate tests."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from .edit_file_tool import FileObject

from langchain.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

class GenerateTestArgs(BaseModel):
    """Arguments for the generate-test tool."""

    file_path: str = Field(
        ..., description="Path to the module/file to generate tests for"
    )
    tests_dir: str = Field(
        "tests", description="Directory to place generated tests"
    )


class GenerateTestTool(BaseTool):
    """Tool for generating basic pytest test files."""

    name: str = "generate-test"
    description: str = (
        "Generate a basic pytest test file for a given Python module. "
        "Creates a tests/ directory and a test_<module>.py scaffold."
    )
    response_format: Literal["content", "content_and_artifact"] = (
        "content_and_artifact"
    )
    args_schema: type[BaseModel] = GenerateTestArgs  # pyrefly: ignore[bad-override-mutable-attribute]

    root: Path

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, root_dir: Path, **kwargs) -> None:
        """Initialize the tool with the root directory.

        :param root_dir: The root directory of the project.
        :param kwargs: Additional arguments to pass to the parent class.
        :return: None
        """
        super().__init__(root=Path(root_dir).expanduser().resolve(), **kwargs)

    def _run(
        self, file_path: str, tests_dir: str = "tests"
    ) -> tuple[str, FileObject]:
        """Generate a basic pytest test file for a given Python module.

        :param file_path: Path to the module/file to generate tests for.
        :param tests_dir: Directory to place generated tests.
        :return: Tuple of (message, FileObject)
        """
        src = self.root / file_path
        if not src.exists():
            return (
                f"❌ Source file not found: {src}",
                FileObject(path=src, contents="", status="error"),
            )
        if src.suffix != ".py":
            raise ValueError(f"File {file_path} is not a Python file.")

        module_name = Path(file_path).stem
        test_file = self.root / tests_dir / f"test_{module_name}.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)

        scaffold = f'''
import pytest

import {module_name}


def test_{module_name}_smoke():
    """Smoke test for ``{module_name}``.

    The generated module imports successfully. Replace this with meaningful
    tests for the module's public API.
    """
    assert {module_name} is not None
'''
        if test_file.exists():
            return (
                f"❌ Test file already exists: {test_file}",
                FileObject(
                    path=test_file,
                    contents=test_file.read_text(encoding="utf-8"),
                    status="exists",
                ),
            )

        test_file.write_text(scaffold, encoding="utf-8")
        return (
            f"✅ Generated test scaffold: {test_file}",
            FileObject(path=test_file, contents=scaffold, status="created"),
        )

    async def _arun(
        self, file_path: str, tests_dir: str = "tests"
    ) -> tuple[str, FileObject]:
        """Async version."""
        return self._run(file_path, tests_dir)
