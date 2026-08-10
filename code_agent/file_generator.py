"""Low-level file-system helpers used by the *code_agent* package.

The goal of this module is to provide **pure, synchronous** helpers that
write text files and convert a simple Python script into a minimal Jupyter
Notebook.  All functions are stateless, return a :class:`pathlib.Path`
instance pointing to the created file, and raise a
``CodeAgentError`` (defined in :mod:`code_agent.exceptions`) on
failure.

The module deliberately avoids external dependencies.  The notebook
generation falls back to a hand-crafted JSON if :mod:`nbformat` is not
available.
"""

from __future__ import annotations

import json

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .exceptions import CodeAgentError

try:  # Optional dependency - used only for the notebook path.
    import nbformat  # type: ignore
except Exception:  # pragma: no cover - handled at runtime
    nbformat = None  # type: ignore[assignment]

__all__ = ["create_from_template", "py_to_ipynb", "write_file"]


def write_file(
    target: Path | str,
    content: str,
    *,
    mode: str = "w",
    encoding: str = "utf-8",
) -> Path:
    """Write *content* to *target* atomically.

    The function creates any missing parent directories, writes the
    content to a temporary file first, and then atomically moves the
    temporary file to ``target``.  This prevents partial writes if the
    process is interrupted.

    :param target: Destination file path.
    :param content: Text to write.
    :param mode: File mode - defaults to ``"w"``.
    :param encoding: Text encoding - defaults to ``"utf-8"``.
    :return: The absolute path of the written file.
    """
    target = Path(target).expanduser().resolve()
    if target.is_dir():
        raise CodeAgentError(f"Cannot write to a directory: {target!s}")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        with tmp.open(mode, encoding=encoding) as fp:
            fp.write(content)
        tmp.replace(target)
        return target
    except OSError as exc:  # pragma: no cover - exercised via tests
        raise CodeAgentError(f"Failed to write file {target!s}: {exc}") from exc


def create_from_template(
    template_root_dir: Path,
    dest_root_dir: Path,
    *,
    replace_vars: dict | None = None,
) -> Path:
    """Create *dest_path* by copying *template_path*.

    ``replace_vars`` may contain placeholder keys that will be replaced
    in the template text using :meth:`str.format`.  The function
    returns the absolute :class:`Path` to the created file.

    :param template_path: Path to the template file.
    :param dest_path: Destination file path.
    :param replace_vars: Optional dict of placeholders to replace.
    :return: The absolute path of the created file.
    """
    template_path = Path(template_root_dir).expanduser().resolve()
    dest_path = Path(dest_root_dir).expanduser().resolve()
    if not template_path.is_file():
        raise CodeAgentError(f"Template file {template_path!s} does not exist")
    try:
        text = template_path.read_text(encoding="utf-8")
        if replace_vars:
            text = text.format(**replace_vars)
        return write_file(dest_path, text)
    except Exception as exc:  # pragma: no cover - exercised via tests
        raise CodeAgentError(
            f"Failed to create {dest_path!s} from template {template_path!s}: {exc}"
        ) from exc


def _generate_ipynb_from_cells(
    cells: Iterable[str],
) -> (
    dict[
        str,
        list[dict[str, str | dict[Any, Any] | list[Any] | None]]
        | dict[str, dict[str, str]]
        | int,
    ]
    | str
):
    """Return a minimal Jupyter notebook dict for the given *cells*.

    The function is intentionally minimal - it creates a single
    code cell per element in ``cells``.  If :mod:`nbformat` is
    available, the notebook is created using the public API; otherwise a
    hand-crafted minimal structure is returned.

    :param cells: Iterable of cell contents.
    :return: Minimal Jupyter notebook dict.
    """
    if nbformat is None:
        # Hand-crafted minimal notebook - sufficient for the tests.
        return {
            "cells": [
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": cell,
                }
                for cell in cells
            ],
            "metadata": {
                "kernelspec": {
                    "display_name": "python",
                    "language": "python",
                    "name": "python",
                }
            },
            "nbformat": 4,
            "nbformat_minor": 2,
        }
    # When nbformat is available we can use the public API.
    nb = nbformat.v4.new_notebook()
    for cell in cells:
        nb.cells.append(nbformat.v4.new_code_cell(cell))
    return nbformat.writes(nb)


def py_to_ipynb(py_file: Path, output: Path | None = None) -> Path:
    """Convert a Python script to a minimal Jupyter notebook.

    The function searches the script for ``# %%`` markers - any text
    following a marker until the next marker (or the file end) becomes a
    separate cell.  If no markers are found, the entire file becomes a
    single cell.

    :param py_file: Path to the input Python file.
    :param output: Destination notebook path.  If omitted, ``py_file`` is
        rewritten with a ``.ipynb`` extension.
    :return: Absolute path to the generated notebook.
    """
    py_file = Path(py_file).expanduser().resolve()
    if not py_file.is_file():
        raise CodeAgentError(f"Python file {py_file!s} does not exist")
    content = py_file.read_text(encoding="utf-8")
    cells: list[str] = []
    current: list[str] = []
    for line in content.splitlines(keepends=True):
        if line.lstrip().startswith("# %%"):
            if current:
                cells.append("".join(current))
                current = []
            continue  # skip the marker line
        current.append(line)
    if current:
        cells.append("".join(current))
    if not cells:  # empty file - create a single empty cell
        cells = ["\n"]
    nb_dict = _generate_ipynb_from_cells(cells)
    if output is None:
        output = py_file.with_suffix(".ipynb")
    else:
        output = Path(output).expanduser().resolve()
    try:
        if isinstance(nb_dict, str):
            # nbformat returned a string when used.
            write_file(output, nb_dict)
        else:
            # hand-crafted dict.
            json_text = json.dumps(nb_dict, indent=2)
            write_file(output, json_text)
        return output
    except Exception as exc:  # pragma: no cover - exercised via tests
        raise CodeAgentError(
            f"Failed to write notebook {output!s}: {exc}"
        ) from exc


def create_file(
    path: Path | str,
    content: str,
    *,
    overwrite: bool = False,
) -> Path:
    """Create *path* and write *content*.

    This is a convenience wrapper around :func:`write_file` that adds an
    overwrite guard: by default an existing file raises
    :class:`CodeAgentError` unless ``overwrite=True`` is passed.

    :param path: Target file path.
    :param content: Text to write.
    :param overwrite: If ``False`` (the default) an existing file will raise
        a :class:`CodeAgentError`.
    :return: Absolute path of the created file.
    """
    path = Path(path).expanduser().resolve()
    if path.exists() and not overwrite:
        raise CodeAgentError(
            f"File {path!s} already exists - use overwrite=True to replace it"
        )
    return write_file(path, content)


def append_file(path: Path | str, content: str) -> Path:
    """Append *content* to *path*.

    The function opens the file in append mode, writes the content and
    returns the absolute file path.  The file must already exist.

    :param path: Target file path.
    :param content: Text to append.
    :return: Absolute path of the modified file.
    """
    path = Path(path).expanduser().resolve()
    if not path.exists():
        raise CodeAgentError(f"File {path!s} does not exist - cannot append")
    with path.open("a", encoding="utf-8") as fp:
        fp.write(content)
    return path
