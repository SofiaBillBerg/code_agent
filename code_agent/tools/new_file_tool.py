# tools/new_file_tool.py
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Literal

from langchain.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from .edit_file_tool import FileObject

log = logging.getLogger(__name__)


class NewFileArgs(BaseModel):
    """Arguments for creating a new file."""

    file_path: str = Field(
            ..., description = "The full path, including the filename, where the new file should be created.", )
    content: str = Field(
            ..., description = "The content to be written into the new file."
            )


class NewFileTool(BaseTool):
    """Tool for creating new files."""

    name: str = "new-file"
    description: str = ("Use this tool to create a new file with specified content. "
                        "Provide a 'file_path' and the 'content' for the file. "
                        "Example: {'tool': 'new-file', 'arguments': {'file_path': 'src/new_module.py', 'content': '# "
                        "New Python module\\n'}}")
    response_format: Literal["content_and_artifact"] = "content_and_artifact"
    args_schema: type[BaseModel] = NewFileArgs

    root: Path

    model_config = ConfigDict(arbitrary_types_allowed = True)

    def __init__(self, root_dir: str | Path, **kwargs):
        super().__init__(root = Path(root_dir).expanduser().resolve(), **kwargs)

    def _run(
            self, file_path: str, content: str, overwrite: bool = False
            ) -> tuple[str, FileObject]:
        """Creates a new file at the specified path with the given content."""

        if not file_path:
            return ("❌ Error: 'file_path' cannot be empty.",
                    FileObject(path = Path(), contents = "", status = "error"),)

        full_path = self.root / file_path

        try:
            backup_status = "no_backup"
            if full_path.exists():
                if not overwrite:
                    return (f"❌ File already exists: {full_path}. Use 'overwrite=True' to replace it.",
                            FileObject(path = full_path, contents = "", status = "error"),)
                else:
                    # Create a backup before overwriting
                    backup_path = full_path.with_suffix(full_path.suffix + ".bak")
                    try:
                        shutil.copy(full_path, backup_path)
                        backup_status = "backup_created"
                        log.info(f"Backup created for overwrite: {backup_path}")
                    except Exception as e:
                        backup_status = "backup_failed"
                        log.error(
                                f"Failed to create backup for {full_path} during overwrite: {e}",
                                exc_info = True, )  # Continue with the creation, but report backup failure

            full_path.parent.mkdir(parents = True, exist_ok = True)
            full_path.write_text(content, encoding = "utf-8")

            message = f"✅ Successfully created {full_path}"
            if backup_status == "backup_failed":
                message += " (⚠️ Backup failed!)"
            elif backup_status == "backup_created":
                message += " (Original backed up)"

            return (message, FileObject(path = full_path, contents = content, status = "created"),)
        except Exception as e:
            log.error(f"Error creating file {full_path}: {e}", exc_info = True)
            return (f"❌ Error creating file: {e}", FileObject(path = full_path, contents = "", status = "error"),)

    async def _arun(
            self, file_path: str, content: str, overwrite: bool = False
            ) -> tuple[str, FileObject]:
        """Async version."""
        return self._run(file_path, content, overwrite)
