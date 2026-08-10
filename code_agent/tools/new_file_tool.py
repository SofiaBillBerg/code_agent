"""Tool to create new files.

Delegates actual file creation to :func:`code_agent.core.create_file`
so that atomic writes, parent-directory creation and overwrite checks
are centralized in one place.
"""

from __future__ import annotations

import logging
import shutil

from pathlib import Path
from typing import Any, Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from code_agent.file_generator import create_file

from .edit_file_tool import FileObject

log = logging.getLogger(__name__)


class NewFileArgs(BaseModel):
    """Arguments for creating a new file."""

    file_path: str = Field(
        ...,
        description="The full path, including the filename, where the new file should be created.",
    )
    content: str = Field(
        ..., description="The content to be written into the new file."
    )


class NewFileTool(BaseTool):
    """Tool for creating new files."""

    name: str = "new-file"
    description: str = (
        "Create a new file with the given content. "
        "Use this when the user asks to create a file that does not exist yet. "
        "Pass the path relative to the project root."
    )
    response_format: Literal["content", "content_and_artifact"] = (
        "content_and_artifact"
    )
    args_schema: type[BaseModel] = (
        NewFileArgs  # pyrefly: ignore[bad-override-mutable-attribute]
    )

    root: Path

    root: Path

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        """Initialize the NewFileTool with the root directory.

        :param root_dir: The root directory for file operations.
        :param kwargs: Additional keyword arguments.
        :return: None
        """
        super().__init__(
            root=Path(root_dir).expanduser().resolve(), **kwargs
        )  # ruff: ignore [ARG002]

    def _run(
        self, file_path: str, content: str, overwrite: bool = False
    ) -> tuple[str, FileObject]:
        """Create a new file at the specified path with the given content.

        Actual file creation is delegated to :func:`code_agent.core.create_file`
        so that atomic writes and parent-directory creation are centralized.

        :param file_path: The path where the new file should be created.
        :param content: The content to be written into the new file.
        :param overwrite: Whether to overwrite the file if it already exists.
        :return: A tuple containing a message and a FileObject.
        """
        if not file_path:
            return (
                "❌ Error: 'file_path' cannot be empty.",
                FileObject(path=Path(), contents="", status="error"),
            )

        full_path = self.root / file_path

        try:
            # Create a backup before overwriting if the file already exists.
            backup_status = "no_backup"
            if full_path.exists() and overwrite:
                backup_path = full_path.with_suffix(full_path.suffix + ".bak")
                try:
                    shutil.copy(full_path, backup_path)
                    backup_status = "backup_created"
                    log.info(f"Backup created for overwrite: {backup_path}")
                except Exception as e:
                    backup_status = "backup_failed"
                    log.exception(
                        f"Failed to create backup for {full_path} during overwrite: {e}"
                    )

            # Delegate actual file creation to the shared helper.
            create_file(full_path, content, overwrite=overwrite)

            message = f"✅ Successfully created {full_path}"
            if backup_status == "backup_failed":
                message += " (⚠️ Backup failed!)"
            elif backup_status == "backup_created":
                message += " (Original backed up)"

            return (
                message,
                FileObject(path=full_path, contents=content, status="created"),
            )
        except Exception as e:
            log.exception(f"Error creating file {full_path}: ")
            return (
                f"❌ Error creating file: {e}",
                FileObject(path=full_path, contents="", status="error"),
            )

    async def _arun(
        self, file_path: str, content: str, overwrite: bool = False
    ) -> tuple[str, FileObject]:
        """Async version."""
        return self._run(file_path, content, overwrite)
