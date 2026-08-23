"""LangGraph Protocol v2 event translation for the web UI.

This module translates LangGraph ``astream_events`` v2 output into the
Protocol v2 event envelopes that ``@langchain/react`` ``useStream`` expects:

* ``seq`` — monotonically increasing sequence number
* ``method`` — one of ``values``, ``messages``, ``tools``, ``lifecycle``,
  ``input``, ``custom``, ``updates``, ``tasks``, ``checkpoints``.
* ``params`` — ``{namespace, node?, data}``.

The root subscription (``namespace == []``) is what ``useStream`` reads for
its always-on projections (``stream.values``, ``stream.messages``,
``stream.toolCalls``, ``stream.interrupts``).  Subgraph events carry a
non-empty namespace and are forwarded unchanged so selector hooks such as
``useMessages(stream, subagent)`` can scope into them.
"""

from __future__ import annotations

import json
import uuid

from collections.abc import AsyncGenerator
from datetime import date, datetime
from pathlib import Path
from typing import Any


# --- SUBAGENT STATE TRACKING ---
# Track subagents that have started to emit start/end events
_seen_subagents: set[str] = set()


def _sse(payload: dict[str, Any], seq: int | None = None) -> str:
    """Format a single SSE frame with id and event fields."""
    lines = []
    if seq is not None:
        lines.append(f"id: {seq}")
    lines.append("event: message")
    lines.append(f"data: {json.dumps(payload, default=_json_default)}")
    lines.append("")  # blank line terminates the frame
    return "\n".join(lines) + "\n"


def _json_default(obj: Any) -> Any:
    """Handle non-serializable objects in protocol events."""
    # Common standard-library types that are not JSON-native
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, bytes):
        try:
            return obj.decode()
        except Exception:
            return str(obj)
    if isinstance(obj, set):
        return list(obj)
    # LangChain message types
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict") and callable(obj.dict):
        return obj.dict()
    if hasattr(obj, "__dict__") and not isinstance(obj, type):
        return obj.__dict__
    # Final safe fallback: never raise, just stringify
    try:
        return str(obj)
    except Exception:
        return f"<{type(obj).__name__} object>"


# ---------------------------------------------------------------------------
# Event translators
# ---------------------------------------------------------------------------


def _translate_on_chat_model_stream(
    event: dict[str, Any],
    ns: list[str],
    node: str | None,
) -> dict[str, Any] | None:
    """Translate ``on_chat_model_stream`` → ``messages`` channel events."""
    data = event.get("data", {})
    chunk = data.get("chunk")
    if chunk is None:
        return None

    content = getattr(chunk, "content", None)
    if content is None:
        content = chunk.get("content") if isinstance(chunk, dict) else None

    if not content:
        return None

    delta: dict[str, Any] = {"type": "text-delta", "text": content}

    return {
        "seq": 0,
        "method": "messages",
        "params": {
            "namespace": ns,
            "node": node,
            "data": {
                "event": "content-block-delta",
                "index": 0,
                "delta": delta,
            },
        },
    }


def _translate_on_llm_start(
    event: dict[str, Any],
    ns: list[str],
    node: str | None,
    message_id: str,
) -> dict[str, Any]:
    """Translate ``on_llm_start`` → ``message-start``."""
    return {
        "seq": 0,
        "method": "messages",
        "params": {
            "namespace": ns,
            "node": node,
            "data": {
                "event": "message-start",
                "id": message_id,
                "role": "ai",
            },
        },
    }


def _translate_on_llm_end(
    event: dict[str, Any],
    ns: list[str],
    node: str | None,
    message_id: str,
) -> dict[str, Any]:
    """Translate ``on_llm_end`` → ``message-finish``."""
    data = event.get("data", {})
    output = data.get("output")
    usage = getattr(output, "usage_metadata", None) if output else None
    response_metadata = (
        getattr(output, "response_metadata", None) if output else None
    )

    result: dict[str, Any] = {
        "seq": 0,
        "method": "messages",
        "params": {
            "namespace": ns,
            "node": node,
            "data": {
                "event": "message-finish",
                "id": message_id,
            },
        },
    }
    if usage:
        result["params"]["data"]["usage"] = usage
    if response_metadata:
        result["params"]["data"]["responseMetadata"] = response_metadata
    return result


def _translate_on_tool_start(
    event: dict[str, Any],
    ns: list[str],
    node: str | None,
) -> dict[str, Any]:
    """Translate ``on_tool_start`` → ``tools`` channel ``tool-started``."""
    data = event.get("data", {})
    tool_name = event.get("name", "")
    tool_input = data.get("input", {})
    run_id = event.get("run_id", "")
    tool_call_id = f"{run_id}-{tool_name}"

    return {
        "seq": 0,
        "method": "tools",
        "params": {
            "namespace": ns,
            "node": node,
            "data": {
                "event": "tool-started",
                "toolCallId": tool_call_id,
                "name": tool_name,
                "input": tool_input,
                "state": "starting",
            },
        },
    }


