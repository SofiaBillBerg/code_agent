# tools/read_file_tool.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain.tools import BaseTool
from pydantic import BaseModel, Field


class ReadFileArgs(BaseModel):
    """Arguments for reading a file."""

    file_path: str = Field(..., description = "The full path of the file to read.")


class ReadFileTool(BaseTool):
    """Tool for reading the content of a file."""

    name: str = "read-file"
    description: str = ("Use this tool to read the entire content of a file. "
                        "Provide a 'file_path' to the file you want to inspect.")
    args_schema: type[BaseModel] = ReadFileArgs

    root: Path

    def __init__(self, root_dir: str | Path, **kwargs):
        super().__init__(root = Path(root_dir).expanduser().resolve(), **kwargs)

    def _run(self, file_path: str) -> str:
        """Reads the content of the specified file."""
        if not file_path:
            return "❌ Error: 'file_path' cannot be empty."

        full_path = self.root / file_path

        if not full_path.exists():
            return f"❌ Error: File not found at {full_path}"

        if not full_path.is_file():
            return f"❌ Error: Path exists but is not a file: {full_path}"

        try:
            content = full_path.read_text(encoding = "utf-8")
            return f"Content of {file_path}:\n\n---\n{content}\n---"
        except Exception as e:
            return f"❌ Error reading file: {e}"

    async def _arun(self, **kwargs: Any) -> str:
        """Async version."""
        return self._run(**kwargs)
