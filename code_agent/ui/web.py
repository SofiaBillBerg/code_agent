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
import uuid

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain.chat_models import BaseChatModel
from langchain.messages import HumanMessage
from langchain.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import BaseModel

from code_agent.agents.base_agent import build_agent, create_default_tools
from code_agent.capabilities.envelope import InvocationRequest, InvokeBody
from code_agent.capabilities.registry import CapabilityRegistry
from code_agent.config.settings import get_settings
from code_agent.main import create_llm, load_config
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
    """Reinitialise the global agent with a new provider/model.

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
                isinstance(checkpointer, SqliteSaver)
                and cfg.get("checkpoint_dir") is None
            ):
                checkpointer = InMemorySaver()
            if isinstance(checkpointer, InMemorySaver) and cfg.get(
                "checkpoint_dir"
            ):
                #: Rebuild a persistent (sqlite) checkpointer from the config
                #: path via ``build_checkpointer`` so the connection is opened
                #: correctly (``SqliteSaver`` expects a ``sqlite3.Connection``,
                #: not a path string).
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
        checkpointer: InMemorySaver | SqliteSaver = build_checkpointer(
            checkpoint_dir=get_settings().checkpoint_dir or None
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
        checkpointer: InMemorySaver | SqliteSaver = build_checkpointer(
            checkpoint_dir=get_settings().checkpoint_dir or None
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
app.add_middleware(
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
    """Switch the active provider and model, reinitialising the agent.

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


@app.post("/chat/resume")
async def chat_resume(request: ResumeRequest) -> dict[str, str]:
    """Deliver an approve/reject decision for a paused HITL interrupt.

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

    return StreamingResponse(
        _stream_agent_events(state.agent, request.message, effective_thread),
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
    stream_fn = getattr(agent, "astream_events", None)
    if stream_fn is None:
        #: Fallback to blocking invoke when astream_events is not available
        #: Emit error event and return
        yield _sse({"type": "error", "reason": "Streaming not supported"})
        return

    tool_start_times: dict[str, float] = {}

    try:  # ruff: ignore[too-many-statements-in-try-clause]
        async for event in stream_fn(
            {"messages": [HumanMessage(content=message)]},
            config={"configurable": {"thread_id": thread_id}},
            version="v2",
        ):
            etype = event.get("event", "")
            data = event.get("data", {})
            event_name = event.get("name", "")

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
    app.mount(
        "/", StaticFiles(directory=str(_DIST_DIR), html=True), name="webapp"
    )
