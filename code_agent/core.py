"""Core helper functions for the *code_agent* package.

This module provides a very small public API that is used by the
command‑line interface, the agent runtime and the test‑suite.  All
functions are intentionally pure – they do not depend on any global
state – which makes them straightforward to unit‑test.

The helpers are thin wrappers around :mod:`code_agent.file_generator`.
They expose a slightly more user‑friendly name and a few convenience
arguments such as ``overwrite``.
"""

from __future__ import annotations

from pathlib import Path

from .exceptions import CodeAgentError
from .file_generator import create_from_template as _create_from_template
from .file_generator import (py_to_ipynb, write_file, )
from .scaffold import create_project_scaffold  # Re-export for public API

__all__ = ["write_file", "create_file", "append_file", "create_from_template", "py_to_ipynb", "create_project_scaffold",
        "CodeAgentError", ]


def create_file(
        path: Path | str, content: str, *, overwrite: bool = False
        ) -> Path:
    """Create *path* and write *content*.

    Parameters
    ----------
    path:
        Target file path.
    content:
        Text to write.
    overwrite:
        If ``False`` (the default) an existing file will raise a
        :class:`CodeAgentError`.
    Returns
    -------
    Path
        Absolute path of the created file.
    """

    path = Path(path).expanduser().resolve()
    if path.exists() and not overwrite:
        raise CodeAgentError(
                f"File {path!s} already exists – use overwrite=True to replace it"
                )
    return write_file(path, content)


def append_file(path: Path | str, content: str) -> Path:
    """Append *content* to *path*.

    The function opens the file in append mode, writes the content and
    returns the absolute file path.
    """

    path = Path(path).expanduser().resolve()
    if not path.exists():
        raise CodeAgentError(f"File {path!s} does not exist – cannot append")
    with path.open("a", encoding = "utf-8") as fp:
        fp.write(content)
    return path


def create_from_template(
        template_path: Path | str, dest_path: Path | str, *, replace_vars: dict | None = None, ) -> Path:
    """Create a file by copying *template_path* to *dest_path*.

    Any ``{}`` placeholders in the template are replaced by
    ``replace_vars`` using :meth:`str.format`.
    """

    return _create_from_template(
            template_path, dest_path, replace_vars = replace_vars
            )
