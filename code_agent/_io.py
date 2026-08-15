"""Low-level, synchronous file-system helpers used by the *code_agent* package.

This module is the private home of the package's atomic file-write helper.
It was extracted from the legacy :mod:`code_agent.file_generator` module
(which is being removed) so that consumers (CLI, tools, documentation
generator, tests) share a single implementation.

All functions are stateless, return a :class:`pathlib.Path` instance
pointing to the created file, and raise ``CodeAgentError`` (defined in
:mod:`code_agent.exceptions`) on failure.
"""

from __future__ import annotations

from pathlib import Path

from .exceptions import CodeAgentError

__all__ = ["_atomic_write"]


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
