# tests/test_capabilities.py
"""Tests for the OAP-inspired capability layer.

Covers the capability contract (:mod:`code_agent.capabilities.base`), the
request/response envelopes (:mod:`code_agent.capabilities.envelope`), the
hash-chained audit log (:mod:`code_agent.capabilities.audit`), the registry
discovery and dispatch flow (:mod:`code_agent.capabilities.registry`) and
the LangChain tool adapter (:mod:`code_agent.capabilities.tool_adapter`).

The adapter depends on ``langchain.tools.BaseTool``; when that package is
not importable a minimal stand-in is injected into ``sys.modules`` first so
the tests run without the real dependency.
"""

from __future__ import annotations

import hashlib
import importlib
import sys
import types

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from pydantic import BaseModel, ValidationError

from code_agent.capabilities.audit import AuditLog, Receipt  # noqa: E402
from code_agent.capabilities.base import (  # noqa: E402
    CapabilityBase,
    RiskClass,
)
from code_agent.capabilities.envelope import (  # noqa: E402
    InvocationRequest,
    InvocationResponse,
)
from code_agent.capabilities.registry import CapabilityRegistry  # noqa: E402
from code_agent.capabilities.tool_adapter import (  # noqa: E402
    ToolResult,
    tool_to_capability,
)


try:
    from langchain.tools import (  # ruff: ignore[unused-import]  # type: ignore[import-not-found]
        BaseTool,
    )
except (ImportError, AttributeError):
    # Inject a stand-in before any ``code_agent`` import because
    # ``code_agent/__init__.py`` eagerly imports ``tool_adapter`` and the
    # provider modules, all of which import langchain packages.
    langchain_tools = sys.modules.get("langchain.tools")
    if langchain_tools is None:
        langchain_tools = types.ModuleType("langchain.tools")
        sys.modules["langchain.tools"] = langchain_tools
    langchain_tools.BaseTool = object
    langchain_pkg = sys.modules.get("langchain")
    if langchain_pkg is None:
        langchain_pkg = types.ModuleType("langchain")
        sys.modules["langchain"] = langchain_pkg
    langchain_pkg.tools = langchain_tools

# ``code_agent/__init__.py`` also eagerly imports the provider modules,
# which need ``langchain_ollama`` and ``langchain_openai``; stand in for
# them too when they are missing.
for _module_name, _attr in (
    ("langchain_ollama", "ChatOllama"),
    ("langchain_openai", "ChatOpenAI"),
):
    try:
        importlib.import_module(_module_name)
    except (ImportError, AttributeError):
        _module = sys.modules.get(_module_name)
        if _module is None:
            _module = types.ModuleType(_module_name)
            sys.modules[_module_name] = _module
        if not hasattr(_module, _attr):
            setattr(_module, _attr, type(_attr, (), {}))


# ---------------------------------------------------------------------------
# Dummy contracts and capabilities (no network required)
# ---------------------------------------------------------------------------


class EchoInput(BaseModel):
    """Input contract for the echo test capability."""

    text: str
    times: int = 1


class EchoOutput(BaseModel):
    """Output contract for the echo test capability."""

    text: str


class EchoCapability(CapabilityBase):
    """Low-risk test capability that echoes its input text."""

    id = "echo"
    intent = "Echo the input text a number of times"
    input_model = EchoInput
    output_model = EchoOutput
    risk_class = RiskClass.LOW

    def _execute(self, params: BaseModel) -> BaseModel:
        echo_input = EchoInput.model_validate(params)
        return EchoOutput(text=echo_input.text * echo_input.times)


class UpperEchoCapability(CapabilityBase):
    """Second capability sharing the ``echo`` id, used by the replace test."""

    id = "echo"
    intent = "Echo the input text uppercased"
    input_model = EchoInput
    output_model = EchoOutput
    risk_class = RiskClass.LOW

    def _execute(self, params: BaseModel) -> BaseModel:
        echo_input = EchoInput.model_validate(params)
        return EchoOutput(text=echo_input.text.upper() * echo_input.times)


class FailingCapability(CapabilityBase):
    """Test capability whose execution always raises."""

    id = "boom"
    intent = "Always fails"
    input_model = EchoInput
    output_model = EchoOutput

    def _execute(self, params: BaseModel) -> BaseModel:
        raise RuntimeError("kaboom")


