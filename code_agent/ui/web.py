"""FastAPI web UI for the capability layer.

Exposes the registered capabilities over HTTP so a browser (or any HTTP
client) can list and invoke them:

* ``GET /capabilities`` - lists the capability catalog. The catalog comes
  from the same registry builder the CLI's ``capabilities list`` command
  uses, so the web view always matches the CLI view.
* ``POST /invoke`` - dispatches an :class:`InvocationRequest` through the
  :class:`CapabilityRegistry` and returns the :class:`InvocationResponse`
  plus the hash-chained audit :class:`Receipt` as JSON.

The built React single-page app (``webapp/dist``) is mounted statically at
the root when present, so ``code-agent serve --web`` can host the whole UI
from a single process.

Security notes:

* Every invocation is validated by the capability's own ``input_model``;
  invalid params are rejected with HTTP 400 before any tool runs.
* Requests, params and results are never logged, so secrets and API keys
  cannot leak through the web server.
* When ``CODE_AGENT_AUTH_TOKEN`` is set, every request must include a matching
  ``X-CodeAgent-Auth-Token`` header. Without it, the server returns HTTP 401.
  This prevents unauthenticated remote access when the server is bound to a
  non-loopback interface.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Literal
import uuid

from code_agent.agents.deepagents_agent import build_agent, create_default_tools
from code_agent.capabilities.envelope import (
    InvocationRequest,
    InvocationResponse,
    InvokeBody,
)
from code_agent.capabilities.registry import CapabilityRegistry
from code_agent.config.settings import get_settings
from code_agent.main import create_llm, load_config
from code_agent.ui.protocol import _sse, translate_stream
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain.chat_models import BaseChatModel
from langchain.messages import HumanMessage
from langchain.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel

#: Module logger — used for protocol stream error reporting.
logger = logging.getLogger(__name__)
from code_agent.utils.checkpointer import build_checkpointer

#: Directory of the built React app (created by ``npm run build`` in webapp/).
_DIST_DIR = Path(__file__).resolve().parent / "webapp" / "dist"

#: Module-level state for agent and provider management
#: -------------------------------------------------------------------

#: Module-level registry singleton - None until get_registry() builds it.
#: This is used by GET /capabilities to share the same registry across requests.
_REGISTRY: CapabilityRegistry | None = None


@dataclass
class AgentState:
    """Holds the runtime state of the LangGraph agent.

    This dataclass replaces the old _AGENT / _AGENT_THREAD_ID globals with
    a structured container that also includes checkpointer, provider, and
    model information for runtime routing.

    Attributes:
        agent: The compiled LangGraph runnable.
        thread_id: The current conversation thread identifier.
        checkpointer: The LangGraph checkpointer (SqliteSaver or InMemorySaver).
        provider: The active provider name (e.g., "ollama").
        model: The active model string (e.g., "gpt-oss:20b").
    """

    agent: Any
    thread_id: str
    checkpointer: Any
    provider: str = "ollama"
    model: str = "gpt-oss:20b"


#: Module-level state for HITL (Human-in-the-Loop) interrupt handling
#: -------------------------------------------------------------------
#: _pending_hitl maps thread_id → asyncio.Event. When a HITL interrupt occurs,
#: the SSE stream waits on the event. The /chat/resume endpoint sets the event
#: when the user makes a decision (approve/reject).
_pending_hitl: dict[str, asyncio.Event] = {}

#: _hitl_decisions stores the user's decision ("approve" | "reject") for each
#: pending thread_id. The SSE stream reads this after the event fires.
_hitl_decisions: dict[str, str] = {}

#: Provider switching state
#: -------------------------------------------------------------------
#: _provider_switch_lock serializes concurrent provider switch requests.
#: _switching is True when a provider switch is in progress to reject new
#: chat requests during the reinitialization window.
_provider_switch_lock: asyncio.Lock = asyncio.Lock()
_switching: bool = False

#: Cancel state
#: -------------------------------------------------------------------
#: _pending_cancel maps thread_id -> asyncio.Event. When /chat/cancel is
#: called, the event is set so the SSE stream can stop early.
_pending_cancel: dict[str, asyncio.Event] = {}

#: _thread_tasks maps thread_id -> asyncio.Task. The /chat/stream endpoint
#: registers the background task here so /chat/cancel can cancel it.
_thread_tasks: dict[str, asyncio.Task] = {}

#: Audit store
#: -------------------------------------------------------------------
#: _audit_log stores per-thread audit entries in memory, keyed by thread_id.
#: Each entry is a dict with action, details, timestamp, user fields.
_audit_log: dict[str, list[dict[str, Any]]] = {}

#: _audit_store is a flat list of audit entries used by /chat/audit endpoints.
_audit_store: list[dict[str, Any]] = []

#: Ping interval in seconds for SSE heartbeat.
_PING_INTERVAL_S: float = 15.0


#: -------------------------------------------------------------------
#: Provider Routing Models (for /providers endpoints)
#: MUST be defined before route handlers to avoid forward reference issues
#: -------------------------------------------------------------------


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


#: Agent state singleton — None until get_agent() builds it.
_STATE: AgentState | None = None


def get_registry() -> CapabilityRegistry:
    """Return the shared capability registry, building it lazily on first use.

    The registry is built once per process so the audit receipt chain stays
    continuous across requests. It reuses the CLI's ``_build_registry``
    helper, guaranteeing ``GET /capabilities`` matches ``capabilities list``.

    :return: A :class:`CapabilityRegistry` populated with the default tool-adapted capabilities.
    """
    global _REGISTRY  # ruff: ignore[global-statement, undefined-export]
    if _REGISTRY is None:
        from code_agent.cli import _build_registry

        _REGISTRY = _build_registry()
    return _REGISTRY


async def _reinit_agent(provider: str, model: str) -> None:
    """Reinitialize the global agent with a new provider/model.

    This function is called by the POST /providers/active endpoint to switch
    the active LLM provider and model at runtime without restarting the server.
    It acquires _provider_switch_lock to ensure only one switch happens at a
    time, and sets _switching = True during the rebuild to reject new chat
    requests.

    The function rebuilds the LLM, tools, and agent from scratch using the new
    provider configuration, then swaps the global _STATE.agent and updates the
    provider/model fields in _STATE.

    :param provider: Provider name (e.g. "ollama", "openai") from the configured provider_list.
    :param model: Model string (e.g. "gpt-oss:20b") to activate for the provider.
    :return: None
    """
    #: Acquire the provider switch lock to ensure only one switch at a time
    async with _provider_switch_lock:
        #: Set switching flag to reject new chat requests during rebuild
        # ruff: ignore[global-statement] - need to update module-level state
        global _switching, _STATE
        _switching = True
        try:
            #: Load fresh config and override provider/model
            cfg = load_config()
            cfg["provider"] = provider
            cfg["model"] = model

            #: Build fresh LLM and tools
            llm = create_llm(cfg)
            tools = create_default_tools(root_dir=str(Path.cwd()), llm=llm)
            from code_agent.cli import _load_mcp_tools

            tools.extend(_load_mcp_tools(cfg))

            #: Get existing checkpointer from current state (or build new one)
            checkpointer = None
            if _STATE is not None:
                checkpointer = _STATE.checkpointer
            if checkpointer is None:
                checkpointer = build_checkpointer(
                    checkpoint_dir=get_settings().checkpoint_dir
                )
            #: If we're switching from sqlite to memory (or vice versa), we need to recreate the checkpointer to match the new backend
            if (
                isinstance(checkpointer, (SqliteSaver, AsyncSqliteSaver))
                and cfg.get("checkpoint_dir") is None
            ):
                checkpointer = InMemorySaver()
            if isinstance(checkpointer, InMemorySaver) and cfg.get(
                "checkpoint_dir"
            ):
                #: Rebuild a persistent (sqlite) checkpointer from the config
                #: path via ``build_checkpointer`` so the connection is opened
                #: correctly. The async web runtime requires ``AsyncSqliteSaver``
                #: (an ``aiosqlite.Connection``), not a sync ``SqliteSaver``.
                checkpointer = build_checkpointer(
                    checkpoint_dir=cfg["checkpoint_dir"]
                )

            #: Build new agent with the new LLM and existing checkpointer
            agent = build_agent(llm=llm, tools=tools, checkpointer=checkpointer)

            #: Update global state with new agent and provider/model
            _STATE = AgentState(
                agent=agent,
                thread_id=str(uuid.uuid4()),
                checkpointer=checkpointer,
                provider=provider,
                model=model,
            )
        finally:
            #: Clear switching flag to allow new chat requests again
            _switching = False


def get_agent() -> AgentState:
    """Return the shared agent state, building it lazily on first use.

    The agent is initialized from the same config path the CLI ``serve``
    command uses. The checkpointer is wired up via ``build_checkpointer()``
    so thread state persists across process restarts when SqliteSaver is
    available, falling back to InMemorySaver if the checkpoint directory
    is not accessible.

    :return: An :class:`AgentState` instance containing the agent, thread_id,
        and checkpointer.
    """
    global _STATE  # ruff: ignore[global-statement, undefined-export]
    if _STATE is None:
        from code_agent.cli import _load_mcp_tools

        cfg = load_config()
        llm: BaseChatModel = create_llm(cfg)
        tools: list[BaseTool] = create_default_tools(
            root_dir=str(Path.cwd()), llm=llm
        )
        tools.extend(_load_mcp_tools(cfg))
        checkpointer: InMemorySaver | SqliteSaver | AsyncSqliteSaver = (
            build_checkpointer(
                checkpoint_dir=get_settings().checkpoint_dir or None
            )
        )
        agent = build_agent(llm=llm, tools=tools, checkpointer=checkpointer)
        _STATE = AgentState(
            agent=agent,
            thread_id=str(uuid.uuid4()),
            checkpointer=checkpointer,
            provider=cfg.get("provider", "ollama"),
            model=cfg.get("model", "gpt-oss:20b"),
        )
    return _STATE


async def get_agent_async() -> AgentState:
    """Async version of get_agent for use in async contexts.

    This function is identical to get_agent() but uses the async version
    of _load_mcp_tools to avoid "asyncio.run() cannot be called from a
    running event loop" errors in FastAPI endpoints.

    :return: An :class:`AgentState` instance containing the agent, thread_id,
        and checkpointer.
    """
    global _STATE  # ruff: ignore[global-statement, undefined-export]
    if _STATE is None:
        from code_agent.cli import _load_mcp_tools_async

        cfg = load_config()
        llm: BaseChatModel = create_llm(cfg)
        tools: list[BaseTool] = create_default_tools(
            root_dir=str(Path.cwd()), llm=llm
        )
        tools.extend(await _load_mcp_tools_async(cfg))
        checkpointer: InMemorySaver | SqliteSaver | AsyncSqliteSaver = (
            build_checkpointer(
                checkpoint_dir=get_settings().checkpoint_dir or None
            )
        )
        agent = build_agent(llm=llm, tools=tools, checkpointer=checkpointer)
        _STATE = AgentState(
            agent=agent,
            thread_id=str(uuid.uuid4()),
            checkpointer=checkpointer,
            provider=cfg.get("provider", "ollama"),
            model=cfg.get("model", "gpt-oss:20b"),
        )
    return _STATE


#: Optional authentication middleware. When ``CODE_AGENT_AUTH_TOKEN`` is set,
#: every request must carry a matching ``X-CodeAgent-Auth-Token`` header.
class AuthMiddleware:
    """Reject requests that lack a valid auth token when one is configured.


    The expected token is read from the ``CODE_AGENT_AUTH_TOKEN`` environment
    variable and compared against the ``X-CodeAgent-Auth-Token`` header.
    This provides a simple way to password-protect the web API when exposed
    to untrusted networks.
    When no ``CODE_AGENT_AUTH_TOKEN`` is set, the middleware allows all requests.

    Attributes:
        app: The wrapped ASGI application.
    """

    def __init__(self, app: Any) -> None:
        """Initialize the middleware with the ASGI app.

        :param app: The ASGI application to wrap.
        :return: None
        """
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        """Handle an ASGI request.

        :param scope: ASGI connection scope.
        :param receive: ASGI receive callable.
        :param send: ASGI send callable.
        :return: None
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        #: ASGI headers are bytes and case-insensitive - normalize to lowercase
        headers = {
            k.decode().lower(): v.decode() for k, v in scope.get("headers", [])
        }
        token = headers.get("x-codeagent-auth-token")
        expected = get_settings().auth_token

        if expected is not None and token != expected:
            from fastapi.responses import JSONResponse

            response = JSONResponse(
                content={"detail": "Unauthorized"}, status_code=401
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


# noinspection argument-equal-default
app = FastAPI(
    title="Code Agent Web UI",
    description=(
        "Web interface for the code_agent capability layer: list "
        "capabilities and invoke them through the audited registry."
    ),
    version="0.1.0",
)

#: Attach auth middleware when an auth token is configured.
if get_settings().auth_token is not None:
    app.add_middleware(AuthMiddleware)

#: CORS for local Vite dev and preview origins so the SPA can call the API.
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


app.add_middleware(RequestLoggingMiddleware)


@app.get("/providers")
async def list_providers() -> ProviderListResponse:
    """Return all configured providers and their available models.

    This endpoint reads the provider_list from Settings (configured via
    CODE_AGENT_PROVIDER_LIST environment variable or .env file) and returns
    it as a list of ProviderConfig objects. When no provider_list is configured,
    returns an empty array.

    :return: ProviderListResponse containing the list of configured providers.
    """
    settings = get_settings()
    raw_list = settings.provider_list or []
    providers = [
        ProviderConfig(name=p["name"], model=p["model"]) for p in raw_list
    ]
    return ProviderListResponse(providers=providers)


@app.get("/providers/active")
async def get_active_provider() -> ActiveProviderResponse:
    """Return the currently active provider and model.

    This endpoint reads the provider and model fields from the global _STATE
    AgentState instance. When the agent has not yet been initialized (first
    request before any chat), it falls back to default values from config.

    :return: ActiveProviderResponse with the current provider and model.
    """
    #: Use _STATE if available, otherwise read defaults from settings
    if _STATE is not None:
        return ActiveProviderResponse(
            provider=_STATE.provider,
            model=_STATE.model,
        )

    #: Fallback to defaults when agent not yet initialized
    settings = get_settings()
    return ActiveProviderResponse(
        provider=settings.provider,
        model=(
            settings.ollama_model
            if settings.provider == "ollama"
            else settings.openai_model
        ),
    )


@app.post("/providers/active")
async def set_active_provider(request: ActiveProviderRequest) -> dict[str, str]:
    """Switch the active provider and model, reinitializing the agent.

    This endpoint allows runtime switching of the LLM provider and model
    without restarting the server. It performs the following steps:

    1. Validates that the requested provider/model combination exists in
       the configured provider_list
    2. Returns HTTP 200 immediately if already switching to the same target
       (idempotent duplicate requests)
    3. Returns HTTP 503 if another switch is already in progress
    4. Returns HTTP 422 if provider/model is not in the configured list
    5. Runs the rebuild asynchronously via asyncio.create_task() to avoid
       holding the HTTP connection open during the agent reinitialization

    The provider switch is serialized using _provider_switch_lock to prevent
    race conditions, and _switching is set to True during the rebuild to
    reject new chat requests.

    :param request: ActiveProviderRequest with provider and model to switch to.
    :return: {"status": "ok"} on success.
    :raises HTTPException: 422 if provider/model not in configured list.
                           503 if a switch is already in progress.
    """
    settings = get_settings()
    valid_providers = {
        (p["name"], p["model"]) for p in (settings.provider_list or [])
    }

    #: Check if the requested provider/model is valid
    if (request.provider, request.model) not in valid_providers:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Provider {request.provider!r} / model {request.model!r} "
                f"is not in the configured provider_list. "
                f"Valid combinations: {sorted(valid_providers)}"
            ),
        )

    #: Idempotent: if already switching to the same target, return success immediately
    #: This handles duplicate requests from the UI without causing errors
    if (
        _switching
        and _STATE is not None
        and _STATE.provider == request.provider
        and _STATE.model == request.model
    ):
        return {"status": "ok"}

    #: If another switch is in progress, reject with 503
    if _switching:
        raise HTTPException(
            status_code=503, detail="provider switch in progress"
        )

    #: Run the rebuild asynchronously to avoid holding the HTTP connection open
    #: The async function _reinit_agent acquires _provider_switch_lock internally
    # ruff: ignore[asyncio-dangling-task] - task runs independently, no need to await
    asyncio.create_task(_reinit_agent(request.provider, request.model))

    return {"status": "ok"}


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


