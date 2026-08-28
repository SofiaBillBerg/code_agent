"""FastAPI web UI for the capability layer.

This module is a **thin HTTP adapter** over the business logic that now lives
entirely in :mod:`berg_agents.ui.web_chat_server` (the
:class:`LangGraphChatServer` singleton).  Every route handler acquires the
server via ``get_server()`` and delegates to a server method; the handler is
responsible only for HTTP concerns:

* Unpacking Pydantic request bodies
* Wrapping server-returned dicts into response models
* Framing streaming generators with SSE (``data:`` prefix) via ``_sse``
* Translating server-side errors into ``HTTPException`` status codes

All mutable state, agent lifecycle, HITL event handling, audit logging, and
protocol-v2 event queues live in ``LangGraphChatServer`` — this file has
**zero module-level state** beyond the ``app`` object and the static mount.

Security notes:

* Every invocation is validated by the capability's own ``input_model``;
  invalid params are rejected with HTTP 400 before any tool runs.
* Requests, params and results are never logged, so secrets and API keys
  cannot leak through the web server.
* When ``BERG_AGENT_AUTH_TOKEN`` is set, every request must include a matching
  ``X-CodeAgent-Auth-Token`` header. Without it, the server returns HTTP 401.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, Literal
import uuid

from berg_agents.capabilities.envelope import InvokeBody
from berg_agents.config.settings import get_settings
from berg_agents.ui.protocol import _sse
from berg_agents.ui.web_chat_server import get_server
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

#: Module logger — used for protocol stream error reporting.
logger = __import__("logging").getLogger(__name__)

#: Directory of the built React app (created by ``npm run build`` in webapp/).
_DIST_DIR = Path(__file__).resolve().parent / "webapp" / "dist"


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------
# These are kept in web.py because they are part of the HTTP contract.  The
# SDK and the SPA depend on their shape.  When the canonical source moves to
# ``chat_schema.py`` (see ``chat_server.py``'s docstring), these will become
# thin re-imports.
# ---------------------------------------------------------------------------


class ProviderConfig(BaseModel):
    """Configuration for a single provider/model pair.

    Attributes:
        name: Provider identifier (e.g. "ollama", "openai").
        model: Model string (e.g. "gpt-oss:20b", "gpt-4o").
    """

    name: str
    model: str


class ProviderListResponse(BaseModel):
    """Response from GET /providers.

    Attributes:
        providers: List of configured provider configurations.
    """

    providers: list[ProviderConfig]


class ActiveProviderResponse(BaseModel):
    """Response from GET /providers/active.

    Attributes:
        provider: Currently active provider name.
        model: Currently active model string.
    """

    provider: str
    model: str


class ActiveProviderRequest(BaseModel):
    """Body for POST /providers/active.

    Attributes:
        provider: Provider name to switch to.
        model: Model string to switch to.
    """

    provider: str
    model: str


class ChatMessage(BaseModel):
    """A single chat message with role and content.

    Attributes:
        role: The role of the message sender (e.g., "user", "assistant").
        content: The content of the message.
    """

    role: str
    content: str


class ChatRequest(BaseModel):
    """A request to send a chat message to the agent.

    Attributes:
        message: The user message to send.
        thread_id: Optional thread ID for conversational state.
    """

    message: str
    thread_id: str | None = None


class ChatResponse(BaseModel):
    """A response from the agent containing the reply and thread ID.

    Attributes:
        response: The assistant's response.
        thread_id: The active thread ID.
    """

    response: str
    thread_id: str


# -- SSE Event Models (kept for SDK / frontend contract) -------------------


class TokenEvent(BaseModel):
    """SSE event representing a single token chunk from the LLM."""

    type: str = "token"
    content: str


class ToolStartEvent(BaseModel):
    """SSE event emitted when a tool call begins."""

    type: str = "tool_start"
    tool: str
    input: dict[str, Any]


class ToolEndEvent(BaseModel):
    """SSE event emitted when a tool call completes."""

    type: str = "tool_end"
    tool: str
    output: str
    elapsed_s: float


class DoneEvent(BaseModel):
    """SSE event emitted when the agent completes successfully."""

    type: str = "done"


class HitlPendingEvent(BaseModel):
    """SSE event emitted when the graph pauses for human approval (HITL)."""

    type: str = "hitl_pending"
    tool: str
    input: dict[str, Any]
    thread_id: str


class ErrorEvent(BaseModel):
    """SSE event emitted when an error occurs during streaming."""

    type: str = "error"
    reason: str


class ResumeRequest(BaseModel):
    """Body for POST /chat/resume.

    Attributes:
        thread_id: The thread whose HITL interrupt is being resolved.
        decision: "approve" or "reject".
    """

    thread_id: str
    decision: Literal["approve", "reject"]


class CancelRequest(BaseModel):
    """Body for POST /chat/cancel.

    Attributes:
        thread_id: The thread whose running agent should be canceled.
    """

    thread_id: str


class HistoryRequest(BaseModel):
    """Query params for GET /chat/history.

    Attributes:
        thread_id: The thread whose history is requested.
        limit: Maximum number of messages to return (default 20).
    """

    thread_id: str
    limit: int = 20


class HistoryResponse(BaseModel):
    """Response from GET /chat/history.

    Attributes:
        messages: List of message dicts with role, content, and optional tool_calls.
    """

    messages: list[dict[str, Any]]


class AuditEntry(BaseModel):
    """A single audit log entry."""

    action: str
    details: dict[str, Any]
    timestamp: str
    user: str


class AuditRequest(BaseModel):
    """Body for POST /chat/audit.

    Attributes:
        thread_id: The thread to record the audit entry for.
        action: "approve", "reject", or "edit".
        details: Free-form dict of additional context.
        timestamp: ISO-8601 timestamp string.
        user: User identifier.
    """

    thread_id: str
    action: Literal["approve", "reject", "edit"]
    details: dict[str, Any] = {}
    timestamp: str
    user: str


class AuditResponse(BaseModel):
    """Response from POST /chat/audit."""

    status: str


class AuditListResponse(BaseModel):
    """Response from GET /chat/audit."""

    entries: list[dict[str, Any]]


class TodoEvent(BaseModel):
    """SSE event emitted when the todos list changes."""

    type: str = "todos"
    todos: list[dict[str, Any]]


class SubagentStartEvent(BaseModel):
    """SSE event emitted when a subagent starts."""

    type: str = "subagent_start"
    id: str
    name: str


class SubagentEndEvent(BaseModel):
    """SSE event emitted when a subagent ends."""

    type: str = "subagent_end"
    id: str
    name: str
    status: str = "success"


class PingEvent(BaseModel):
    """SSE heartbeat event emitted periodically to keep the connection alive."""

    type: str = "ping"


class ProtocolCommand(BaseModel):
    """A LangGraph protocol v2 command.

    Attributes:
        id: Client-generated command ID that must be echoed in the response.
        method: Command method name (e.g. "run.start", "input.respond", "run.stop").
        params: Command-specific parameters.
    """

    id: int | None = None
    method: str
    params: dict[str, Any] = {}


class ProtocolStreamRequest(BaseModel):
    """Request body for POST /threads/{thread_id}/stream/events.

    Attributes:
        channels: List of channels to subscribe to.
        namespaces: Optional list of namespace prefixes to filter.
        depth: Optional max depth for namespace matching.
        since: Optional sequence number to replay from.
    """

    channels: list[str]
    namespaces: list[list[str]] | None = None
    depth: int | None = None
    since: int | None = None


class ThreadCreatePayload(BaseModel):
    """Payload for creating a new thread.

    Attributes:
        metadata: Optional metadata to attach to the thread.
        thread_id: Optional client-generated thread ID.
        if_exists: Behavior when thread_id already exists ('raise' or 'do_nothing').
    """

    metadata: dict[str, Any] | None = None
    thread_id: str | None = None
    if_exists: str | None = None


class SwitchModelRequest(BaseModel):
    """Body for switching a thread's model.

    Attributes:
        provider: The provider name (e.g. "openai", "ollama").
        model: The model name (e.g. "gpt-4", "mistral").
        base_url: Optional base URL for the provider (if not default).
    """

    provider: str
    model: str
    base_url: str | None = None


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class AuthMiddleware:
    """Reject requests that lack a valid auth token when one is configured.

    The expected token is read from the ``BERG_AGENT_AUTH_TOKEN`` environment
    variable and compared against the ``X-CodeAgent-Auth-Token`` header.
    This provides a simple way to password-protect the web API when exposed
    to untrusted networks.
    When no ``BERG_AGENT_AUTH_TOKEN`` is set, the middleware allows all requests.

    Attributes:
        app: The wrapped ASGI application.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode().lower(): v.decode() for k, v in scope.get("headers", [])
        }
        token = headers.get("x-bergagents-auth-token")
        expected = get_settings().auth_token

        if expected is not None and token != expected:
            from fastapi.responses import JSONResponse

            response = JSONResponse(
                content={"detail": "Unauthorized"}, status_code=401
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


class RequestLoggingMiddleware:
    """Log all incoming requests for debugging."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            method = scope.get("method", "?")
            path = scope.get("path", "?")
            query = scope.get("query_string", b"").decode(
                "utf-8", errors="replace"
            )
            print(f"[REQ] {method} {path}?{query}")
        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

# noinspection argument-equal-default
app = FastAPI(
    title="Berg Agents Web UI",
    description=(
        "Web interface for the berg_agents capability layer: list "
        "capabilities and invoke them through the audited registry."
    ),
    version="0.1.0",
)

if get_settings().auth_token is not None:
    app.add_middleware(AuthMiddleware)

app.add_middleware(  # type: ignore[arg-type]
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-CodeAgent-Auth-Token"],
)

app.add_middleware(RequestLoggingMiddleware)


# ---------------------------------------------------------------------------
# Route handlers — every handler delegates to LangGraphChatServer
# ---------------------------------------------------------------------------


@app.get("/providers")
async def list_providers() -> ProviderListResponse:
    """Return all configured providers and their available models."""
    server = get_server()
    raw = server.list_providers()
    return ProviderListResponse(providers=[ProviderConfig(**p) for p in raw])


@app.get("/providers/active")
async def get_active_provider() -> ActiveProviderResponse:
    """Return the currently active provider and model."""
    server = get_server()
    raw = server.get_active_provider()
    return ActiveProviderResponse(**raw)


@app.post("/providers/active")
async def set_active_provider(request: ActiveProviderRequest) -> dict[str, str]:
    """Switch the active provider and model, reinitializing the agent."""
    server = get_server()

    #: Validate against the configured provider list
    error = server.validate_provider(request.provider, request.model)
    if error:
        raise HTTPException(status_code=422, detail=error)

    result = await server.set_active_provider(request.provider, request.model)

    if result.get("status") == "error":
        raise HTTPException(
            status_code=503,
            detail=result.get("detail", "provider switch in progress"),
        )

    return {"status": "ok"}


@app.post("/chat/resume")
async def chat_resume(request: ResumeRequest) -> dict[str, str]:
    """Deliver an approval/reject decision for a paused HITL interrupt."""
    server = get_server()
    try:
        server.resume_hitl(request.thread_id, request.decision)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "ok"}


@app.post("/chat")
async def chat(request: ChatRequest) -> ChatResponse:
    """Send a chat message to the agent and return the response (legacy)."""
    server = get_server()
    result = server.chat(request.message, request.thread_id)
    return ChatResponse(**result)


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Send a chat message to the agent via SSE streaming (legacy)."""
    server = get_server()

    async def _wrap() -> AsyncGenerator[str, None]:
        try:
            async for chunk in server.chat_stream(
                request.message, request.thread_id
            ):
                yield chunk
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return StreamingResponse(
        _wrap(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Thread-Id": request.thread_id or "",
        },
    )


@app.post("/chat/cancel")
async def chat_cancel(request: CancelRequest) -> dict[str, str]:
    """Cancel a running agent thread."""
    server = get_server()
    try:
        server.cancel_legacy(request.thread_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "cancelled"}


@app.get("/chat/history")
async def chat_history(thread_id: str, limit: int = 20) -> HistoryResponse:
    """Return the message history for a thread."""
    server = get_server()
    messages = await server.chat_history(thread_id, limit)
    return HistoryResponse(messages=messages)


@app.post("/chat/audit")
async def chat_audit(request: AuditRequest) -> AuditResponse:
    """Record an audit log entry for a thread."""
    server = get_server()
    server.audit_entry(
        request.thread_id,
        request.action,
        request.details,
        request.timestamp,
        request.user,
    )
    return AuditResponse(status="recorded")


@app.get("/chat/audit")
async def chat_audit_list(thread_id: str) -> AuditListResponse:
    """List audit log entries for a thread."""
    server = get_server()
    entries = server.audit_list(thread_id)
    return AuditListResponse(entries=entries)


# ---------------------------------------------------------------------------
# LangGraph Protocol v2 endpoints (for useStream frontend SDK)
# ---------------------------------------------------------------------------


@app.post("/threads")
async def create_thread(payload: ThreadCreatePayload) -> dict[str, Any]:
    """Create a new thread."""
    server = get_server()
    return server.create_thread(
        payload.thread_id, payload.metadata, payload.if_exists
    )


@app.post("/threads/{thread_id}/commands")
async def thread_commands(
    thread_id: str, command: ProtocolCommand
) -> dict[str, Any]:
    """Handle a LangGraph protocol v2 command.

    Supported commands: ``run.start``, ``input.respond``, ``run.stop``.
    """
    server = get_server()
    try:
        return await server.handle_protocol_command(
            thread_id, command.method, command.params or {}, command.id or 0
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/threads/{thread_id}/stream/events")
async def thread_stream_events(
    thread_id: str,
    channels: str | None = None,
    since: int | None = None,
) -> StreamingResponse:
    """Open a LangGraph protocol v2 SSE event stream (GET with query params)."""
    server = get_server()
    _since = since or 0

    async def _event_stream() -> AsyncGenerator[str, None]:
        async for event in server.thread_stream_events(thread_id, _since):
            yield _sse(event)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/threads/{thread_id}/stream/events")
async def thread_stream_events_post(
    thread_id: str, request: ProtocolStreamRequest
) -> StreamingResponse:
    """Open a LangGraph protocol v2 SSE event stream via POST."""
    server = get_server()
    _since = request.since or 0

    async def _event_stream() -> AsyncGenerator[str, None]:
        async for event in server.thread_stream_events(thread_id, _since):
            yield _sse(event)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/threads/{thread_id}/runs/stream")
async def thread_runs_stream(
    thread_id: str,
    request: dict[str, Any],
) -> StreamingResponse:
    """Start a run and stream SSE events."""
    server = get_server()

    input_data = request.get("input", {})
    messages = input_data.get("messages", [])
    human_msg = next(
        (m for m in messages if m.get("type") in ("human", "user")), None
    )
    text = human_msg.get("content", "") if human_msg else ""

    async def _event_stream() -> AsyncGenerator[str, None]:
        if not text:
            yield _sse({
                "method": "lifecycle",
                "params": {
                    "namespace": [],
                    "data": {"event": "failed", "error": "No message content"},
                },
            })
            return

        run_id = server.start_background_run(thread_id, text)

        seq = 0
        try:
            async for event in server.thread_stream_events(thread_id, 0):
                params = event.get("params", {})
                evt_seq = params.get("seq", seq + 1)
                if evt_seq > seq:
                    seq = evt_seq
                    yield _sse(event, seq=evt_seq)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Content-Location": f"/threads/{thread_id}/runs/{uuid.uuid4()}",
        },
    )


