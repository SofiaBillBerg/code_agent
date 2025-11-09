# tools/edit_file_tool.py
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Literal

from langchain.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)


class FileObject(BaseModel):
    """Artifact representing a file."""

    path: Path
    contents: str
    status: str = "success"

    model_config = ConfigDict(arbitrary_types_allowed = True)


class EditFileArgs(BaseModel):
    """Arguments for editing a file."""

    file_path: str = Field(..., description = "Path to the file to edit")
    new_content: str = Field(..., description = "New content for the file")
    mode: str = Field("replace", description = "Mode: replace|append|patch")


class EditFileTool(BaseTool):
    """Tool for editing existing files."""

    name: str = "edit-file"
    description: str = ("Edit an existing file by replacing/appending/patching its content. "
                        "Returns confirmation message and FileObject artifact.")
    response_format: Literal["content_and_artifact"] = "content_and_artifact"
    args_schema: type[BaseModel] = EditFileArgs

    root: Path

    model_config = ConfigDict(arbitrary_types_allowed = True)

    def __init__(self, root_dir: str | Path, **kwargs):
        super().__init__(root = Path(root_dir).expanduser().resolve(), **kwargs)

    def _backup_file(self, path: Path) -> str:
        """Create a backup of the file."""
        if not path.exists():
            return "no_backup"
        backup_path = path.with_suffix(path.suffix + ".bak")
        try:
            shutil.copy(path, backup_path)
            log.info(f"Backup created: {backup_path}")
            return "backup_created"
        except Exception as e:
            log.error(
                    f"Failed to create backup for {path}: {e}", exc_info = True
                    )
            return "backup_failed"

    def _edit_replace(self, path: Path, content: str) -> None:
        path.write_text(content, encoding = "utf-8")

    def _edit_append(self, path: Path, content: str) -> None:
        original_content = path.read_text(encoding = "utf-8")
        path.write_text(original_content + content, encoding = "utf-8")

    def _edit_patch(self, path: Path, content: str) -> None:
        original_content = path.read_text(encoding = "utf-8")
        start_marker = "<!-- AUTOGEN START -->"
        end_marker = "<!-- AUTOGEN END -->"
        if start_marker in original_content and end_marker in original_content:
            pre, rest = original_content.split(start_marker, 1)
            _, post = rest.split(end_marker, 1)
            new_full = (pre + start_marker + "\n" + content + "\n" + end_marker + post)
        else:
            new_full = original_content + "\n" + content
        path.write_text(new_full, encoding = "utf-8")

    def _run(
            self, file_path: str, new_content: str, mode: str = "replace"
            ) -> tuple[str, FileObject]:
        full_path = self.root / file_path

        if not full_path.exists():
            return (f"❌ File not found: {full_path}", FileObject(path = full_path, contents = "", status = "error"),)

        try:
            backup_status = self._backup_file(full_path)

            edit_functions = {"replace": self._edit_replace, "append": self._edit_append, "patch": self._edit_patch, }

            if mode not in edit_functions:
                return (f"❌ Unknown mode: {mode}", FileObject(path = full_path, contents = "", status = "error"),)

            edit_functions[mode](full_path, new_content)
            status = f"edited_{mode}"

            final_contents = full_path.read_text(encoding = "utf-8")
            message = f"✅ Successfully {status} {full_path}"
            if backup_status == "backup_failed":
                message += " (⚠️ Backup failed!)"

            return (message, FileObject(
                    path = full_path, contents = final_contents, status = status
                    ),)
        except Exception as e:
            log.error(
                    f"Error during file edit operation for {full_path}: {e}", exc_info = True, )
            return (f"❌ Error editing file: {e}", FileObject(path = full_path, contents = "", status = "error"),)

    async def _arun(
            self, file_path: str, new_content: str, mode: str = "replace"
            ) -> tuple[str, FileObject]:
        """Async version."""
        return self._run(file_path, new_content, mode)