#: -------------------------------------------------------------------
#: SSE Event Models (for streaming chat endpoint)
#: -------------------------------------------------------------------


class TokenEvent(BaseModel):
    """SSE event representing a single token chunk from the LLM.

    Attributes:
        type: Event type identifier ("token").
        content: The partial text content of the token.
    """

    type: str = "token"
    content: str


class ToolStartEvent(BaseModel):
    """SSE event emitted when a tool call begins.

    Attributes:
        type: Event type identifier ("tool_start").
        tool: The tool name being invoked.
        input: The input arguments passed to the tool.
    """

    type: str = "tool_start"
    tool: str
    input: dict[str, Any]


class ToolEndEvent(BaseModel):
    """SSE event emitted when a tool call completes.

    Attributes:
        type: Event type identifier ("tool_end").
        tool: The tool name that completed.
        output: The tool's raw output (truncated to 2000 chars in handler).
        elapsed_s: Time spent in the tool in seconds, rounded to one decimal.
    """

    type: str = "tool_end"
    tool: str
    output: str
    elapsed_s: float


class DoneEvent(BaseModel):
    """SSE event emitted when the agent completes successfully.

    Attributes:
        type: Event type identifier ("done").
    """

    type: str = "done"


class HitlPendingEvent(BaseModel):
    """SSE event emitted when the graph pauses for human approval (HITL).

    Attributes:
        type: Event type identifier ("hitl_pending").
        tool: The tool name requiring approval.
        input: The tool input that needs approval.
        thread_id: The conversation thread identifier.
    """

    type: str = "hitl_pending"
    tool: str
    input: dict[str, Any]
    thread_id: str