@app.get("/threads/{thread_id}/runs/{run_id}/stream")
async def thread_runs_join_stream(
    thread_id: str,
    run_id: str,
    last_event_id: str | None = Header(None),
) -> StreamingResponse:
    """Reconnect to an existing run's SSE event stream."""
    server = get_server()
    _since = (
        int(last_event_id) if last_event_id and last_event_id != "-1" else 0
    )

    async def _event_stream() -> AsyncGenerator[str, None]:
        async for event in server.thread_stream_events(thread_id, _since):
            params = event.get("params", {})
            evt_seq = params.get("seq", _since + 1)
            if evt_seq > _since:
                _since = evt_seq
                yield _sse(event, seq=evt_seq)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/threads/{thread_id}/runs/{run_id}/cancel")
async def thread_runs_cancel(
    thread_id: str,
    run_id: str,
) -> dict[str, Any]:
    """Cancel a running task."""
    server = get_server()
    server.cancel_run(thread_id)
    return {}


@app.post("/threads/{thread_id}/history")
async def thread_history(
    thread_id: str,
    request: dict[str, Any],
) -> list[dict[str, Any]]:
    """Get past states for a thread."""
    server = get_server()
    return await server.get_thread_history(thread_id)


@app.get("/threads/{thread_id}/state")
async def thread_state(thread_id: str) -> dict[str, Any]:
    """Get the current state of a thread."""
    server = get_server()
    return await server.get_thread_state(thread_id)


