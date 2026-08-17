"""Low-level, synchronous file-system helpers used by the *code_agent* package.

This module is the private home of the package's atomic file-write helper
and the small set of pure, stateless file helpers the agent uses to create,
append, template and convert files.  It was extracted from the legacy
:mod:`code_agent.file_generator` module (which has been removed) so that
consumers (CLI, tools, documentation generator, tests) share a single
implementation.

All functions are stateless, return a :class:`pathlib.Path` instance
pointing to the created file, and raise ``CodeAgentError`` (defined in
:mod:`code_agent.exceptions`) on failure.
"""

from __future__ import annotations

import json

from collections.abc import Iterable
from pathlib import Path
from types import ModuleType
from typing import Any

from code_agent.exceptions import CodeAgentError


#: Optional Jupyter notebook dependency; ``None`` when unavailable.
nbformat: ModuleType | None
try:  # Optional dependency - used only for the notebook path.
    import nbformat
except Exception:  # pragma: no cover - handled at runtime
    # noinspection PyGlobalVariableRedeclarationInNotebook
    nbformat = None

__all__ = [
    "_atomic_write",
    "append_file",
    "create_file",
    "create_from_template",
]


def _atomic_write(
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
    :raises CodeAgentError: If *target* is a directory or the write fails.
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


def create_file(
    path: Path | str,
    content: str,
    *,
    overwrite: bool = False,
) -> Path:
    """Create *path* and write *content*.

    This is a convenience wrapper around :func:`_atomic_write` that adds an
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
    return _atomic_write(path, content)


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

    :param template_root_dir: Path to the template file.
    :param dest_root_dir: Path to the destination file to create.
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
        return _atomic_write(dest_path, text)
    except Exception as exc:  # pragma: no cover - exercised via tests
        raise CodeAgentError(
            f"Failed to create {dest_path!s} from template {template_path!s}: {exc}"
        ) from exc