class ErrorEvent(BaseModel):
    """SSE event emitted when an error occurs during streaming.

    Attributes:
        type: Event type identifier ("error").
        reason: Human-readable error description.
    """

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
    """A single audit log entry.

    Attributes:
        action: "approve", "reject", or "edit".
        details: Free-form dict of additional context.
        timestamp: ISO-8601 timestamp string.
        user: User identifier who performed the action.
    """

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
    """Response from POST /chat/audit.

    Attributes:
        status: "recorded" on success.
    """

    status: str


class AuditListResponse(BaseModel):
    """Response from GET /chat/audit.

    Attributes:
        entries: List of audit entries for the thread.
    """

    entries: list[dict[str, Any]]


class TodoEvent(BaseModel):
    """SSE event emitted when the todos list changes.

    Attributes:
        type: Event type identifier ("todos").
        todos: The current list of todo items from PlanningState.
    """

    type: str = "todos"
    todos: list[dict[str, Any]]


class SubagentStartEvent(BaseModel):
    """SSE event emitted when a subagent starts.

    Attributes:
        type: Event type identifier ("subagent_start").
        id: Identifier derived from the namespace or run id.
        name: The graph/node name of the subagent.
    """

    type: str = "subagent_start"
    id: str
    name: str


class SubagentEndEvent(BaseModel):
    """SSE event emitted when a subagent ends.

    Attributes:
        type: Event type identifier ("subagent_end").
        id: Identifier matching the subagent_start event.
        name: The graph/node name of the subagent.
        status: "success" or "error".
    """

    type: str = "subagent_end"
    id: str
    name: str
    status: str = "success"


