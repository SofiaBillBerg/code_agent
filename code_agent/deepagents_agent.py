"""DeepAgents (LangGraph) based agent construction.

This module builds on :func:`deepagents.create_deep_agent` and centralizes
the project-specific wiring that a plain ``create_agent`` call does not
cover:

* the working directory is mounted at ``/workspace/`` through a
  :class:`~deepagents.backends.composite.CompositeBackend` - the project
  lives on real disk (``FilesystemBackend`` with ``virtual_mode=True`` for
  path sandboxing) while agent-internal artifacts (offloaded tool results
  under ``/large_tool_results/`` and conversation history under
  ``/conversation_history/``) stay in an ephemeral
  :class:`~deepagents.backends.state.StateBackend` instead of polluting the
  user's project,
* path permissions (``FilesystemPermission`` glob rules) with
  ``mode="interrupt"`` pause the built-in filesystem tools for
  human-in-the-loop review,
* ``interrupt_on`` gates the mutating built-in tools (``edit_file``,
  ``write_file``, ``delete``, ``execute``) and any custom tools the caller
  marks for review,
* an :class:`langgraph.checkpoint.memory.InMemorySaver` checkpointing is
  attached automatically (mandatory for HITL pauses to work),
* optional *harness profiles* (registered under ``provider:model`` keys) can
  tune the system prompt, tool descriptions and excluded tools per model.

The built-in filesystem tool set provided by ``create_deep_agent`` is
``ls, read_file, write_file, edit_file, glob, grep, delete, execute, task``.
Passing custom tools is *additive* - built-ins are only removed through a
profile's ``excluded_tools``.  This module therefore drops custom tools whose
names collide with the built-ins (the built-ins are the ones wired to the
backend/permissions, so they win), avoiding duplicate-tool errors.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import logging
from pathlib import Path
from typing import Any

from deepagents import (
    FilesystemPermission,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends import CompositeBackend, StateBackend
from deepagents.backends.filesystem import FilesystemBackend
from langchain.agents.middleware.human_in_the_loop import InterruptOnConfig
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore

log = logging.getLogger(__name__)

__all__ = [
    "FS_BUILTIN_TOOLS",
    "build_deep_agent",
    "make_backend",
    "make_default_permissions",
    "register_harness_profile",
]

#: Tools provided out of the box by ``create_deep_agent``.
FS_BUILTIN_TOOLS: frozenset[str] = frozenset({
    "ls",
    "read_file",
    "write_file",
    "edit_file",
    "glob",
    "grep",
    "delete",
    "execute",
    "task",
})

#: Built-in tools that modify state and therefore default to HITL review.
DEFAULT_INTERRUPT_ON: dict[str, bool] = {
    "edit_file": True,
    "write_file": True,
    "delete": True,
    "execute": True,
}

#: Route prefix under which the real working directory is mounted.
DEFAULT_WORKSPACE_PREFIX = "/workspace/"


def make_backend(
    root_dir: str | Path,
    *,
    workspace_prefix: str = DEFAULT_WORKSPACE_PREFIX,
    virtual_mode: bool = True,
) -> CompositeBackend:
    """Build the :class:`CompositeBackend` used by the deep agent.

    Routes ``<workspace_prefix>`` to a real-disk :class:`FilesystemBackend`
    rooted at *root_dir* (``virtual_mode=True`` sandboxes paths: ``..``,
    ``~`` and absolute paths outside the root are blocked).  Everything else
    - the agent's internal files - stays in an ephemeral :class:`StateBackend`
    so offloaded tool results and conversation history never touch the user's
    project.

    :param root_dir: Directory the agent may read/write on real disk.
    :param workspace_prefix: Virtual mount point for *root_dir* (must start
        and end with ``/``).
    :param virtual_mode: Sandbox paths under *root_dir* (recommended; the
        non-virtual mode provides no path security at all).

    :return: A configured :class:`CompositeBackend`.
    """
    fs_backend = FilesystemBackend(
        root_dir=str(Path(root_dir).expanduser().resolve()),
        virtual_mode=virtual_mode,
    )
    return CompositeBackend(StateBackend(), {workspace_prefix: fs_backend})


def make_default_permissions(
    *,
    workspace_prefix: str = DEFAULT_WORKSPACE_PREFIX,
) -> list[FilesystemPermission]:
    """Return sensible default filesystem permission rules.

    Rules are evaluated in order, first match wins, and any path that matches
    no rule is *allowed* - so the deny rules must come before the allow-all.

    * reads under the workspace are allowed,
    * writes under the workspace raise an HITL interrupt (``mode="interrupt"``
      pauses the built-in ``write_file``/``edit_file`` tools for review),
    * ``.env`` and ``secrets/`` are denied outright (defense in depth on top
      of ``virtual_mode``).

    All patterns are glob rules (``**`` crosses directories) matched against
    the validated route-prefixed path, e.g. ``/workspace/foo/bar.py``.

    :param workspace_prefix: Route prefix of the real working directory.

    :return: Ordered list of :class:`FilesystemPermission` rules.
    """
    wp = workspace_prefix.rstrip("/")  # e.g. "/workspace"
    return [
        # Deny sensitive paths first (first-match-wins semantics).
        FilesystemPermission(
            operations=["read", "write"],
            paths=[f"{wp}/.env", f"{wp}/**/.env", f"{wp}/secrets/**"],
            mode="deny",
        ),
        # Reads: allowed anywhere under the workspace.
        FilesystemPermission(
            operations=["read"],
            paths=[f"{wp}/**"],
            mode="allow",
        ),
        # Writes: paused for human review.
        FilesystemPermission(
            operations=["write"],
            paths=[f"{wp}/**"],
            mode="interrupt",
        ),
    ]


def build_deep_agent(
    llm: BaseChatModel,
    tools: Sequence[BaseTool] | None = None,
    *,
    root_dir: str | Path = ".",
    system_prompt: str | SystemMessage | None = None,
    permissions: Sequence[FilesystemPermission] | None = None,
    interrupt_on: Mapping[str, bool | InterruptOnConfig] | None = None,
    checkpointer: Any | None = None,
    store: BaseStore | None = None,
    name: str | None = None,
    workspace_prefix: str = DEFAULT_WORKSPACE_PREFIX,
    drop_builtin_collisions: bool = True,
    profile: HarnessProfile | None = None,
    profile_key: str | None = None,
    **kwargs: Any,
) -> CompiledStateGraph:
    """Create a DeepAgents agent wired for this project.

    The returned graph exposes the built-in filesystem tools plus any custom
    *tools* that do not collide with those built-ins.  All mutating built-ins
    default to HITL review (see :data:`DEFAULT_INTERRUPT_ON`); merge
    additional tool names into *interrupt_on* (``True`` or a dict with
    ``allowed_decisions``) to review custom tools as well.

    A checkpointer is mandatory for HITL; when none is given an
    :class:`InMemorySaver` is created (per-thread, in-memory).

    :param llm: Chat model backing the agent.
    :param tools: Custom tools to add on top of the built-in filesystem set.
        Tools whose ``name`` collides with a built-in are dropped unless
        *drop_builtin_collisions* is false.
    :param root_dir: Real working directory mounted at *workspace_prefix*.
    :param system_prompt: Base system prompt for the agent.
    :param permissions: Filesystem permission rules; defaults to
        :func:`make_default_permissions`.
    :param interrupt_on: Tool-name -> HITL config.  Defaults to
        :data:`DEFAULT_INTERRUPT_ON` (mutating built-ins).
    :param checkpointer: LangGraph checkpointer; an :class:`InMemorySaver` is
        created when omitted.
    :param store: Optional LangGraph store (cross-thread memory).
    :param name: Optional graph name (useful for tracing).
    :param workspace_prefix: Virtual mount point for *root_dir*.
    :param drop_builtin_collisions: Drop custom tools whose names match
        built-in tools (built-ins are wired to the backend and win).
    :param profile: Optional harness profile to register under *profile_key*.
    :param profile_key: Key of the form ``provider:model`` (e.g.
        ``"ollama:gpt-oss:20b"``) under which *profile* is registered.
    :param kwargs: Extra keyword arguments forwarded to
        :func:`deepagents.create_deep_agent` (e.g. ``middleware``,
        ``subagents``, ``memory``, ``response_format``, ``debug``).

    :return: A compiled LangGraph state graph ready to ``invoke``.
    """
    backend = make_backend(root_dir, workspace_prefix=workspace_prefix)

    # Custom tools are additive; drop any that shadow the built-ins.
    tool_list = list(tools) if tools is not None else []
    if drop_builtin_collisions and tool_list:
        original_names = {t.name for t in tool_list}
        tool_list = [t for t in tool_list if t.name not in FS_BUILTIN_TOOLS]
        dropped = original_names - {t.name for t in tool_list}
        if dropped:
            log.info(
                "Dropped custom tools shadowing built-ins: %s", sorted(dropped)
            )

    # HITL: default to reviewing every mutating built-in tool.
    merged_interrupt_on: dict[str, bool | InterruptOnConfig] = dict(
        DEFAULT_INTERRUPT_ON
    )
    if interrupt_on:
        merged_interrupt_on.update(interrupt_on)

    # A checkpointer is required for HITL pauses to be resumable.
    if checkpointer is None:
        checkpointer = InMemorySaver()

    if profile is not None:
        if not profile_key:
            raise ValueError(
                "profile_key (e.g. 'ollama:gpt-oss:20b') is required when a profile is given"
            )
        register_harness_profile(profile_key, profile)
        log.info("Registered harness profile under '%s'", profile_key)

    return create_deep_agent(
        model=llm,
        tools=tool_list or None,
        system_prompt=system_prompt,
        backend=backend,
        permissions=(
            list(permissions)
            if permissions is not None
            else make_default_permissions(workspace_prefix=workspace_prefix)
        ),
        interrupt_on=merged_interrupt_on,
        checkpointer=checkpointer,
        store=store,
        name=name,
        **kwargs,
    )
