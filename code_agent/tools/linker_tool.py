# tools/linker_tool.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from langchain.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from .edit_file_tool import FileObject


#  Arguments schema


class LinkerArgs(BaseModel):
    """Arguments for reading file contents."""

    file_path: str = Field(..., description="Path to file to read")


# Tool definition
class LinkerTool(BaseTool):
    """Tool for reading file contents."""

    name: str = "linker"
    description: str = (
        "Read and return the full contents of a file. "
        "Returns file contents as string and FileObject artifact."
    )
    response_format: Literal["content", "content_and_artifact"] = (
        "content_and_artifact"
    )
    args_schema: type[BaseModel] = LinkerArgs  # pyrefly: ignore[bad-override-mutable-attribute]

    root: Path

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, root_dir: Path, **kwargs: dict[str, Any]) -> None:
        """Initialize the tool.

        :param root_dir: The root directory to use for file operations.
        :param kwargs: Additional arguments to pass to the parent class.
        :return: None
        """
        super().__init__(root=Path(root_dir).expanduser().resolve(), **kwargs)

    def _run(self, **kwargs: Any) -> tuple[str, FileObject]:
        """Run the tool.

        :param kwargs: The arguments to pass to the tool.
        :return: The result of the tool.
        """
        file_path_str: str = kwargs.get("file_path", "")
        file_path = self.root / file_path_str

        if not file_path.exists():
            return (
                f"❌ File not found: {file_path}",
                FileObject(path=file_path, contents="", status="error"),
            )

        try:
            contents = file_path.read_text(encoding="utf-8")
            return (
                contents,
                FileObject(path=file_path, contents=contents, status="read"),
            )
        except Exception as e:
            return (
                f"❌ Error reading file: {e}",
                FileObject(path=file_path, contents="", status="error"),
            )

    async def _arun(self, **kwargs: Any) -> tuple[str, FileObject]:
        """Async version."""
        return self._run(**kwargs)