def _translate_on_tool_end(
    event: dict[str, Any],
    ns: list[str],
    node: str | None,
) -> dict[str, Any]:
    """Translate ``on_tool_end`` → ``tools`` channel ``tool-finished``."""
    data = event.get("data", {})
    tool_name = event.get("name", "")
    run_id = event.get("run_id", "")
    tool_call_id = f"{run_id}-{tool_name}"
    output = data.get("output", "")

    return {
        "seq": 0,
        "method": "tools",
        "params": {
            "namespace": ns,
            "node": node,
            "data": {
                "event": "tool-finished",
                "toolCallId": tool_call_id,
                "name": tool_name,
                "output": str(output)[:2000],
                "state": "completed",
            },
        },
    }


def _translate_on_tool_error(
    event: dict[str, Any],
    ns: list[str],
    node: str | None,
) -> dict[str, Any]:
    """Translate ``on_tool_error`` → ``tools`` channel ``tool-error``."""
    data = event.get("data", {})
    tool_name = event.get("name", "")
    run_id = event.get("run_id", "")
    tool_call_id = f"{run_id}-{tool_name}"
    error = data.get("error", str(data.get("output", "")))

    return {
        "seq": 0,
        "method": "tools",
        "params": {
            "namespace": ns,
            "node": node,
            "data": {
                "event": "tool-error",
                "toolCallId": tool_call_id,
                "name": tool_name,
                "error": str(error)[:2000],
                "state": "error",
            },
        },
    }


def _translate_on_chain_start(
    event: dict[str, Any],
    ns: list[str],
    node: str | None,
) -> dict[str, Any]:
    """Translate ``on_chain_start`` → ``lifecycle`` channel ``started``."""
    name = event.get("name", node or "")
    return {
        "seq": 0,
        "method": "lifecycle",
        "params": {
            "namespace": ns,
            "node": node,
            "data": {
                "event": "started",
                "graph_name": name,
            },
        },
    }


def _translate_on_chain_end(
    event: dict[str, Any],
    ns: list[str],
    node: str | None,
    is_error: bool = False,
) -> dict[str, Any]:
    """Translate ``on_chain_end`` → ``lifecycle`` channel ``completed``/``failed``."""
    name = event.get("name", node or "")
    status = "failed" if is_error else "completed"
    result: dict[str, Any] = {
        "seq": 0,
        "method": "lifecycle",
        "params": {
            "namespace": ns,
            "node": node,
            "data": {
                "event": status,
                "graph_name": name,
            },
        },
    }
    if is_error:
        data = event.get("data", {})
        result["params"]["data"]["error"] = str(data.get("error", ""))
    return result


def _translate_interrupt(
    event: dict[str, Any],
    ns: list[str],
    node: str | None,
) -> dict[str, Any]:
    """Translate an interrupt → ``input`` channel ``input-requested``."""
    data = event.get("data", {})
    output = data.get("output", {})

    # Unwrap LangGraph's interrupt wrapper when present
    if isinstance(output, dict):
        output = output.get("__interrupt__", output)

    interrupt_id = str(uuid.uuid4())

    return {
        "seq": 0,
        "method": "input",
        "params": {
            "namespace": ns,
            "node": node,
            "data": {
                "event": "input-requested",
                "id": interrupt_id,
                "value": output,
            },
        },
    }


def _translate_values(
    event: dict[str, Any],
    ns: list[str],
    node: str | None,
) -> dict[str, Any] | None:
    """Translate state values → ``values`` channel."""
    data = event.get("data", {})
    output = data.get("output", {})

    if not isinstance(output, dict):
        return None

    return {
        "seq": 0,
        "method": "values",
        "params": {
            "namespace": ns,
            "node": node,
            "data": output,
        },
    }


# ---------------------------------------------------------------------------
# Main stream translator
# ---------------------------------------------------------------------------


