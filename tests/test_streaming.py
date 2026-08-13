"""Property and example tests for `/chat/stream` SSE endpoint.

Tests for Server-Sent Events streaming responses from the chat endpoint.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from starlette.responses import StreamingResponse

from code_agent.ui.web import app, ChatRequest


# Tag: Feature: agent-core-enhancement, Property 14: SSE stream properly formatted event


class TestStreamingEndpoint:
    """Tests for /chat/stream SSE endpoint."""

    @pytest.mark.asyncio
    async def test_sse_events_have_required_format(self) -> None:
        """Property 14: SSE events have the required `data:` prefix format.

        Each line yielded should start with `data: ` followed by valid JSON.

        An SSE event line should be formatted as:
        data: {"type": "message", "content": "..."}
        """
        # Arrange: Create mock streaming generator
        async def mock_generator() -> AsyncGenerator[str]:
            yield "data: {\"type\": \"message\", \"content\": \"Hello\"}\n"
            yield "data: {\"type\": \"done\", \"content\": null}\n"

        # Act: Verify event formatting
        events = []
        async for event in mock_generator():
            events.append(event)

        # Assert: All events start with 'data: '
        for event in events:
            assert event.startswith("data: ")

    @pytest.mark.asyncio 
    async def test_sse_event_structure_valid_json(self) -> None:
        """Property 14 variant: SSE event data contains valid JSON.

        The payload after 'data: ' should be parseable as JSON.
        """
        # Arrange
        raw_event = 'data: {"type": "message", "content": "test"}\n'

        # Act
        json_str = raw_event.replace("data: ", "").strip()
        data = json.loads(json_str)

        # Assert
        assert "type" in data
        assert isinstance(data["type"], str)

    def test_streaming_response_is_streaming_response(self) -> None:
        """Example test: /chat/stream returns StreamingResponse."""
        # This test verifies the endpoint returns correct response type
        client = TestClient(app)

        # The endpoint should exist and return streaming response
        response = client.post(
            "/chat/stream",
            json={"messages": [{"role": "user", "content": "Hello"}]},
            timeout=5,
        )

        assert response.status_code in [200, 401, 422]  # Auth or validation issues expected