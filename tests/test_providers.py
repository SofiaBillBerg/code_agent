# tests/test_providers.py
"""Tests for the provider-agnostic LLM layer.

Covers the ``LLMProvider`` protocol and ``ProviderBase``
(:mod:`code_agent.providers.base`), the provider factory
(:mod:`code_agent.providers.factory`) and the ``OllamaProvider`` /
``OpenAIProvider`` adapters (:mod:`code_agent.providers.ollama`,
:mod:`code_agent.providers.openai`).

The adapters import ``langchain_ollama`` / ``langchain_openai`` at module
level, and ``code_agent/__init__.py`` eagerly imports the whole agent stack.
When those optional dependencies are missing (as in a minimal test
environment) the real provider source files are loaded directly from disk
with stand-in langchain modules whose ``ChatOllama`` / ``ChatOpenAI`` are
``unittest.mock.MagicMock`` classes.  This keeps every test runnable without
the real dependency and guarantees no network calls: provider construction is
lazy and ``complete()`` is always exercised against a mocked client.
"""

from __future__ import annotations

import importlib.util
import sys
import types

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fallback: load the real provider modules without optional langchain deps
# ---------------------------------------------------------------------------


def _is_importable(module_name: str) -> bool:
    """Return True when *module_name* can be imported from this environment."""
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def _load_source_module(name: str, path: Path) -> types.ModuleType:
    """Load a Python source file as a module without executing parents.

    Used only when the ``code_agent`` package cannot be imported because
    optional dependencies are missing. The provider modules use absolute
    imports (``from code_agent.providers.base import ...``), so minimal
    parent packages are registered in ``sys.modules`` while the real source
    files execute; the entries are removed once loading completes.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create an import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def _stub_langchain_module(module_name: str, class_name: str) -> None:
    """Register a stand-in langchain module when the real one is missing."""
    if _is_importable(module_name) or module_name in sys.modules:
        return
    stub = types.ModuleType(module_name)
    setattr(stub, class_name, MagicMock)
    sys.modules[module_name] = stub


def _load_provider_modules() -> tuple[
    types.ModuleType, types.ModuleType, types.ModuleType, types.ModuleType
]:
    """Load the real provider modules without optional langchain packages.

    Returns the ``base``, ``factory``, ``ollama`` and ``openai`` modules in
    that order.  Temporary ``sys.modules`` entries are removed afterwards so
    the fallback does not leak into other tests.
    """
    providers_dir = (
        Path(__file__).resolve().parent.parent / "code_agent" / "providers"
    )

    _stub_langchain_module("langchain_ollama", "ChatOllama")
    _stub_langchain_module("langchain_openai", "ChatOpenAI")

    installed: list[str] = []
    try:
        # Minimal parent packages so the absolute imports inside the provider
        # modules resolve without executing ``code_agent/__init__.py``.
        for pkg_name in ("code_agent", "code_agent.providers"):
            pkg = types.ModuleType(pkg_name)
            pkg.__path__ = []  # type: ignore[attr-defined]
            sys.modules[pkg_name] = pkg
            installed.append(pkg_name)

        modules: dict[str, types.ModuleType] = {}
        for mod_name, file_name in (
            ("code_agent.providers.base", "base.py"),
            ("code_agent.providers.ollama", "ollama.py"),
            ("code_agent.providers.openai", "openai.py"),
            ("code_agent.providers.factory", "factory.py"),
        ):
            module = _load_source_module(mod_name, providers_dir / file_name)
            installed.append(mod_name)
            modules[mod_name] = module
        return (
            modules["code_agent.providers.base"],
            modules["code_agent.providers.factory"],
            modules["code_agent.providers.ollama"],
            modules["code_agent.providers.openai"],
        )
    finally:
        for name in installed:
            sys.modules.pop(name, None)


# ---------------------------------------------------------------------------
# Import the real provider modules (full env) or fall back to file loading
# ---------------------------------------------------------------------------

# The class names below are bound either from the real ``code_agent``
# package (full environment) or from the file-based fallback.  They are
# declared as ``Any`` so static analysis accepts both binding paths and so
# tests can reach adapter-specific attributes.
LLMProvider: Any
ProviderBase: Any
OllamaProvider: Any
OpenAIProvider: Any

try:  # noqa: E402  (imports follow the fallback helpers by design)
    import code_agent.providers.factory as _factory_mod  # noqa: E402
    import code_agent.providers.ollama as _ollama_mod  # noqa: E402
    import code_agent.providers.openai as _openai_mod  # noqa: E402

    from code_agent.providers.base import (  # noqa: E402
        LLMProvider,
        ProviderBase,
    )
except ImportError:
    # Minimal environment: load the real provider source files directly.
    _base_mod, _factory_mod, _ollama_mod, _openai_mod = _load_provider_modules()
    LLMProvider = _base_mod.LLMProvider
    ProviderBase = _base_mod.ProviderBase

OllamaProvider = _ollama_mod.OllamaProvider
OpenAIProvider = _openai_mod.OpenAIProvider


# ---------------------------------------------------------------------------
# Dummy providers used by the protocol / factory tests (no network)
# ---------------------------------------------------------------------------


class DummyProvider:
    """Minimal structural match for the ``LLMProvider`` protocol."""

    name: str = "dummy"

    def complete(self, messages: list[dict[str, Any]]) -> str:
        """Return a canned completion."""
        return "dummy response"

    def bind_capabilities(self, caps: list[Any]) -> "DummyProvider":
        """Return self (no tool-binding needed)."""
        return self


class IncompleteProvider:
    """Provider missing ``complete``; must not satisfy the protocol."""

    name: str = "incomplete"

    def bind_capabilities(self, caps: list[Any]) -> "IncompleteProvider":
        """Return self (no tool-binding needed)."""
        return self


class EchoProvider(ProviderBase):
    """Concrete ``ProviderBase`` subclass that only implements ``complete``."""

    name: str = "echo"

    def complete(self, messages: list[dict[str, Any]]) -> str:
        """Return a canned completion."""
        return "echo"


class FakeProvider:
    """Stand-in provider registered into the factory for dispatch tests."""

    name: str = "fake"

    def __init__(self, **kwargs: Any) -> None:
        """Store config keys and adopt an optional ``name`` override."""
        self.kwargs = kwargs
        if "name" in kwargs:
            self.name = kwargs["name"]

    def complete(self, messages: list[dict[str, Any]]) -> str:
        """Return a canned completion."""
        return "fake"

    def bind_capabilities(self, caps: list[Any]) -> "FakeProvider":
        """Return self (no tool-binding needed)."""
        return self


def _fake_provider_factory(config: dict[str, Any]) -> FakeProvider:
    """Factory callable used when monkeypatching the provider registry."""
    return FakeProvider(name=config.get("name", "fake"))


# ---------------------------------------------------------------------------
# LLMProvider protocol (runtime_checkable structural contract)
# ---------------------------------------------------------------------------


def test_dummy_provider_satisfies_llm_provider_protocol() -> None:
    """A class with name/complete/bind_capabilities must match the protocol."""
    assert isinstance(DummyProvider(), LLMProvider)


def test_incomplete_provider_does_not_satisfy_protocol() -> None:
    """A provider missing ``complete`` must not match the protocol."""
    assert not isinstance(IncompleteProvider(), LLMProvider)


def test_concrete_adapters_satisfy_llm_provider_protocol() -> None:
    """Both shipped adapters must structurally satisfy the protocol."""
    assert isinstance(OllamaProvider(model="m"), LLMProvider)
    assert isinstance(OpenAIProvider(model="m", api_key="k"), LLMProvider)


# ---------------------------------------------------------------------------
# ProviderBase (ABC with a no-op bind_capabilities default)
# ---------------------------------------------------------------------------


def test_provider_base_bind_capabilities_returns_self() -> None:
    """The default bind_capabilities must be a no-op returning self."""
    provider = EchoProvider()
    assert provider.bind_capabilities([object()]) is provider


def test_provider_base_requires_complete_implementation() -> None:
    """``complete`` is abstract; a subclass without it must not instantiate."""

    class MissingComplete(ProviderBase):
        """Subclass that forgets to implement ``complete``."""

        name: str = "broken"

    with pytest.raises(TypeError):
        MissingComplete()


# ---------------------------------------------------------------------------
# Factory: provider selection
# ---------------------------------------------------------------------------


def test_create_provider_selects_ollama_provider() -> None:
    """An ``ollama`` config must yield an OllamaProvider (no network)."""
    provider = cast(
        Any,
        _factory_mod.create_provider({
            "provider": "ollama",
            "model": "gpt-oss:20b-cloud",
        }),
    )
    assert isinstance(provider, OllamaProvider)
    assert provider.name == "ollama"
    assert provider.model == "gpt-oss:20b-cloud"


def test_create_provider_defaults_to_ollama_when_key_missing() -> None:
    """A config without a provider key must fall back to the default."""
    provider = _factory_mod.create_provider({"model": "gpt-oss:20b-cloud"})
    assert isinstance(provider, OllamaProvider)


def test_create_provider_defaults_to_ollama_when_key_is_none() -> None:
    """A None provider key must also fall back to the default."""
    provider = _factory_mod.create_provider({
        "provider": None,
        "model": "gpt-oss:20b-cloud",
    })
    assert isinstance(provider, OllamaProvider)


def test_create_provider_selects_openai_provider() -> None:
    """An ``openai`` config must yield an OpenAIProvider (no network)."""
    provider = cast(
        Any,
        _factory_mod.create_provider({
            "provider": "openai",
            "model": "gpt-4o",
            "api_key": "test-key",
        }),
    )
    assert isinstance(provider, OpenAIProvider)
    assert provider.name == "openai"
    assert provider.model == "gpt-4o"
    assert provider.api_key == "test-key"


def test_create_provider_openai_forwards_config_options() -> None:
    """Known config keys must be forwarded to the OpenAI adapter."""
    provider = cast(
        Any,
        _factory_mod.create_provider({
            "provider": "openai",
            "model": "gpt-4o",
            "api_key": "k",
            "base_url": "https://example.test/v1",
            "temperature": 0.5,
        }),
    )
    assert provider.model == "gpt-4o"
    assert provider.api_key == "k"
    assert provider.base_url == "https://example.test/v1"


def test_create_provider_normalizes_provider_name() -> None:
    """Provider names must be case- and whitespace-insensitive."""
    provider = _factory_mod.create_provider({
        "provider": "  OLLAMA  ",
        "model": "m",
    })
    assert isinstance(provider, OllamaProvider)


# ---------------------------------------------------------------------------
# Factory: dispatch against the internal provider registry (monkeypatched)
# ---------------------------------------------------------------------------


def test_create_provider_dispatches_to_registered_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_provider must call the registered factory with the config."""
    monkeypatch.setattr(
        _factory_mod, "_PROVIDER_FACTORIES", {"fake": _fake_provider_factory}
    )
    provider = _factory_mod.create_provider({
        "provider": "fake",
        "name": "stub",
    })
    assert isinstance(provider, FakeProvider)
    assert provider.name == "stub"


