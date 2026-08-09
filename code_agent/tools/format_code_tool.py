# tools/format_code_tool.py
from __future__ import annotations

import shutil
import subprocess

from pathlib import Path
from typing import Any, Literal

from langchain.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from .edit_file_tool import FileObject


class FormatCodeArgs(BaseModel):
    """Args for the format-code tool."""

    file_path: str = Field(..., description="Path to the file to format")
    mode: str = Field("auto", description="Mode: auto|python|r")


class FormatCodeTool(BaseTool):
    """Format a source file."""

    name: str = "format-code"
    description: str = (
        "Format a source file. For python files, run black and isort if available. "
        "For R files, optionally run styler if available. Returns a FileObject."
    )
    response_format: Literal["content", "content_and_artifact"] = (
        "content_and_artifact"
    )
    args_schema: type[BaseModel] = FormatCodeArgs  # pyrefly: ignore[bad-override-mutable-attribute]

    root: Path

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, root_dir: Path, **kwargs):
        """Initialize the tool.

        :param root_dir: The root directory of the project.
        :param kwargs: Additional arguments.
        :return: None
        """
        super().__init__(root=Path(root_dir).expanduser().resolve(), **kwargs)

    def _run(self, **kwargs: Any) -> tuple[str, FileObject]:
        """Format a source file.

        If the file is a Python file, run black and isort if available.
        If the file is an R file, optionally run styler if available.

        :param kwargs : file path
        :param mode : auto|python|r
        :return:
        """
        file_path: str = kwargs.get("file_path", "")
        mode: str = kwargs.get("mode", "auto")
        p = self.root / file_path
        if not p.exists():
            return (
                f"❌ File not found: {p}",
                FileObject(path=p, contents="", status="error"),
            )

        ext = p.suffix.lower()
        if mode == "auto":
            if ext == ".py":
                mode = "python"
            elif ext in {".r", ".R"}:
                mode = "r"

        # Delegate formatting to helper methods to reduce complexity
        if mode == "python":
            ok, msg = self._format_python(p)
        elif mode == "r":
            ok, msg = self._format_r(p)
        else:
            return (
                f"❌ Unknown mode: {mode}",
                FileObject(path=p, contents="", status="error"),
            )

        if not ok:
            return (
                f"❌ Formatting failed: {msg}",
                FileObject(path=p, contents="", status="error"),
            )

        new_contents = p.read_text(encoding="utf-8")
        return (
            f"✅ Formatted {p}",
            FileObject(path=p, contents=new_contents, status="formatted"),
        )

    def _format_python(self, p: Path) -> tuple[bool, str]:
        """Run python formatters (isort, black) if available.

        :param p: Path to the file to format.
        :return: (success, message).
        """
        try:
            if shutil.which("isort"):
                subprocess.run(["isort", str(p)], check=False)
            if shutil.which("black"):
                subprocess.run(["black", str(p)], check=False)
            return True, ""
        except Exception as e:
            return False, str(e)

    def _format_r(self, p: Path) -> tuple[bool, str]:
        """Run R styler via Rscript if available.

        :param p: Path to the file to format.
        :return: (success, message).
        """
        try:
            if shutil.which("Rscript"):
                rcmd = f"styler::style_file('{p!s}')"
                subprocess.run(["Rscript", "-e", rcmd], check=False)
            return True, ""
        except Exception as e:
            return False, str(e)

    async def _arun(self, **kwargs: Any) -> tuple[str, FileObject]:
        """Async wrapper for _run.

        :param kwargs: Keyword arguments for _run.
        :return: Tuple of (message, FileObject).
        """
        return self._run(**kwargs)