class GatedCapability(CapabilityBase):
    """High-risk test capability that must never run unapproved."""

    id = "gated"
    intent = "Dangerous operation"
    input_model = EchoInput
    output_model = EchoOutput
    risk_class = RiskClass.HIGH

    executed = False

    def _execute(self, params: BaseModel) -> BaseModel:
        type(self).executed = True
        return EchoOutput(text="ran")


@pytest.fixture
def registry() -> CapabilityRegistry:
    """Return a fresh registry with a low-risk echo capability registered."""
    reg = CapabilityRegistry()
    reg.register(EchoCapability())  # type: ignore[arg-type]
    return reg


# ---------------------------------------------------------------------------
# Capability base contract
# ---------------------------------------------------------------------------


def test_capability_base_rejects_wrong_params_type() -> None:
    """``invoke`` must raise TypeError when params are not the input model."""
    capability = EchoCapability()
    with pytest.raises(TypeError, match="EchoInput"):
        capability.invoke({"text": "nope"})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Envelope construction and validation
# ---------------------------------------------------------------------------


def test_invocation_request_requires_ids() -> None:
    """Missing request_id/capability_id must fail validation."""
    with pytest.raises(ValidationError):
        InvocationRequest()  # type: ignore[call-arg]


def test_invocation_request_defaults() -> None:
    """params/caller default and created_at is an ISO timestamp."""
    request = InvocationRequest(request_id="r1", capability_id="echo")
    assert request.params == {}
    assert request.caller is None
    assert "T" in request.created_at


def test_invocation_request_accepts_caller_and_params() -> None:
    """Custom caller and params are preserved."""
    request = InvocationRequest(
        request_id="r1",
        capability_id="echo",
        params={"text": "hi"},
        caller="test",
    )
    assert request.caller == "test"
    assert request.params == {"text": "hi"}


def test_invocation_response_defaults() -> None:
    """Response defaults to an empty ok envelope."""
    response = InvocationResponse(request_id="r1", capability_id="echo")
    assert response.status == "ok"
    assert response.result is None
    assert response.error is None
    assert response.duration_ms == 0