def test_create_provider_unknown_lists_registered_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The error must list the providers currently registered."""
    monkeypatch.setattr(
        _factory_mod, "_PROVIDER_FACTORIES", {"fake": _fake_provider_factory}
    )
    with pytest.raises(ValueError) as excinfo:
        _factory_mod.create_provider({"provider": "nope"})
    assert "fake" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Factory: unknown provider error (real registry)
# ---------------------------------------------------------------------------


def test_create_provider_unknown_provider_raises_value_error() -> None:
    """An unknown provider must raise a ValueError naming the supported set."""
    with pytest.raises(ValueError, match="Unknown LLM provider 'unknown'"):
        _factory_mod.create_provider({"provider": "unknown"})
    with pytest.raises(ValueError) as excinfo:
        _factory_mod.create_provider({"provider": "unknown"})
    message = str(excinfo.value)
    assert "ollama" in message
    assert "openai" in message


# ---------------------------------------------------------------------------
# Ollama adapter (mocked client, no network)
# ---------------------------------------------------------------------------


def test_ollama_provider_complete_returns_content() -> None:
    """``complete`` must return the client response content."""
    provider = OllamaProvider(model="gpt-oss:20b-cloud")
    client = MagicMock()
    client.invoke.return_value = SimpleNamespace(content="hello")
    provider._client = client
    messages = [{"role": "user", "content": "hi"}]
    assert provider.complete(messages) == "hello"
    client.invoke.assert_called_once_with(messages)


def test_ollama_provider_complete_wraps_backend_errors() -> None:
    """Backend failures must surface as a RuntimeError from ``complete``."""
    provider = OllamaProvider(model="gpt-oss:20b-cloud")
    client = MagicMock()
    client.invoke.side_effect = RuntimeError("backend down")
    provider._client = client
    with pytest.raises(RuntimeError, match="Ollama completion failed"):
        provider.complete([{"role": "user", "content": "hi"}])


def test_ollama_provider_bind_capabilities_returns_self() -> None:
    """The Ollama adapter must not rebind capabilities."""
    provider = OllamaProvider(model="m")
    assert provider.bind_capabilities([object()]) is provider


def test_ollama_provider_from_config_builds_connection_details() -> None:
    """from_config must read the ollama_* keys and build the base URL."""
    provider = OllamaProvider.from_config({
        "model": "m",
        "ollama_scheme": "https",
        "ollama_host": "server",
        "ollama_port": 8080,
    })
    assert provider.model == "m"
    assert provider.base_url == "https://server:8080"


# ---------------------------------------------------------------------------
# OpenAI adapter (mocked client, no network)
# ---------------------------------------------------------------------------


def test_openai_provider_complete_returns_content() -> None:
    """``complete`` must return the client response content."""
    provider = OpenAIProvider(model="gpt-4o", api_key="k")
    client = MagicMock()
    client.invoke.return_value = SimpleNamespace(content="hi there")
    provider._client = client
    messages = [{"role": "user", "content": "hi"}]
    assert provider.complete(messages) == "hi there"
    client.invoke.assert_called_once_with(messages)


def test_openai_provider_complete_wraps_backend_errors() -> None:
    """Backend failures must surface as a RuntimeError from ``complete``."""
    provider = OpenAIProvider(model="gpt-4o", api_key="k")
    client = MagicMock()
    client.invoke.side_effect = RuntimeError("backend down")
    provider._client = client
    with pytest.raises(RuntimeError, match="OpenAI completion failed"):
        provider.complete([{"role": "user", "content": "hi"}])


def test_openai_provider_bind_capabilities_returns_self() -> None:
    """The OpenAI adapter must not rebind capabilities."""
    provider = OpenAIProvider(model="m", api_key="k")
    assert provider.bind_capabilities([object()]) is provider


def test_openai_provider_explicit_api_key_wins_over_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit api_key must take precedence over the environment."""
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    provider = OpenAIProvider(model="gpt-4o", api_key="explicit")
    assert provider.api_key == "explicit"


def test_openai_provider_reads_api_key_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an api_key, OPENAI_API_KEY must be read from the environment."""
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    provider = OpenAIProvider(model="gpt-4o")
    assert provider.api_key == "env-key"