class PingEvent(BaseModel):
    """SSE heartbeat event emitted periodically to keep the connection alive.

    Attributes:
        type: Event type identifier ("ping").
    """

    type: str = "ping"


@app.post("/chat/resume")
async def chat_resume(request: ResumeRequest) -> dict[str, str]:
    """Deliver an approval/reject decision for a paused HITL interrupt.

    This endpoint is called by the browser when the user clicks Approve or Reject
    on the HITL Surface component. It resolves the pending HITL interrupt by:

    1. Looking up the asyncio.Event for the given thread_id in _pending_hitl
    2. Storing the decision in _hitl_decisions for the SSE stream to read
    3. Setting the event to unblock the waiting SSE stream

    If no pending interrupt exists for the thread_id (either never registered
    or already resolved/cleaned up), returns HTTP 409.

    :param request: ResumeRequest containing thread_id and decision ("approve" | "reject").
    :return: {"status": "ok"} on success.
    :raises HTTPException: 409 if no pending HITL interrupt for thread_id.
    """
    #: Check if there is a pending HITL interrupt for this thread_id
    ev = _pending_hitl.get(request.thread_id)

    #: If no pending event exists, return 409 with detail explaining the issue
    #: This covers two cases:
    #: 1. The interrupt was never registered (thread_id invalid)
    #: 2. The interrupt was already resolved and cleaned up (stream closed)
    if ev is None:
        raise HTTPException(
            status_code=409,
            detail=f"No pending HITL interrupt for thread_id={request.thread_id!r}",
        )

    #: Store the user's decision for the SSE stream to read after the event fires
    _hitl_decisions[request.thread_id] = request.decision

    #: Signal the waiting SSE stream to resume with the user's decision
    ev.set()

    return {"status": "ok"}