async def translate_stream(
    agent: Any,
    message: str,
    thread_id: str,
) -> AsyncGenerator[dict[str, Any]]:
    """Drive ``agent.astream_events`` and yield protocol v2 event dicts.

    This is the core translation layer.  It consumes LangGraph v2 events,
    maps them to protocol v2 ``method/params`` envelopes, and yields the
    event dicts.  The caller is responsible for SSE framing.

    :param agent: Compiled LangGraph agent (from ``build_agent()``).
    :param message: User message text.
    :param thread_id: Conversation thread identifier.
    :yields: Protocol v2 event dicts.
    """
    seq = 0
    active_namespaces: dict[str, set[str]] = {}

    def next_seq() -> int:
        nonlocal seq
        seq += 1
        return seq

    stream_fn = getattr(agent, "astream_events", None)
    if stream_fn is None:
        yield {
            "seq": next_seq(),
            "method": "lifecycle",
            "params": {
                "namespace": [],
                "data": {"event": "failed", "error": "Streaming not supported"},
            },
        }
        return

    # Track active message IDs per (namespace, node)
    active_messages: dict[str, str] = {}

    try:
        yield {
            "seq": next_seq(),
            "method": "lifecycle",
            "params": {
                "namespace": [],
                "data": {"event": "started"},
            },
        }

        async for event in stream_fn(
            {"messages": [{"role": "user", "content": message}]},
            config={
                "configurable": {"thread_id": thread_id},
                "recursion_limit": 150,
            },
            version="v2",
        ):
            etype = event.get("event", "")
            data = event.get("data", {})
            event_name = event.get("name", "")
            run_id = event.get("run_id", "")
            tags = event.get("tags", [])
            namespace: list[str] = []

            # Derive namespace from tags
            for tag in tags:
                if isinstance(tag, str) and tag.startswith("__subgraph__:"):
                    namespace = tag.split(":", 1)[1].split(":")
                    break

            node = event_name if event_name else None

            if etype == "on_chat_model_start":
                msg_id = f"{run_id}-{event_name}"
                ns_key = f"{':'.join(namespace)}::{event_name}"
                active_messages[ns_key] = msg_id
                frame = _translate_on_llm_start(event, namespace, node, msg_id)
                frame["seq"] = next_seq()
                yield frame

            elif etype == "on_chat_model_stream":
                ns_key = f"{':'.join(namespace)}::{event_name}"
                if ns_key not in active_messages:
                    msg_id = f"{run_id}-{event_name}"
                    active_messages[ns_key] = msg_id
                    frame = _translate_on_llm_start(
                        event, namespace, node, msg_id
                    )
                    frame["seq"] = next_seq()
                    yield frame

                frame = _translate_on_chat_model_stream(event, namespace, node)
                if frame:
                    frame["seq"] = next_seq()
                    yield frame

            elif etype == "on_chat_model_end":
                ns_key = f"{':'.join(namespace)}::{event_name}"
                msg_id = active_messages.pop(ns_key, f"{run_id}-{event_name}")
                frame = _translate_on_llm_end(event, namespace, node, msg_id)
                frame["seq"] = next_seq()
                yield frame

            elif etype == "on_tool_start":
                frame = _translate_on_tool_start(event, namespace, node)
                frame["seq"] = next_seq()
                yield frame

            elif etype == "on_tool_end":
                frame = _translate_on_tool_end(event, namespace, node)
                frame["seq"] = next_seq()
                yield frame

            elif etype == "on_tool_error":
                frame = _translate_on_tool_error(event, namespace, node)
                frame["seq"] = next_seq()
                yield frame

            elif etype == "on_chain_start":
                frame = _translate_on_chain_start(event, namespace, node)
                frame["seq"] = next_seq()
                yield frame

            elif etype == "on_chain_end":
                output = data.get("output", {})
                is_error = bool(
                    isinstance(output, dict) and output.get("error")
                )
                frame = _translate_on_chain_end(
                    event, namespace, node, is_error=is_error
                )
                frame["seq"] = next_seq()
                yield frame

                # Emit subagent lifecycle events based on namespace
                if namespace:
                    active_namespaces.setdefault(run_id, set()).add(
                        ":".join(namespace)
                    )
                    # Check if any subgraph namespace just completed
                    finished = active_namespaces.get(run_id, set())
                    for ns in finished:
                        yield {
                            "seq": next_seq(),
                            "method": "lifecycle",
                            "params": {
                                "namespace": ns.split(":") if ":" in ns else [],
                                "data": {
                                    "event": "subagent_end",
                                    "name": ns[-1] if ns else "unknown",
                                },
                            },
                        }
                    # Emit subagent_start for any new subgraph that just started
                    # (this would have been emitted on on_agent_step_start if needed)

                # Extract and emit todos from chain end output
                if isinstance(output, dict) and output.get("todos"):
                    todos = output["todos"]
                    yield {
                        "seq": next_seq(),
                        "method": "todos",
                        "params": {
                            "namespace": namespace,
                            "data": {"todos": todos},
                        },
                    }

                if isinstance(output, dict) and output.get("__interrupt__"):
                    frame = _translate_interrupt(event, namespace, node)
                    frame["seq"] = next_seq()
                    yield frame

                frame = _translate_values(event, namespace, node)
                if frame:
                    frame["seq"] = next_seq()
                    yield frame

            elif etype == "on_chain_error":
                frame = _translate_on_chain_end(
                    event, namespace, node, is_error=True
                )
                frame["seq"] = next_seq()
                yield frame

            elif etype == "on_agent_step_end":
                frame = _translate_values(event, namespace, node)
                if frame:
                    frame["seq"] = next_seq()
                    yield frame

        yield {
            "seq": next_seq(),
            "method": "lifecycle",
            "params": {
                "namespace": [],
                "data": {"event": "completed"},
            },
        }

    except Exception as exc:
        yield {
            "seq": next_seq(),
            "method": "lifecycle",
            "params": {
                "namespace": [],
                "data": {
                    "event": "failed",
                    "error": str(exc),
                },
            },
        }
