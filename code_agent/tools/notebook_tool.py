"""Tool to generate notebooks."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from .edit_file_tool import FileObject

from langchain_core.tools import BaseTool, tool
import nbformat
from nbformat import NotebookNode
from pydantic import BaseModel, Field

class NotebookArgs(BaseModel):
    """Arguments for the notebook tool.

    Attributes:
        file_path: Path to the notebook to create or edit.
        content: Markdown or code content to insert.
        mode: Mode: create|append|replace.
    """

    file_path: str = Field(
        ..., description="Path to the notebook to create or edit"
    )
    content: str = Field("", description="Markdown or code content to insert")
    mode: str = Field("create", description="Mode: create|append|replace")


def make_notebook_tool(root_dir: Path) -> BaseTool:
    """Create a ``notebook`` tool bound to ``root_dir``.

    The root directory is captured in the closure at construction time so the
    tool is a plain :func:`@tool`-decorated function (no custom ``BaseTool``
    subclass fields), which is how recent langchain-core expects tools to be
    registered.

    :param root_dir: The root directory for the notebook tool.
    :return: A LangChain tool that creates and edits Jupyter notebooks.
    """
    root = Path(root_dir).expanduser().resolve()

    @tool(
        "notebook",
        args_schema=NotebookArgs,
        response_format="content_and_artifact",
        description=(
            "Create or edit Jupyter notebooks (.ipynb). Mode create: create a minimal notebook; "
            "append: add a markdown cell with content; replace: replace entire notebook with given "
            "content."
        ),
    )
    def notebook(
        file_path: str, content: str = "", mode: str = "create"
    ) -> tuple[str, FileObject]:
        """Create or edit a Jupyter notebook.

        :param file_path: Path to the notebook to create or edit.
        :param content: Markdown or code content to insert.
        :param mode: Mode: create|append|replace.
        :return: A tuple containing the result message and a FileObject.
        """
        nb_path = root / file_path
        try:
            if mode == "create":
                nb = nbformat.v4.new_notebook()
                nb.cells.append(nbformat.v4.new_markdown_cell(content))
                nb_path.parent.mkdir(parents=True, exist_ok=True)
                nbformat.write(nb, str(nb_path))
                return (
                    f"✅ Created notebook {nb_path}",
                    FileObject(
                        path=nb_path, contents=content, status="created"
                    ),
                )
            elif mode == "append":
                if not nb_path.exists():
                    return (
                        f"❌ Notebook not found: {nb_path}",
                        FileObject(path=nb_path, contents="", status="error"),
                    )
                nb = cast(
                    NotebookNode, nbformat.read(str(nb_path), as_version=4)
                )

                nb.cells.append(nbformat.v4.new_markdown_cell(content))
                nbformat.write(nb, str(nb_path))
                return (
                    f"✅ Appended notebook {nb_path}",
                    FileObject(
                        path=nb_path, contents=content, status="appended"
                    ),
                )
            elif mode == "replace":
                # Interpret content as raw notebook JSON or as a markdown cell
                try:
                    nb_obj = nbformat.reads(content, as_version=4)
                    nbformat.write(nb_obj, str(nb_path))
                except Exception:
                    nb: NotebookNode = nbformat.v4.new_notebook()
                    nb.cells.append(nbformat.v4.new_markdown_cell(content))
                    nb_path.parent.mkdir(parents=True, exist_ok=True)
                    nbformat.write(nb, str(nb_path))
                return (
                    f"✅ Replaced notebook {nb_path}",
                    FileObject(
                        path=nb_path, contents=content, status="replaced"
                    ),
                )
            else:
                return (
                    f"❌ Unknown mode: {mode}",
                    FileObject(path=nb_path, contents="", status="error"),
                )
        except Exception as e:
            return (
                f"❌ Notebook operation failed: {e}",
                FileObject(path=nb_path, contents="", status="error"),
            )

    return notebook
