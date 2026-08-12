"""Tests for the CLI chat streaming UX helpers.

Covers:
- streamed event handling in ``_stream_agent_response``
- fallback to blocking ``invoke`` when streaming is unavailable
- tool-start/tool-end logging
- empty-response fallback text
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from code_agent.cli import _stream_agent_response


def _make_stream_agent(events: list[dict[str, object]]) -> MagicMock:
    agent = MagicMock()
    agent.astream_events.return_value = iter(events)
    return agent


def test_stream_agent_response_collects_model_chunks() -> None:
    chunk = MagicMock()
    chunk.content = "hello"
    events = [
        {"event": "on_chat_model_stream", "data": {"chunk": chunk}},
        {"event": "on_chain_end", "data": {"output": {"messages": []}}},
    ]
    agent = _make_stream_agent(events)

    response = _stream_agent_response(agent, [], "thread-1")

    assert response == "hello"


def test_stream_agent_response_logs_tool_events() -> None:
    events = [
        {"event": "on_tool_start", "data": {"name": "read-file", "input": {"path": "/tmp/x"}}},
        {"event": "on_tool_end", "data": {}},
        {"event": "on_chain_end", "data": {"output": {"messages": []}}},
    ]
    agent = _make_stream_agent(events)

    response = _stream_agent_response(agent, [], "thread-1")

    assert response == "(no text response)"


def test_stream_agent_response_falls_back_to_invoke() -> None:
    message = MagicMock()
    message.content = "fallback"
    agent = MagicMock()
    agent.invoke.return_value = {"messages": [message]}
    if hasattr(agent, "astream_events"):
        del agent.astream_events

    response = _stream_agent_response(agent, [], "thread-1")

    assert response == "fallback"


def test_stream_agent_response_handles_empty_message_content() -> None:
    message = MagicMock()
    message.content = None
    events = [
        {"event": "on_chain_end", "data": {"output": {"messages": [message]}}},
    ]
    agent = _make_stream_agent(events)

    response = _stream_agent_response(agent, [], "thread-1")

    assert response == "(no text response)"