def test_invocation_response_rejects_invalid_status() -> None:
    """``status`` is restricted to ok/error."""
    with pytest.raises(ValidationError):
        InvocationResponse(
            request_id="r1",
            capability_id="echo",
            status="maybe",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Registry: discovery
# ---------------------------------------------------------------------------


def test_register_and_discover_returns_metadata(
    registry: CapabilityRegistry,
) -> None:
    """Discover must return metadata for every registered capability."""
    metadata = registry.discover()
    assert [entry["id"] for entry in metadata] == ["echo"]
    entry = metadata[0]
    assert entry["intent"] == EchoCapability.intent
    assert entry["risk_class"] == RiskClass.LOW
    assert "input_schema" in entry
    assert "text" in entry["input_schema"]["properties"]


def test_register_replaces_existing_capability(
    registry: CapabilityRegistry,
) -> None:
    """Re-registering the same id must replace the previous entry."""
    registry.register(UpperEchoCapability())  # type: ignore[arg-type]
    assert len(registry.discover()) == 1
    response, _ = registry.dispatch(
        InvocationRequest(
            request_id="r1", capability_id="echo", params={"text": "hi"}
        )
    )
    assert response.status == "ok"
    assert response.result == {"text": "HI"}


# ---------------------------------------------------------------------------
# Registry: dispatch
# ---------------------------------------------------------------------------


def test_dispatch_valid_params_returns_ok(
    registry: CapabilityRegistry,
) -> None:
    """A valid request dispatches to the capability and returns a result."""
    response, receipt = registry.dispatch(
        InvocationRequest(
            request_id="r1",
            capability_id="echo",
            params={"text": "ha", "times": 2},
        )
    )
    assert response.status == "ok"
    assert response.result == {"text": "haha"}
    assert response.request_id == "r1"
    assert response.capability_id == "echo"
    assert receipt.request_id == "r1"


def test_dispatch_invalid_params_returns_error_response(
    registry: CapabilityRegistry,
) -> None:
    """Invalid params must produce an error response, not an exception."""
    response, _ = registry.dispatch(
        InvocationRequest(
            request_id="r1", capability_id="echo", params={"times": "x"}
        )
    )
    assert response.status == "error"
    assert response.error is not None
    assert "invalid params" in response.error


def test_dispatch_unknown_capability_returns_error_response(
    registry: CapabilityRegistry,
) -> None:
    """An unknown capability id must produce an error response."""
    response, _ = registry.dispatch(
        InvocationRequest(request_id="r1", capability_id="nope")
    )
    assert response.status == "error"
    assert "unknown capability" in (response.error or "")


def test_dispatch_high_risk_gated_without_approval(
    registry: CapabilityRegistry,
) -> None:
    """High-risk capabilities must be gated until explicitly approved."""
    GatedCapability.executed = False
    registry.register(GatedCapability())  # type: ignore[arg-type]
    response, _ = registry.dispatch(
        InvocationRequest(
            request_id="r1", capability_id="gated", params={"text": "x"}
        )
    )
    assert response.status == "error"
    assert "high-risk" in (response.error or "")
    assert GatedCapability.executed is False


def test_dispatch_invocation_exception_returns_error_response(
    registry: CapabilityRegistry,
) -> None:
    """An exception inside the capability surfaces as an error response."""
    registry.register(FailingCapability())  # type: ignore[arg-type]
    response, _ = registry.dispatch(
        InvocationRequest(
            request_id="r1", capability_id="boom", params={"text": "x"}
        )
    )
    assert response.status == "error"
    assert "invocation failed" in (response.error or "")


# ---------------------------------------------------------------------------
# Registry: audit receipts
# ---------------------------------------------------------------------------


def test_dispatch_records_audit_receipt(registry: CapabilityRegistry) -> None:
    """Every dispatch must emit an audit receipt."""
    _, receipt = registry.dispatch(
        InvocationRequest(
            request_id="r1", capability_id="echo", params={"text": "hi"}
        )
    )
    assert isinstance(receipt, Receipt)
    assert receipt.status == "ok"
    assert receipt.capability_id == "echo"


def test_dispatch_receipts_are_hash_chained(
    registry: CapabilityRegistry,
) -> None:
    """Receipts must link via prev_hash to the previous receipt."""
    _, first = registry.dispatch(
        InvocationRequest(
            request_id="r1", capability_id="echo", params={"text": "a"}
        )
    )
    _, second = registry.dispatch(
        InvocationRequest(
            request_id="r2", capability_id="echo", params={"text": "b"}
        )
    )
    assert first.prev_hash == "GENESIS"
    assert second.prev_hash == first.receipt_hash


# ---------------------------------------------------------------------------
# Audit log: hash chaining and append-only behavior
# ---------------------------------------------------------------------------


def test_audit_first_receipt_prev_hash_is_genesis() -> None:
    """The first receipt anchors the chain at GENESIS."""
    log = AuditLog()
    receipt = log.record("r1", "echo", "ok")
    assert receipt.prev_hash == "GENESIS"
    assert receipt.receipt_hash != "GENESIS"


def test_audit_receipts_form_hash_chain() -> None:
    """Each receipt's prev_hash must equal the previous receipt_hash."""
    log = AuditLog()
    receipts = [log.record(f"r{i}", "echo", "ok") for i in range(3)]
    assert receipts[1].prev_hash == receipts[0].receipt_hash
    assert receipts[2].prev_hash == receipts[1].receipt_hash
    assert log.last_hash == receipts[2].receipt_hash


def test_audit_hash_chain_detects_tampering() -> None:
    """Altering any recorded field must break the stored chain hash."""
    log = AuditLog()
    first = log.record("r1", "echo", "ok")
    second = log.record("r2", "echo", "ok")

    def chain_hash(prev: str, receipt: Receipt) -> str:
        parts = [
            prev,
            receipt.request_id,
            receipt.capability_id,
            receipt.status,
            receipt.timestamp,
        ]
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    assert chain_hash(first.receipt_hash, second) == second.receipt_hash
    tampered = second.model_copy(update={"request_id": "r2-CHANGED"})
    assert chain_hash(first.receipt_hash, tampered) != second.receipt_hash


def test_audit_read_chain_returns_copy() -> None:
    """read_chain must expose a copy, keeping the log append-only."""
    log = AuditLog()
    log.record("r1", "echo", "ok")
    chain = log.read_chain()
    chain.append(
        Receipt(
            request_id="fake",
            capability_id="echo",
            status="ok",
            timestamp="t",
            prev_hash="x",
            receipt_hash="y",
        )
    )
    assert len(log.read_chain()) == 1


def test_audit_persists_receipts_to_file(tmp_path: Path) -> None:
    """Receipts must be appended as JSON lines when a path is given."""
    audit_path = tmp_path / "audit.jsonl"
    log = AuditLog(path=audit_path)
    log.record("r1", "echo", "ok")
    log.record("r2", "echo", "error")
    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert '"request_id": "r1"' in lines[0]


# ---------------------------------------------------------------------------
# Tool adapter: wrapping a BaseTool into a Capability
# ---------------------------------------------------------------------------


def _make_tool(
    name: str = "read_file",
    description: str = "Read a file",
    args_schema: type[BaseModel] | None = EchoInput,
    run: Any = None,
) -> MagicMock:
    """Build a mocked LangChain tool for the adapter tests."""
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.args_schema = args_schema
    if run is not None:
        tool._run.side_effect = run
    return tool


def test_tool_to_capability_kebab_case_id() -> None:
    """The capability id must be the kebab-cased tool name."""
    capability = tool_to_capability(_make_tool(name="read_file"))
    assert capability.id == "read-file"


def test_tool_to_capability_intent_from_description() -> None:
    """The intent must come from the tool description."""
    capability = tool_to_capability(_make_tool(description="Fetch a file"))
    assert capability.intent == "Fetch a file"


def test_tool_to_capability_infers_low_risk_for_read_only_tool() -> None:
    """Read-only tool names map to low risk."""
    capability = tool_to_capability(_make_tool(name="search_files"))
    assert capability.risk_class == RiskClass.LOW


def test_tool_to_capability_infers_medium_risk_for_mutating_tool() -> None:
    """Non-read-only tool names map to medium risk."""
    capability = tool_to_capability(_make_tool(name="write_file"))
    assert capability.risk_class == RiskClass.MEDIUM


def test_tool_to_capability_explicit_risk_class_override() -> None:
    """An explicit risk_class must win over the heuristic."""
    capability = tool_to_capability(
        _make_tool(name="read_file"), risk_class=RiskClass.HIGH
    )
    assert capability.risk_class == RiskClass.HIGH


def test_tool_to_capability_delegates_to_run() -> None:
    """Invoke must call the tool's _run with validated keyword params."""
    calls: list[dict[str, Any]] = []

    def run(**kwargs: Any) -> str:
        calls.append(kwargs)
        return "content"

    capability = tool_to_capability(_make_tool(run=run))
    result = capability.invoke(EchoInput(text="hello", times=2))
    assert calls == [{"text": "hello", "times": 2}]
    assert isinstance(result, ToolResult)
    assert result.output == "content"


def test_tool_to_capability_falls_back_to_invoke() -> None:
    """Tools without _run must fall back to invoke(tool_input)."""
    tool = _make_tool()
    tool._run.side_effect = NotImplementedError
    tool.invoke.return_value = "fallback output"
    capability = tool_to_capability(tool)
    result = capability.invoke(EchoInput(text="hello"))
    assert isinstance(result, ToolResult)
    assert result.output == "fallback output"
    tool.invoke.assert_called_once_with({"text": "hello", "times": 1})


def test_tool_to_capability_dispatchable_through_registry() -> None:
    """An adapted tool must work end-to-end through the registry."""
    tool = _make_tool(name="read_file", run=lambda **kwargs: kwargs["text"])
    registry = CapabilityRegistry()
    registry.register(tool_to_capability(tool))  # type: ignore[arg-type]
    response, receipt = registry.dispatch(
        InvocationRequest(
            request_id="r1",
            capability_id="read-file",
            params={"text": "hello"},
        )
    )
    assert response.status == "ok"
    assert response.result == {"output": "hello"}
    assert receipt.status == "ok"