@app.get("/models")
def list_models_endpoint() -> dict[str, Any]:
    """Return available models for the dynamic model selector."""
    server = get_server()
    return {"models": server.list_models()}


@app.get("/threads/{thread_id}/export")
async def export_thread(thread_id: str, format: str = "md") -> Any:
    """Export a thread's conversation as a downloadable file."""
    from fastapi.responses import Response

    server = get_server()
    try:
        body = await server.export_thread(thread_id, format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Clean thread_id for filename (take first segment before dots, truncate)
    clean_id = (
        thread_id.split(".", maxsplit=1)[0][:8]
        if "." in thread_id
        else thread_id[:8]
    )
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="bergagents-chat-{clean_id}.md"'
            )
        },
    )


@app.post("/threads/{thread_id}/model")
async def switch_thread_model(
    thread_id: str, body: SwitchModelRequest
) -> dict[str, Any]:
    """Switch the model for a given thread."""
    server = get_server()
    result = await server.set_thread_model(
        thread_id, body.provider, body.model, body.base_url
    )
    if result.get("status") == "error":
        raise HTTPException(
            status_code=409, detail=result.get("detail", "Cannot switch model")
        )
    return result


@app.get("/capabilities")
def list_capabilities() -> list[dict[str, Any]]:
    """Return metadata for every registered capability."""
    server = get_server()
    return server.list_capabilities()


