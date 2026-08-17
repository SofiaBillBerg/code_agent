"""LangGraph checkpointer factory.

This module provides a single factory function, :func:`build_checkpointer`,
that returns a configured checkpointer for persistent LangGraph state.

The checkpointer resolves the storage path from settings, creates the
directory if needed, and instantiates a :class:`SqliteSaver`.  If the
SQLite database cannot be created or accessed (permissions error,
read-only filesystem, invalid path), the module logs a WARNING and
returns an :class:`InMemorySaver` so the agent remains operational.

Dependencies:
    langgraph_checkpoint_sqlite: SqliteSaver for persistent storage.
    langgraph.checkpoint.memory: InMemorySaver as fallback.

Environment:
    CODE_AGENT_CHECKPOINT_DIR: Directory where agent_state.db is stored.

.. note::
    All functions are fully annotated with PEP 257 docstrings. Every
    non-trivial line carries a comment explaining its purpose.
"""

from __future__ import (
    annotations,  # : Enable future annotations for type hints.
)

import logging  # : Standard logging module for WARNING-level entries.
import sqlite3  # : Standard sqlite3 for opening the checkpoint connection.

from pathlib import Path  # : Pathlib for filesystem path handling.

#: Import the LangGraph checkpointer classes needed for persistence.
#: SqliteSaver provides persistent storage in an SQLite database.
#: InMemorySaver serves as a fallback when SQLite is unavailable.
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import (
    SqliteSaver,  # ruff: ignore [undefined-name] -- F821 is intentional here.
)


#: Module-level logger instance for consistent WARNING-level logging.
logger = logging.getLogger(__name__)

#: Default directory for checkpoint storage when CODE_AGENT_CHECKPOINT_DIR is unset.
DEFAULT_CHECKPOINT_DIR = "~/.code_agent/checkpoints/"

#: Filename appended to checkpoint_dir to form the full SQLite database path.
CHECKPOINT_FILENAME = "agent.db"


def build_checkpointer(
    checkpoint_dir: str | None = None,
) -> InMemorySaver | SqliteSaver:
    """Return a persistent checkpointer for LangGraph state.

    The checkpointer resolves the storage path from the *checkpoint_dir*
    argument, the environment variable ``CODE_AGENT_CHECKPOINT_DIR``, or
    the hard-coded default. It creates the directory if needed and
    instantiates a :class:`SqliteSaver`. If the directory cannot be
    accessed or the SQLite database fails to initialize, a WARNING is
    logged and an :class:`InMemorySaver` is returned instead.

    Resolution order for the checkpoint directory:

    1. The *checkpoint_dir* argument (if not ``None``).
    2. The ``CODE_AGENT_CHECKPOINT_DIR`` environment variable via
       :func:`~code_agent.config.settings.get_settings`.
    3. The hard-coded default ``~/.code_agent/checkpoints/``.

    All three paths are expanded (``~`` → home directory) and resolved
    to an absolute :class:`pathlib.Path`.

    :param checkpoint_dir: Optional override for the storage directory.
        If ``None``, the value is read from settings or the default.
    :returns: A configured :class:`SqliteSaver` or fallback
        :class:`InMemorySaver`.
    """
    #: Resolve the checkpoint directory from the argument, settings, or default.
    resolved_dir = _resolve_checkpoint_dir(checkpoint_dir)

    try:
        #: Ensure the directory exists (creates parent directories if needed).
        resolved_dir.mkdir(parents=True, exist_ok=True)

        #: Construct the full SQLite database path by appending the filename.
        db_path = resolved_dir / CHECKPOINT_FILENAME

        #: Open a dedicated SQLite connection for the checkpoint database.
        #: check_same_thread=False is safe: the saver uses an internal lock.
        conn = sqlite3.connect(str(db_path), check_same_thread=False)

        #: Create and return the SqliteSaver bound to the open connection.
        return SqliteSaver(conn)

    except OSError as exc:
        #: Log the error and fall back to InMemorySaver for graceful degradation.
        #: OSError covers permission errors, read-only filesystems, etc.
        logger.warning(
            "SqliteSaver unavailable at %s (%s); falling back to InMemorySaver.",
            resolved_dir,
            exc,
        )
        return InMemorySaver()

    except Exception as exc:
        #: Catch any other unexpected exception to ensure the agent remains
        #: operational even with unforeseen errors (e.g., SQLite library issues).
        logger.warning(
            "Unexpected error creating SqliteSaver at %s (%s); falling back to InMemorySaver.",
            resolved_dir,
            exc,
        )
        return InMemorySaver()


def _resolve_checkpoint_dir(override: str | None) -> Path:
    """Resolve the checkpoint directory from override, settings, or default.

    This internal helper implements the resolution order for the checkpoint
    directory. It is called by :func:`build_checkpointer` to obtain the
    absolute :class:`Path` before attempting directory creation.

    Resolution order:

    1. If *override* is not ``None``, use it directly (expand ``~`` and resolve).
    2. If *override* is ``None``, read ``settings.checkpoint_dir`` via
       :func:`~code_agent.config.settings.get_settings`.
    3. If both *override* and settings fail, use the hard-coded default.

    :param override: Caller-supplied directory path, or ``None`` to use
        settings or the default.
    :returns: An absolute :class:`Path` for the checkpoint directory.
    """
    #: If the caller provided an explicit override, expand ~ and resolve to absolute.
    if override is not None:
        return Path(override).expanduser().resolve()

    #: Attempt to read checkpoint_dir from settings (may raise if settings fail).
    try:
        from code_agent.config.settings import get_settings

        checkpoint_dir = get_settings().checkpoint_dir
        return Path(checkpoint_dir).expanduser().resolve()

    except Exception:
        #: If settings cannot be loaded (e.g., missing .env, Pydantic error),
        #: fall back to the hard-coded default path.
        return Path(DEFAULT_CHECKPOINT_DIR).expanduser().resolve()
