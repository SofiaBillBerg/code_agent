# tests/test_ui.py
"""Tests for the Code Agent UI layer (``code_agent.ui``).

Covers the rich terminal renderer (:mod:`code_agent.ui.cli_ui`) and the
FastAPI web UI (:mod:`code_agent.ui.web`).

The renderer tests build a small in-memory :class:`CapabilityRegistry` with
dummy capabilities so no network or real LLM provider is required. The web
test monkeypatches ``get_registry`` to return the same kind of isolated
registry, keeping the suite hermetic and fast.
"""

from __future__ import annotations

import io

from collections.abc import Callable, Iterator

import pytest

from fastapi.testclient import TestClient
from pydantic import BaseModel
from rich.console import Console

from code_agent.capabilities.audit import Receipt
from code_agent.capabilities.base import CapabilityBase, RiskClass
from code_agent.capabilities.envelope import (
    InvocationRequest,
    InvocationResponse,
)
from code_agent.capabilities.registry import CapabilityRegistry
from code_agent.ui import cli_ui
from code_agent.ui.web import app


# ---------------------------------------------------------------------------
# Dummy capabilities (no network required)
# ---------------------------------------------------------------------------


class _PingInput(BaseModel):
    """Empty input contract for the ping test capability."""


class _PingOutput(BaseModel):
    """Output contract for the ping test capability."""

    text: str


class PingCapability(CapabilityBase):
    """No-parameter test capability returning a fixed pong."""

    id = "ping"
    intent = "Ping the agent and get a pong back"
    input_model = _PingInput
    output_model = _PingOutput
    risk_class = RiskClass.LOW

    def _execute(self, params: BaseModel) -> BaseModel:
        return _PingOutput(text="pong")


class _AddInput(BaseModel):
    """Input contract carrying a single integer."""

    a: int


class _AddOutput(BaseModel):
    """Output contract carrying the incremented integer."""

    total: int


class AddCapability(CapabilityBase):
    """Test capability that increments its integer parameter."""

    id = "add"
    intent = "Add one to the supplied integer"
    input_model = _AddInput
    output_model = _AddOutput
    risk_class = RiskClass.LOW

    def _execute(self, params: BaseModel) -> BaseModel:
        add_input = _AddInput.model_validate(params)
        return _AddOutput(total=add_input.a + 1)


def _make_registry() -> CapabilityRegistry:
    """Return a fresh registry with the two dummy capabilities registered."""
    registry = CapabilityRegistry()
    registry.register(PingCapability())  # type: ignore[arg-type]
    registry.register(AddCapability())  # type: ignore[arg-type]
    return registry


def _capture_console() -> tuple[Console, Callable[[], str]]:
    """Return a recording Console and a callable that exports its text."""
    console = Console(record=True, file=io.StringIO(), width=100)
    return console, console.export_text


# ---------------------------------------------------------------------------
# Catalog + request/progress/response/receipt rendering
# ---------------------------------------------------------------------------


def test_render_catalog_lists_every_capability() -> None:
    """The catalog table must show each registered capability's id + intent."""
    console, export = _capture_console()
    cli_ui.render_catalog(_make_registry(), console)
    text = export()
    assert "Capability Catalog" in text
    assert "ping" in text
    assert "add" in text
    assert "Ping the agent" in text


def test_render_request_panel_shows_fields() -> None:
    """The request panel must surface the request id and capability id."""
    console, export = _capture_console()
    request = InvocationRequest(request_id="r1", capability_id="ping")
    cli_ui.render_request(request, console)
    text = export()
    assert "r1" in text
    assert "ping" in text
    assert "Invocation request" in text


def test_render_progress_shows_capability_and_request() -> None:
    """The progress line must name the capability and request being run."""
    console, export = _capture_console()
    request = InvocationRequest(request_id="r9", capability_id="add")
    cli_ui.render_progress(request, console)
    text = export()
    assert "add" in text
    assert "r9" in text
    assert "dispatching" in text.lower()