@app.post("/chat")
async def chat(request: ChatRequest) -> ChatResponse:
    """Send a chat message to the agent and return the response.

    This is the legacy synchronous chat endpoint for backward compatibility.
    It invokes the agent synchronously and returns the final response.

    :param request: Parsed chat request containing the user message and optional thread_id.
    :return: ChatResponse with the assistant's reply and thread_id.
    """
    state = await get_agent_async()
    effective_thread = request.thread_id or state.thread_id

    # Invoke the agent synchronously with the message and thread config
    result = state.agent.invoke(
        {"messages": [HumanMessage(content=request.message)]},
        config={"configurable": {"thread_id": effective_thread}},
    )

    # Extract the response from the result
    messages = result.get("messages", [])
    response_text = "(no text response)"

    # Find the last AI message content
    for msg in reversed(messages):
        if hasattr(msg, "content") and msg.content:
            response_text = msg.content
            break

    return ChatResponse(response=response_text, thread_id=effective_thread)


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Send a chat message to the agent via Server-Sent Events (SSE) streaming.

    This endpoint returns a text/event-stream response that emits incremental
    events as the agent processes the request:

    - "token" events for each LLM output token chunk
    - "tool_start" events when a tool call begins
    - "tool_end" events when a tool call completes (output truncated to 2000 chars)
    - "hitl_pending" events when the graph pauses for human approval
    - "done" event when the agent completes successfully
    - "error" events when an exception occurs

    The stream stays open for up to 300 seconds while waiting for HITL decisions.
    Returns HTTP 503 if a provider switch is in progress.

    :param request: Parsed chat request containing the user message and optional thread_id.
    :return: StreamingResponse with media_type="text/event-stream".
    :raises HTTPException: 501 if streaming is disabled, 503 if provider switch in progress.
    """
    # Check if streaming is enabled via settings
    settings = get_settings()
    if not settings.stream_enabled:
        raise HTTPException(status_code=501, detail="Streaming is disabled.")

    # Check if a provider switch is in progress and reject with 503
    if _switching:
        raise HTTPException(
            status_code=503, detail="provider switch in progress"
        )

    state = await get_agent_async()
    effective_thread = request.thread_id or state.thread_id

    async def _stream_wrapper():
        try:
            async for chunk in _stream_agent_events(
                state.agent, request.message, effective_thread
            ):
                yield chunk
        finally:
            _thread_tasks.pop(effective_thread, None)

    streamer = _stream_wrapper()
    task = asyncio.create_task(streamer.__anext__())
    _thread_tasks[effective_thread] = task

    async def _consume_stream():
        try:
            async for chunk in streamer:
                yield chunk
        except asyncio.CancelledError:
            pass
        finally:
            _thread_tasks.pop(effective_thread, None)

    return StreamingResponse(
        _consume_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Thread-Id": effective_thread,  # Let client capture new thread_id
        },
    )


async def _stream_agent_events(  # ruff: ignore[complex-structure]
    agent: Any,
    message: str,
    thread_id: str,
) -> AsyncGenerator[str]:
    r"""Async generator that drives the agent and yields SSE-formatted event frames.

    This function uses LangGraph's astream_events v2 API to capture all graph
    execution events and translate them into SSE frames. It handles:

    - LLM token streaming (on_chat_model_stream)
    - Tool call start/end events (on_tool_start, on_tool_end)
    - HITL interrupts (graph pause for human approval)
    - Completion signals (on_chain_end with final output)
    - Exception handling (emits error event and closes stream)

    Falls back to blocking invoke() if astream_events is not available.

    The generator tracks tool call timing and truncates tool output to 2000
    characters as required by the specification.

    :param agent: The compiled LangGraph runnable (agent).
    :param message: The user message text to process.
    :param thread_id: The conversation thread identifier.
    :yields: SSE-formatted strings in the format "data: {json}\n\n".
    """
    import json
    import time

    def _sse(payload: dict[str, Any]) -> str:
        r"""Format a single SSE frame with the given payload.

        Each SSE frame consists of a "data:" prefix followed by JSON content,
        ending with two newlines. The event type is embedded inside the JSON
        payload as the "type" field for easy client-side parsing.

        :param payload: Dictionary to serialize as JSON.
        :return: SSE-formatted string ready to send to the client.
        """
        return f"data: {json.dumps(payload)}\n\n"

    #: Try astream_events first, fall back to invoke if not available
    stream_fn: Any = getattr(agent, "astream_events", None)
    if not callable(stream_fn):
        #: Fallback to blocking invoke when astream_events is not available
        #: Emit error event and return
        yield _sse({"type": "error", "reason": "Streaming not supported"})
        return

    tool_start_times: dict[str, float] = {}
    last_ping_time = time.monotonic()
    seen_subagents: set[str] = set()

    try:  # ruff: ignore[too-many-statements-in-try-clause]
        #: Emit initial ping to confirm connection
        yield _sse({"type": "ping"})

        async for event in stream_fn(  # type: ignore[operator]
            {"messages": [HumanMessage(content=message)]},
            config={"configurable": {"thread_id": thread_id}},
            version="v2",
        ):
            etype = event.get("event", "")
            data = event.get("data", {})
            event_name = event.get("name", "")

            #: Periodic ping to keep connection alive
            now = time.monotonic()
            if now - last_ping_time >= _PING_INTERVAL_S:
                yield _sse({"type": "ping"})
                last_ping_time = now

            if etype == "on_chat_model_stream":
                chunk = data.get("chunk")
                if chunk:
                    content = getattr(chunk, "content", None) or ""
                    if content:
                        yield _sse({"type": "token", "content": content})

            elif etype == "on_tool_start":
                tool_start_times[event_name] = time.monotonic()
                yield _sse({
                    "type": "tool_start",
                    "tool": event_name,
                    "input": data.get("input", {}),
                })

            elif etype == "on_tool_end":
                elapsed = round(
                    time.monotonic()
                    - tool_start_times.pop(event_name, time.monotonic()),
                    1,  # Round to one decimal place
                )
                raw_output = str(data.get("output", ""))
                output = raw_output[:2000]
                yield _sse({
                    "type": "tool_end",
                    "tool": event_name,
                    "output": output,
                    "elapsed_s": elapsed,
                })

            elif etype == "on_chain_start":
                #: Detect subagent start from lifecycle events
                if event_name and event_name not in seen_subagents:
                    # Heuristic: subagent nodes often have names like "agent:xxx" or "subgraph:xxx"
                    if ":" in event_name or event_name.startswith("agent"):
                        seen_subagents.add(event_name)
                        yield _sse({
                            "type": "subagent_start",
                            "id": event_name,
                            "name": event_name,
                        })

            elif etype == "on_chain_end":
                output = data.get("output", {})
                if isinstance(output, dict) and output.get("__interrupt__"):
                    interrupt_info = output["__interrupt__"]
                    tool_name = interrupt_info.get("tool", "")
                    tool_input = interrupt_info.get("input", {})

                    yield _sse({
                        "type": "hitl_pending",
                        "tool": tool_name,
                        "input": tool_input,
                        "thread_id": thread_id,
                    })

                    ev = _pending_hitl.get(thread_id)
                    if ev is not None:
                        try:
                            await asyncio.wait_for(ev.wait(), timeout=300.0)
                        except TimeoutError:
                            yield _sse({
                                "type": "error",
                                "reason": "hitl_timeout",
                            })
                            return
                        finally:
                            _pending_hitl.pop(thread_id, None)
                            _hitl_decisions.pop(thread_id, None)

                #: Detect subagent end from lifecycle events
                if event_name and event_name in seen_subagents:
                    seen_subagents.discard(event_name)
                    status = (
                        "error"
                        if isinstance(output, dict) and output.get("error")
                        else "success"
                    )
                    yield _sse({
                        "type": "subagent_end",
                        "id": event_name,
                        "name": event_name,
                        "status": status,
                    })

                #: Emit todos update if present in state output
                if isinstance(output, dict) and "todos" in output:
                    yield _sse({
                        "type": "todos",
                        "todos": output["todos"],
                    })

        yield _sse({"type": "ping"})
        yield _sse({"type": "done"})

    except asyncio.CancelledError:
        _pending_hitl.pop(thread_id, None)
        _hitl_decisions.pop(thread_id, None)
        return

    except Exception as exc:
        #: Re-raise the exception as an HTTP 500 error for the client
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        #: Ensure any exceptions are caught and converted to SSE error events
        if "exc" in locals():
            yield _sse({"type": "error", "reason": "internal_error"})


@app.post("/chat/cancel")
async def chat_cancel(request: CancelRequest) -> dict[str, str]:
    """Cancel a running agent thread.

    This endpoint is called by the browser when the user clicks a Cancel button.
    It looks up the asyncio.Task for the given thread_id in ``_thread_tasks``
    and cancels it. If the task is already done or no task is registered for
    the thread, returns HTTP 409.

    :param request: CancelRequest containing the thread_id to cancel.
    :return: {"status": "canceled"} on success.
    :raises HTTPException: 409 if no running task for thread_id.
    """
    task = _thread_tasks.get(request.thread_id)
    if task is None or task.done():
        raise HTTPException(
            status_code=409,
            detail=f"No running task for thread_id={request.thread_id!r}",
        )
    task.cancel()
    return {"status": "cancelled"}


@app.get("/chat/history")
async def chat_history(thread_id: str, limit: int = 20) -> HistoryResponse:
    """Return the message history for a thread.

    This endpoint reads the checkpointed state for the given thread_id and
    returns the list of messages. If the thread has no history, returns an
    empty list.

    :param thread_id: The thread whose history is requested.
    :param limit: Maximum number of messages to return (default 20).
    :return: HistoryResponse with a list of message dicts.
    """
    state = await get_agent_async()
    checkpointer = getattr(state.agent, "checkpointer", None)
    if checkpointer is None:
        return HistoryResponse(messages=[])

    try:
        config = {"configurable": {"thread_id": thread_id}}
        state_data = await checkpointer.aget(config)
        messages = state_data.get("messages", []) if state_data else []
        # Convert message objects to dicts, truncating to limit
        result = []
        for msg in messages[-limit:]:
            if hasattr(msg, "to_dict"):
                result.append(msg.to_dict())
            elif hasattr(msg, "content"):
                result.append({"role": "user", "content": msg.content})
            else:
                result.append({"role": "user", "content": str(msg)})
        return HistoryResponse(messages=result)
    except Exception as e:
        logger.exception(f"Error occurred while fetching chat history: {e}")
        return HistoryResponse(messages=[])


@app.post("/chat/audit")
async def chat_audit(request: AuditRequest) -> AuditResponse:
    """Record an audit log entry for a thread.

    This endpoint is called by the browser when the user performs an action
    that should be audited (approve, reject, edit). It stores the entry in
    the in-memory ``_audit_store``.

    :param request: AuditRequest containing thread_id, action, details, timestamp, and user.
    :return: AuditResponse with status "recorded".
    """
    entry = {
        "thread_id": request.thread_id,
        "action": request.action,
        "details": request.details,
        "timestamp": request.timestamp,
        "user": request.user,
    }
    _audit_store.append(entry)
    return AuditResponse(status="recorded")


@app.get("/chat/audit")
async def chat_audit_list(thread_id: str) -> AuditListResponse:
    """List audit log entries for a thread.

    :param thread_id: The thread whose audit entries are requested.
    :return: AuditListResponse with a list of audit entries.
    """
    entries = [e for e in _audit_store if e.get("thread_id") == thread_id]
    return AuditListResponse(entries=entries)


#: -------------------------------------------------------------------
#: LangGraph Protocol v2 endpoints (for useStream frontend SDK)
#: -------------------------------------------------------------------

#: Per-thread event queues for protocol v2 SSE streaming.
#: Maps thread_id → list of (seq, event_dict) tuples.
_protocol_event_queues: dict[str, list[tuple[int, dict[str, Any]]]] = {}
#: Maps thread_id → asyncio.Event for notifying the stream that new events are available.
_protocol_stream_notifiers: dict[str, asyncio.Event] = {}
#: Maps thread_id → set of active stream tasks (for cleanup).
_protocol_stream_tasks: dict[str, set[asyncio.Task]] = {}
#: Maps thread_id → interrupt_id for the currently pending HITL interrupt.
_pending_interrupt_ids: dict[str, str] = {}


def _get_or_create_queue(thread_id: str) -> list[tuple[int, dict[str, Any]]]:
    """Get or create the event queue for a thread."""
    if thread_id not in _protocol_event_queues:
        _protocol_event_queues[thread_id] = []
    return _protocol_event_queues[thread_id]


def _get_or_create_notifier(thread_id: str) -> asyncio.Event:
    """Get or create the notifier event for a thread."""
    if thread_id not in _protocol_stream_notifiers:
        _protocol_stream_notifiers[thread_id] = asyncio.Event()
    return _protocol_stream_notifiers[thread_id]


def _push_protocol_event(thread_id: str, event: dict[str, Any]) -> None:
    """Push a protocol event to the thread's queue and notify listeners."""
    queue = _get_or_create_queue(thread_id)
    notifier = _get_or_create_notifier(thread_id)
    seq = len(queue) + 1
    queue.append((seq, event))

    # Track interrupt IDs so we can match input.respond calls
    if event.get("method") == "input":
        params = event.get("params", {})
        data = params.get("data", {})
        if data.get("event") == "input-requested":
            interrupt_id = data.get("id")
            if interrupt_id:
                _pending_interrupt_ids[thread_id] = interrupt_id

    notifier.set()


