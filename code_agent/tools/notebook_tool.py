# tools/notebook_tool.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import nbformat
from langchain.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from .edit_file_tool import FileObject


class NotebookArgs(BaseModel):
    file_path: str = Field(
            ..., description = "Path to the notebook to create or edit"
            )
    content: str = Field("", description = "Markdown or code content to insert")
    mode: str = Field("create", description = "Mode: create|append|replace")


class NotebookTool(BaseTool):
    name: str = "notebook"
    description: str = ("Create or edit Jupyter notebooks (.ipynb). Mode create: create a minimal notebook; "
                        "append: add a markdown cell with content; replace: replace entire notebook with given "
                        "content.")
    response_format: Literal["content_and_artifact"] = "content_and_artifact"
    args_schema: type[BaseModel] = NotebookArgs

    root: Path

    model_config = ConfigDict(arbitrary_types_allowed = True)

    def __init__(self, root_dir: str | Path, **kwargs):
        """
        Initializes the NotebookTool with the given root directory.
            Args:
                root_dir (str | Path): The root directory for the notebook tool.
                **kwargs: Additional keyword arguments.
            Returns: None
        """
        super().__init__(root = Path(root_dir).expanduser().resolve(), **kwargs)

    def _run(self, **kwargs: Any) -> tuple[str, FileObject]:
        file_path: str = kwargs.get("file_path")
        content: str = kwargs.get("content", "")
        mode: str = kwargs.get("mode", "create")

        nb_path = self.root / file_path
        try:
            if mode == "create":
                nb = nbformat.v4.new_notebook()
                nb.cells.append(nbformat.v4.new_markdown_cell(content))
                nb_path.parent.mkdir(parents = True, exist_ok = True)
                nbformat.write(nb, str(nb_path))
                return (f"✅ Created notebook {nb_path}", FileObject(
                        path = nb_path, contents = content, status = "created"
                        ),)
            elif mode == "append":
                if not nb_path.exists():
                    return (f"❌ Notebook not found: {nb_path}",
                            FileObject(path = nb_path, contents = "", status = "error"),)
                nb = nbformat.read(str(nb_path), as_version = 4)
                nb.cells.append(nbformat.v4.new_markdown_cell(content))
                nbformat.write(nb, str(nb_path))
                return (f"✅ Appended notebook {nb_path}", FileObject(
                        path = nb_path, contents = content, status = "appended"
                        ),)
            elif mode == "replace":
                # Interpret content as raw notebook JSON or as a markdown cell
                try:
                    nb_obj = nbformat.reads(content, as_version = 4)
                    nbformat.write(nb_obj, str(nb_path))
                except Exception:
                    nb = nbformat.v4.new_notebook()
                    nb.cells.append(nbformat.v4.new_markdown_cell(content))
                    nb_path.parent.mkdir(parents = True, exist_ok = True)
                    nbformat.write(nb, str(nb_path))
                return (f"✅ Replaced notebook {nb_path}", FileObject(
                        path = nb_path, contents = content, status = "replaced"
                        ),)
            else:
                return (f"❌ Unknown mode: {mode}", FileObject(path = nb_path, contents = "", status = "error"),)
        except Exception as e:
            return (f"❌ Notebook operation failed: {e}", FileObject(path = nb_path, contents = "", status = "error"),)

    async def _arun(self, **kwargs: Any) -> tuple[str, FileObject]:
        return self._run(**kwargs)
