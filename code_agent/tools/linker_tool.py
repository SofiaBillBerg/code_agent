"""Tool to read files."""

from __future__ import annotations

from pathlib import Path

from .edit_file_tool import FileObject

from langchain.tools import BaseTool, tool
from pydantic import BaseModel, Field

class LinkerArgs(BaseModel):
    """Arguments for reading file contents.

    Attributes:
        file_path: Path to file to read.
    """

    file_path: str = Field(..., description="Path to file to read")


def make_linker_tool(root_dir: Path) -> BaseTool:
    """Create a ``linker`` tool bound to ``root_dir``.

    The root directory is captured in the closure at construction time so the
    tool is a plain :func:`@tool`-decorated function (no custom ``BaseTool``
    subclass fields), which is how recent langchain-core expects tools to be
    registered.

    :param root_dir: The root directory to use for file operations.
    :return: A LangChain tool that reads file contents.
    """
    root = Path(root_dir).expanduser().resolve()

    @tool(
        "linker",
        args_schema=LinkerArgs,
        response_format="content_and_artifact",
        description=(
                "Read and return the full contents of a file. "
                "Returns file contents as string and FileObject artifact."
        ),
    )
    def linker(file_path: str) -> tuple[str, FileObject]:
        """Read and return the full contents of a file.

        :param file_path: Path to the file to read.
        :return: A tuple of the file contents and a :class:`FileObject` artifact.
        """
        full_path = root / file_path

        if not full_path.exists():
            return (
                f"❌ File not found: {full_path}",
                FileObject(path=full_path, contents="", status="error"),
            )

        try:
            contents = full_path.read_text(encoding="utf-8")
            return (
                contents,
                FileObject(path=full_path, contents=contents, status="read"),
            )
        except Exception as e:
            return (
                f"❌ Error reading file: {e}",
                FileObject(path=full_path, contents="", status="error"),
            )

    return linker
