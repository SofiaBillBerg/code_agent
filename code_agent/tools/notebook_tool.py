"""Tool to generate notebooks."""

from __future__ import annotations

import logging

from pathlib import Path
from typing import cast

import nbformat

from langchain.tools import BaseTool, tool
from nbformat import NotebookNode
from pydantic import BaseModel, Field

from code_agent.exceptions import CodeAgentError
from code_agent.tools.edit_file_tool import FileObject


logger = logging.getLogger(__name__)


def py_to_ipynb(
    py_file: Path,
    output_path: Path | None = None,
    content: str = "",
    mode: str = "create",
) -> Path:  # ruff: ignore[complex-structure]
    """Convert a Python script to a minimal Jupyter notebook.

    The function searches the script for ``# %%`` markers - any text
    following a marker until the next marker (or the file end) becomes a
    separate cell.  If no markers are found, the entire file becomes a
    single cell.

    :param content:
    :param py_file: Path to the input Python file.
    :param output_path: Destination notebook path.  If omitted, ``py_file`` is
        rewritten with a ``.ipynb`` extension.
    :param mode: Mode: create|append|replace.
    :return: Absolute path to the generated notebook.
    """
    if nbformat is None:
        raise CodeAgentError(
            "nbformat is not installed; please install it to use the notebook tool"
        )

    mode = mode.lower()
    py_file = Path(py_file).expanduser().resolve()
    if not py_file.is_file():
        raise CodeAgentError(f"Python file {py_file!s} does not exist")
    if mode not in {"create", "append", "replace"}:
        raise CodeAgentError(f"Unknown mode: {mode!s}")
    if mode == "append" and not py_file.with_suffix(".ipynb").exists():
        raise CodeAgentError(
            f"Cannot append to notebook {py_file.with_suffix('.ipynb')!s} because it does not exist"
        )
    if mode == "replace":
        # Interpret content as raw notebook JSON or as a Markdown cell
        try:
            nb_obj = nbformat.reads(content, as_version=4)
            if output_path is None:
                output_path = py_file.with_suffix(".ipynb")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            nbformat.write(nb_obj, str(output_path))
            return output_path
        except Exception as e:
            raise CodeAgentError(
                f"Error occurred while replacing notebook: {e}"
            )
    if mode == "create" and py_file.with_suffix(".ipynb").exists():
        raise CodeAgentError(
            f"Cannot create notebook {py_file.with_suffix('.ipynb')!s} because it already exists"
        )
    if mode == "append":
        nb = cast(
            nbformat.NotebookNode,
            nbformat.read(str(py_file.with_suffix(".ipynb")), as_version=4),
        )
    else:
        nb = nbformat.v4.new_notebook()
        current_cell_lines: list[str] = []
        with py_file.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip() == "# %%":
                    if current_cell_lines:
                        nb.cells.append(
                            nbformat.v4.new_code_cell(
                                source="".join(current_cell_lines)
                            )
                        )
                        current_cell_lines = []
                else:
                    current_cell_lines.append(line)
            if current_cell_lines:
                nb.cells.append(
                    nbformat.v4.new_code_cell(
                        source="".join(current_cell_lines)
                    )
                )
    if content:
        nb.cells.append(nbformat.v4.new_markdown_cell(content))
    if output_path is None:
        output_path = py_file.with_suffix(".ipynb")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(nb, str(output_path))
    return output_path


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
    output_path: Path | None = Field(
        None, description="Optional output path for the notebook"
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
        name_or_callable="notebook-tool",
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

        am file_path: Path to the notebook to create or edit.
        :param content: Markdown or code content to insert.
        :param mode: Mode: create|append|replace.
        :return: A tuple containing the result message and a FileObject.
        """
        nb_path = root / file_path
        try:  # ruff: ignore[too-many-statements-in-try-clause]
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