def test_render_response_success_is_green() -> None:
    """A successful response renders its result and a success title."""
    console, export = _capture_console()
    response = InvocationResponse(
        request_id="r1",
        capability_id="ping",
        status="ok",
        result={"text": "pong"},
        duration_ms=12,
    )
    cli_ui.render_response(response, console)
    text = export()
    assert "succeeded" in text.lower()
    assert "pong" in text


def test_render_response_error_is_red() -> None:
    """An error response renders the inline message, never a traceback."""
    console, export = _capture_console()
    response = InvocationResponse(
        request_id="r1",
        capability_id="ping",
        status="error",
        error="invalid params",
    )
    cli_ui.render_response(response, console)
    text = export()
    assert "failed" in text.lower()
    assert "invalid params" in text


def test_render_receipt_shows_hash_chain() -> None:
    """The receipt panel must expose the prev/receipt hash linkage."""
    console, export = _capture_console()
    receipt = Receipt(
        request_id="r1",
        capability_id="ping",
        status="ok",
        timestamp="2026-08-05T00:00:00",
        prev_hash="GENESIS",
        receipt_hash="abc123",
    )
    cli_ui.render_receipt(receipt, console)
    text = export()
    assert "prev_hash" in text
    assert "receipt_hash" in text
    assert "abc123" in text


# ---------------------------------------------------------------------------
# Interactive loop (run_cli_ui)
# ---------------------------------------------------------------------------


def _input_sequence(answers: list[str]) -> Callable[[str], str]:
    """Return a read-line callable that yields ``answers`` in order."""
    iterator: Iterator[str] = iter(answers)

    def _read(_prompt: str) -> str:
        return next(iterator)

    return _read


def test_run_cli_ui_quits_without_dispatch() -> None:
    """Selecting quit immediately must render the catalog and exit."""
    console, export = _capture_console()
    cli_ui.run_cli_ui(_make_registry(), console, _input_sequence(["q"]))
    text = export()
    assert "Capability Catalog" in text
    assert "Goodbye" in text


def test_run_cli_ui_dispatches_no_param_capability() -> None:
    """A no-parameter capability is dispatched and its receipt rendered."""
    console, export = _capture_console()
    cli_ui.run_cli_ui(_make_registry(), console, _input_sequence(["ping", "q"]))
    text = export()
    assert "succeeded" in text.lower()
    assert "Audit receipt" in text
    assert "Goodbye" in text


def test_run_cli_ui_coerces_and_dispatches_param() -> None:
    """An integer parameter is coerced and the capability result shown."""
    console, export = _capture_console()
    cli_ui.run_cli_ui(
        _make_registry(), console, _input_sequence(["add", "5", "q"])
    )
    text = export()
    assert "succeeded" in text.lower()
    assert "6" in text  # 5 + 1 from AddCapability


# ---------------------------------------------------------------------------
# Web UI endpoint (isolated registry via monkeypatch)
# ---------------------------------------------------------------------------


@pytest.fixture()
def web_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Return a TestClient whose registry is the isolated dummy registry."""
    monkeypatch.setattr(
        "code_agent.ui.web.get_registry", _make_registry, raising=True
    )
    return TestClient(app)


def test_web_capabilities_listed(web_client: TestClient) -> None:
    """GET /capabilities returns 200 and lists the dummy capabilities."""
    response = web_client.get("/capabilities")
    assert response.status_code == 200
    catalog = response.json()
    ids = {entry["id"] for entry in catalog}
    assert "ping" in ids
    assert "add" in ids


def test_web_invoke_returns_response_and_receipt(
    web_client: TestClient,
) -> None:
    """POST /invoke dispatches a valid capability and returns receipt."""
    response = web_client.post(
        "/invoke",
        json={"capability_id": "ping", "params": {}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["response"]["status"] == "ok"
    assert payload["response"]["result"] == {"text": "pong"}
    assert payload["receipt"]["capability_id"] == "ping"
    assert payload["receipt"]["receipt_hash"]


def test_web_invoke_unknown_capability_returns_400(
    web_client: TestClient,
) -> None:
    """POST /invoke with an unknown id returns HTTP 400."""
    response = web_client.post(
        "/invoke",
        json={"capability_id": "nope", "params": {}},
    )
    assert response.status_code == 400