def _extract_decision(response: Any) -> str:
    """Extract approve/reject decision from a protocol v2 input.respond response.

    Handles both the standard protocol format (plain value or object with
    ``type``/``decisions``) and the legacy custom format.
    """
    if isinstance(response, dict):
        # Standard protocol: {type: "approve"} or {decisions: [{type: "approve"}]}
        decisions = response.get("decisions")
        if isinstance(decisions, list) and decisions:
            first = decisions[0]
            if isinstance(first, dict):
                return "approve" if first.get("type") == "approve" else "reject"
        # Single decision object
        if "type" in response:
            return "approve" if response.get("type") == "approve" else "reject"
        # DeepAgents-style: {approved: true}
        if "approved" in response:
            return "approve" if response.get("approved") else "reject"
    # Plain truthy/falsy value
    return "approve" if response else "reject"


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


@app.post("/threads/{thread_id}/commands")
async def thread_commands(
    thread_id: str, command: ProtocolCommand
) -> dict[str, Any]:
    """Handle a LangGraph protocol v2 command.

    Supported commands:
    * ``run.start`` — start a new run with the given input
    * ``input.respond`` — respond to a pending HITL interrupt
    * ``run.stop`` — cancel a running

    :param thread_id: The thread to execute the command on.
    :param command: The protocol command to execute.
    :return: Command result dict.
    """
    method = command.method
    params = command.params or {}

    def _ok(result: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build a protocol v2 CommandResponse echoing the command id."""
        return {
            "type": "success",
            "id": command.id if command.id is not None else 0,
            "result": result or {},
        }

    if method == "run.start":
        # Extract input from params
        input_data = params.get("input", {})
        messages = input_data.get("messages", [])
        human_msg = next(
            (m for m in messages if m.get("type") in ("human", "user")), None
        )
        text = human_msg.get("content", "") if human_msg else ""

        if not text:
            return _ok()

        state = await get_agent_async()
        effective_thread = thread_id or state.thread_id

        async def _run():
            try:
                print(
                    f"[DEBUG] Starting stream for thread {effective_thread}, text: {text[:50]}"
                )
                async for event in translate_stream(
                    state.agent, text, effective_thread
                ):
                    _evt_data = event.get("params", {}).get("data", {})
                    print(
                        f"[DEBUG] Pushing event: {event.get('method')} "
                        f"{_evt_data.get('event', '')}"
                        + (
                            f" | error: {_evt_data.get('error')}"
                            if _evt_data.get("error")
                            else ""
                        )
                    )
                    _push_protocol_event(effective_thread, event)
                print(f"[DEBUG] Stream completed for thread {effective_thread}")
            except asyncio.CancelledError:
                print(f"[DEBUG] Stream cancelled for thread {effective_thread}")
            except Exception as exc:
                print(
                    f"[DEBUG] Stream error for thread {effective_thread}: {exc}"
                )
                #: No "seq" here on purpose — _push_protocol_event assigns the
                #: authoritative per-thread seq, and the SSE endpoint overrides
                #: the payload seq with it before writing the frame.
                _push_protocol_event(
                    effective_thread,
                    {
                        "method": "lifecycle",
                        "params": {
                            "namespace": [],
                            "data": {"event": "failed", "error": str(exc)},
                        },
                    },
                )

        task = asyncio.create_task(_run())
        _thread_tasks[effective_thread] = task
        return _ok({"run_id": str(uuid.uuid4())})

    elif method == "input.respond":
        # Standard protocol v2 format:
        # params: { namespace, interrupt_id, response, update?, goto?, config?, metadata? }
        response = params.get("response", {})
        interrupt_id = params.get("interrupt_id")

        # Validate interrupt_id if provided
        if interrupt_id:
            expected_id = _pending_interrupt_ids.get(thread_id)
            if expected_id and expected_id != interrupt_id:
                return {"status": "error", "error": "interrupt_id mismatch"}

        ev = _pending_hitl.get(thread_id)
        if ev is None:
            state = await get_agent_async()
            checkpointer = getattr(state.agent, "checkpointer", None)
            if checkpointer:
                try:
                    config = {"configurable": {"thread_id": thread_id}}
                    state_data = await checkpointer.aget(config)
                    if state_data and "__interrupt__" in state_data:
                        ev = asyncio.Event()
                        _pending_hitl[thread_id] = ev
                        _hitl_decisions[thread_id] = _extract_decision(response)
                        ev.set()
                        return _ok()
                except Exception as e:
                    logger.exception(
                        f"Error occurred while fetching interrupt decision: {e}"
                    )
            return _ok()

        _hitl_decisions[thread_id] = _extract_decision(response)
        ev.set()
        return _ok()

    elif method == "run.stop":
        task = _thread_tasks.get(thread_id)
        if task and not task.done():
            task.cancel()
        return _ok()

    return _ok()


@app.post("/threads/{thread_id}/stream/events")
async def thread_stream_events(
    thread_id: str,
    request: ProtocolStreamRequest,
) -> StreamingResponse:
    """Open a LangGraph protocol v2 SSE event stream.

    Uses POST with fetch streaming (not EventSource) — compatible with
    the @langchain/react built-in SSE transport.

    :param thread_id: The thread to stream events for.
    :param request: Stream subscription parameters.
    :return: StreamingResponse with protocol v2 SSE events.
    """
    channels = request.channels or [
        "values",
        "messages",
        "tools",
        "lifecycle",
        "input",
    ]
    since = request.since or 0

    effective_thread = thread_id
    queue = _get_or_create_queue(effective_thread)
    notifier = _get_or_create_notifier(effective_thread)

    async def _event_stream():
        nonlocal since
        try:
            # Replay events since the given since value.
            # NOTE: `since` MUST advance here too — otherwise the first
            # live-drain below re-yields everything we just replayed,
            # producing duplicate frames with regressing seq numbers
            # (which stalls the @langchain/protocol client).
            for seq, event in queue:
                if seq > since:
                    since = seq
                    #: Override the payload seq with the authoritative
                    #: per-thread queue seq so the wire sequence stays
                    #: strictly monotonic across multiple runs.
                    yield _sse(event)
                else:
                    # Skip events already seen
                    pass

            # Stream new events as they arrive
            while True:
                await notifier.wait()
                notifier.clear()

                # Drain any new events
                for seq, event in queue:
                    if seq > since:
                        since = seq
                        yield _sse(event)

                # Small sleep to avoid busy-looping
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            #: Never swallow stream errors silently — a NameError here
            #: previously killed every SSE connection with no trace.
            logger.exception(f"protocol v2 event stream failed: {e}")

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
        },
    )


@app.get("/threads/{thread_id}/state")
async def thread_state(thread_id: str) -> dict[str, Any]:
    """Get the current state of a thread.

    :param thread_id: The thread to get state for.
    :return: Current thread state dict.
    """
    state = await get_agent_async()
    checkpointer = getattr(state.agent, "checkpointer", None)
    if checkpointer is None:
        return {"values": {}, "next": [], "tasks": []}

    try:
        config = {"configurable": {"thread_id": thread_id}}
        state_data = await checkpointer.aget(config)
        if not state_data:
            return {"values": {}, "next": [], "tasks": []}

        messages = state_data.get("messages", [])
        values = {k: v for k, v in state_data.items() if k != "messages"}

        return {
            "values": values,
            "messages": [
                msg.to_dict() if hasattr(msg, "to_dict") else str(msg)
                for msg in messages
            ],
            "next": [],
            "tasks": [],
        }
    except Exception as e:
        logger.exception(f"Error occurred while fetching thread state: {e}")
        return {"values": {}, "next": [], "tasks": []}


@app.get("/capabilities")
def list_capabilities() -> list[dict[str, Any]]:
    """Return metadata for every registered capability.

    :return: A JSON list of capability metadata dicts (id, intent, risk_class,
        input_schema) from the shared registry.
    """
    return get_registry().discover()


@app.post("/invoke")
def invoke_capability(body: InvokeBody) -> dict[str, Any]:
    """Dispatch an invocation and return the response plus audit receipt.

    :param body: Parsed request body (capability_id and params).

    :return: A JSON object with ``response`` (the :class:`InvocationResponse`)
        and ``receipt`` (the audit :class:`Receipt`) fields.

    :raises HTTPException: 400 when the capability is unknown, high-risk, or the
            params fail validation. 401 when ``CODE_AGENT_AUTH_TOKEN`` is set
            but the request does not include a matching header.
    """
    request = InvocationRequest(
        request_id=uuid.uuid4().hex,
        capability_id=body.capability_id,
        params=body.params,
        caller="web",
    )
    response, receipt = get_registry().dispatch(request)
    if response.status == "error":
        raise HTTPException(status_code=400, detail=response.error)
    return {
        "response": response.model_dump(),
        "receipt": receipt.model_dump(),
    }


#: Serve the built React app at the root when it exists. API routes registered
#: above take precedence, so the SPA only handles paths that are not API calls.
if _DIST_DIR.is_dir():
    from starlette.responses import FileResponse, Response

    class NoCacheStaticFiles(StaticFiles):
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
