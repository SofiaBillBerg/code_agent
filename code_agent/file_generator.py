"""Low‑level file‑system helpers used by the *code_agent* package.

The goal of this module is to provide **pure, synchronous** helpers that
write text files and convert a simple Python script into a minimal Jupyter
Notebook.  All functions are stateless, return a :class:`pathlib.Path`
instance pointing to the created file, and raise a
``CodeAgentError`` (defined in :mod:`code_agent.exceptions`) on
failure.

The module deliberately avoids external dependencies.  The notebook
generation falls back to a hand‑crafted JSON if :mod:`nbformat` is not
available.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

try:  # Optional dependency – used only for the notebook path.
    import nbformat  # type: ignore
except Exception:  # pragma: no cover – handled at runtime
    nbformat = None

from .exceptions import CodeAgentError

__all__ = ["write_file", "create_from_template", "py_to_ipynb", ]


def write_file(
        target: Path | str, content: str, *, mode: str = "w", encoding: str = "utf-8", ) -> Path:
    """Write *content* to *target* atomically.

    The function creates any missing parent directories, writes the
    content to a temporary file first, and then atomically moves the
    temporary file to ``target``.  This prevents partial writes if the
    process is interrupted.

    Parameters
    ----------
    target:
        Destination file path.
    content:
        Text to write.
    mode:
        File mode – defaults to ``"w"``.
    encoding:
        Text encoding – defaults to ``"utf-8"``.
    Returns
    -------
    Path
        The absolute path of the written file.
    """

    target = Path(target).expanduser().resolve()
    try:
        target.parent.mkdir(parents = True, exist_ok = True)
        tmp = target.with_suffix(".tmp")
        with tmp.open(mode, encoding = encoding) as fp:
            fp.write(content)
        tmp.replace(target)
        return target
    except OSError as exc:  # pragma: no cover – exercised via tests
        raise CodeAgentError(f"Failed to write file {target!s}: {exc}") from exc


def create_from_template(
        template_path: Path | str, dest_path: Path | str, *, replace_vars: dict | None = None, ) -> Path:
    """Create *dest_path* by copying *template_path*.

    ``replace_vars`` may contain placeholder keys that will be replaced
    in the template text using :meth:`str.format`.  The function
    returns the absolute :class:`Path` to the created file.
    """

    template_path = Path(template_path).expanduser().resolve()
    dest_path = Path(dest_path).expanduser().resolve()
    if not template_path.is_file():
        raise CodeAgentError(f"Template file {template_path!s} does not exist")
    try:
        text = template_path.read_text(encoding = "utf-8")
        if replace_vars:
            text = text.format(**replace_vars)
        return write_file(dest_path, text)
    except Exception as exc:  # pragma: no cover – exercised via tests
        raise CodeAgentError(
                f"Failed to create {dest_path!s} from template {template_path!s}: {exc}"
                ) from exc


def _generate_ipynb_from_cells(
        cells: Iterable[str], ) -> (
        dict[str, list[dict[str, str | None | dict[Any, Any] | list[Any]]] | dict[str, dict[str, str]] | int,] | str):
    """Return a minimal Jupyter notebook dict for the given *cells*.

    The function is intentionally minimal – it creates a single
    code cell per element in ``cells``.  If :mod:`nbformat` is
    available, the notebook is created using the public API; otherwise a
    hand‑crafted minimal structure is returned.
    """

    if nbformat is None:
        # Hand‑crafted minimal notebook – sufficient for the tests.
        return {"cells": [
                {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": cell, } for cell
                in cells],
                "metadata": {"kernelspec": {"display_name": "python", "language": "python", "name": "python", }},
                "nbformat": 4, "nbformat_minor": 2, }
    # When nbformat is available we can use the public API.
    nb = nbformat.v4.new_notebook()
    for cell in cells:
        nb.cells.append(nbformat.v4.new_code_cell(cell))
    return nbformat.writes(nb)


def py_to_ipynb(py_file: Path | str, output: Path | str | None = None) -> Path:
    """Convert a Python script to a minimal Jupyter notebook.

    The function searches the script for ``# %%`` markers – any text
    following a marker until the next marker (or the file end) becomes a
    separate cell.  If no markers are found, the entire file becomes a
    single cell.

    Parameters
    ----------
    py_file:
        Path to the input Python file.
    output:
        Destination notebook path.  If omitted, ``py_file`` is
        rewritten with a ``.ipynb`` extension.
    Returns
    -------
    Path
        Absolute path to the generated notebook.
    """

    py_file = Path(py_file).expanduser().resolve()
    if not py_file.is_file():
        raise CodeAgentError(f"Python file {py_file!s} does not exist")
    content = py_file.read_text(encoding = "utf-8")
    cells: list[str] = []
    current: list[str] = []
    for line in content.splitlines(True):
        if line.lstrip().startswith("# %%"):
            if current:
                cells.append("".join(current))
                current = []
            continue  # skip the marker line
        current.append(line)
    if current:
        cells.append("".join(current))
    if not cells:  # empty file – create a single empty cell
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
            # hand‑crafted dict.
            json_text = json.dumps(nb_dict, indent = 2)
            write_file(output, json_text)
        return output
    except Exception as exc:  # pragma: no cover – exercised via tests
        raise CodeAgentError(f"Failed to write notebook {output!s}: {exc}") from exc
