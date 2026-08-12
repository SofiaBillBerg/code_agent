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

from pathlib import Path
from typing import Any
import uuid

from code_agent.capabilities.envelope import InvocationRequest, InvokeBody
from code_agent.capabilities.registry import CapabilityRegistry
from code_agent.settings import get_settings
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Directory of the built React app (created by ``npm run build`` in webapp/).
_DIST_DIR = Path(__file__).resolve().parent / "webapp" / "dist"

_REGISTRY: CapabilityRegistry | None = None


def get_registry() -> CapabilityRegistry:
    """Return the shared capability registry, building it lazily on first use.

    The registry is built once per process so the audit receipt chain stays
    continuous across requests. It reuses the CLI's ``_build_registry``
    helper, guaranteeing ``GET /capabilities`` matches ``capabilities list``.

    :return: A :class:`CapabilityRegistry` populated with the default tool-adapted capabilities.
    """
    global _REGISTRY  # ruff: ignore [undefined-export]
    if _REGISTRY is None:
        # Imported lazily to avoid a circular import: ``cli.py`` imports
        # this module inside ``serve --web``, by which time ``cli.py`` has
        # finished loading and ``_build_registry`` is defined.
        from code_agent.cli import _build_registry

        _REGISTRY = _build_registry()
    return _REGISTRY


# Optional authentication middleware. When ``CODE_AGENT_AUTH_TOKEN`` is set,
# every request must carry a matching ``X-CodeAgent-Auth-Token`` header.
class AuthMiddleware:
    """Reject requests that lack a valid auth token when one is configured."""

    def __init__(self, app: Any) -> None:
        """Initialize the middleware with the ASGI app.

        :param app: The ASGI application to wrap.
        """
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        """Handle an ASGI request.

        :param scope: ASGI connection scope.
        :param receive: ASGI receive callable.
        :param send: ASGI send callable.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode(): v.decode() for k, v in scope.get("headers", [])}
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


app = FastAPI(
    title="Code Agent Web UI",
    description=(
        "Web interface for the code_agent capability layer: list "
        "capabilities and invoke them through the audited registry."
    ),
    version="0.1.0",
)

# Attach auth middleware when an auth token is configured.
if get_settings().auth_token is not None:
    app.add_middleware(AuthMiddleware)

# CORS for local Vite dev and preview origins so the SPA can call the API.
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


# Serve the built React app at the root when it exists. API routes registered
# above take precedence, so the SPA only handles paths that are not API calls.
if _DIST_DIR.is_dir():
    app.mount(
        "/", StaticFiles(directory=str(_DIST_DIR), html=True), name="webapp"
    )