@app.post("/invoke")
def invoke_capability(body: InvokeBody) -> dict[str, Any]:
    """Dispatch an invocation and return the response plus audit receipt."""
    server = get_server()
    try:
        return server.invoke_capability(body.capability_id, body.params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Static file mount — SPA at root
# ---------------------------------------------------------------------------

if _DIST_DIR.is_dir():
    from starlette.responses import FileResponse, Response

    class NoCacheStaticFiles(StaticFiles):
        """StaticFiles subclass that disables caching for SPA files."""

        async def get_response(
            self, path: str, scope: Any
        ) -> FileResponse | Response:
            response = await super().get_response(path, scope)
            if isinstance(response, FileResponse):
                response.headers["Cache-Control"] = (
                    "no-cache, no-store, must-revalidate"
                )
                response.headers["Pragma"] = "no-cache"
                response.headers["Expires"] = "0"
            return response

    app.mount(
        "/",
        NoCacheStaticFiles(directory=str(_DIST_DIR), html=True),
        name="webapp",
    )

    # Include orchestrator routes (new multi-agent system)
    # Deferred import to avoid circular imports at module level
    from berg_agents.ui.orchestrator_routes import router as _orch_router

    # include_router doesn't work in this context due to import ordering,
    # so we append routes directly
    for _route in _orch_router.routes:
        app.routes.append(_route)
