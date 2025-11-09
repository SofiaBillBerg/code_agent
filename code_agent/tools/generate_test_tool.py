# tools/generate_test_tool.py
from __future__ import annotations

from pathlib import Path
from typing import Literal

from langchain.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from .edit_file_tool import FileObject


class GenerateTestArgs(BaseModel):
    file_path: str = Field(
            ..., description = "Path to the module/file to generate tests for"
            )
    tests_dir: str = Field("tests", description = "Directory to place generated tests")


class GenerateTestTool(BaseTool):
    name: str = "generate-test"
    description: str = ("Generate a basic pytest test file for a given Python module. "
                        "Creates a tests/ directory and a test_<module>.py scaffold.")
    response_format: Literal["content_and_artifact"] = "content_and_artifact"
    args_schema: type[BaseModel] = GenerateTestArgs

    root: Path

    model_config = ConfigDict(arbitrary_types_allowed = True)

    def __init__(self, root_dir: str | Path, **kwargs):
        super().__init__(root = Path(root_dir).expanduser().resolve(), **kwargs)

    def _run(self, file_path: str, tests_dir: str = "tests") -> tuple[str, FileObject]:
        """Generates a basic pytest test file for a given Python module."""

        src = self.root / file_path
        if not src.exists():
            return (f"❌ Source file not found: {src}", FileObject(path = src, contents = "", status = "error"),)

        module_name = Path(file_path).stem
        test_file = self.root / tests_dir / f"test_{module_name}.py"
        test_file.parent.mkdir(parents = True, exist_ok = True)

        scaffold = f"""
import pytest
from {module_name} import *


def test_placeholder():
    # Replace this placeholder with meaningful tests for `{module_name}`
    assert True
"""
        if test_file.exists():
            return (f"❌ Test file already exists: {test_file}", FileObject(
                    path = test_file, contents = test_file.read_text(encoding = "utf-8"), status = "exists", ),)

        test_file.write_text(scaffold, encoding = "utf-8")
        return (f"✅ Generated test scaffold: {test_file}",
                FileObject(path = test_file, contents = scaffold, status = "created"),)

    async def _arun(
            self, file_path: str, tests_dir: str = "tests"
            ) -> tuple[str, FileObject]:
        """Async version."""
        return self._run(file_path, tests_dir)
