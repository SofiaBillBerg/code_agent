# providers/factory.py
"""Provider factory for the OAP-inspired layer.

``create_provider(config)`` is the single entry point for constructing an
``LLMProvider`` from a config mapping. It reads the ``provider`` key
(e.g. ``"ollama"`` | ``"openai"``) and dispatches to the registered provider
factory, so business logic never references a concrete model backend.

Extending: register a new provider by adding one entry to
``_PROVIDER_FACTORIES`` mapping its name to either a ``from_config``
classmethod or a small builder function ``(config: dict) -> LLMProvider``.
"""

from __future__ import annotations

from typing import Any, Callable

from code_agent.providers.base import LLMProvider
from code_agent.providers.ollama import OllamaProvider
from code_agent.providers.openai import OpenAIProvider


#: Provider used when ``config`` has no ``provider`` key (backward compat).
DEFAULT_PROVIDER: str = "ollama"

#: Callable that builds an LLM provider from a config mapping.
ProviderFactory = Callable[[dict[str, Any]], LLMProvider]


def _openai_from_config(config: dict[str, Any]) -> OpenAIProvider:
    """Build an ``OpenAIProvider`` from a config mapping.

    ``OpenAIProvider`` has no ``from_config`` classmethod, so the factory
    forwards the config keys it understands: ``model``, ``api_key``,
    ``base_url`` and the ``ChatOpenAI`` options ``temperature``,
    ``max_tokens`` and ``stream``. Keys absent from ``config`` are omitted so
    constructor defaults (e.g. the ``OPENAI_API_KEY`` env fallback) apply.

    Args:
        config: Configuration mapping.

    Returns:
        A configured ``OpenAIProvider`` instance.
    """
    # Prefer the OpenAI-specific keys sourced from settings, falling back to the
    # bare keys for backward compatibility with older configs and tests.
    kwargs: dict[str, Any] = {}
    model = config.get("openai_model") or config.get("model")
    if model is not None:
        kwargs["model"] = model
    api_key = config.get("openai_api_key") or config.get("api_key")
    if api_key is not None:
        kwargs["api_key"] = api_key
    base_url = config.get("openai_base_url") or config.get("base_url")
    if base_url is not None:
        kwargs["base_url"] = base_url
    for key in ("temperature", "max_tokens", "stream"):
        if key in config:
            kwargs[key] = config[key]
    return OpenAIProvider(**kwargs)


#: Registered provider name -> factory callable.
_PROVIDER_FACTORIES: dict[str, ProviderFactory] = {
    "ollama": OllamaProvider.from_config,
    "openai": _openai_from_config,
}


def create_provider(config: dict[str, Any]) -> LLMProvider:
    """Create an ``LLMProvider`` selected by the config mapping.

    The ``provider`` key of ``config`` names the backend (e.g. ``"ollama"``
    or ``"openai"``). When the key is missing (or ``None``) it defaults to
    ``DEFAULT_PROVIDER`` so existing configs keep working. The remaining keys
    are passed to the selected provider's factory (``from_config`` classmethod
    or builder function).

    Args:
        config: Configuration mapping containing at least a ``provider`` key
            plus the options for that provider.

    Returns:
        A configured ``LLMProvider`` instance.

    Raises:
        ValueError: If the ``provider`` key names an unknown or unsupported
            provider.
    """
    provider_value = config.get("provider", DEFAULT_PROVIDER)
    if provider_value is None:
        provider_value = DEFAULT_PROVIDER
    provider_name = str(provider_value).strip().lower()

    factory = _PROVIDER_FACTORIES.get(provider_name)
    if factory is None:
        supported = ", ".join(sorted(_PROVIDER_FACTORIES))
        raise ValueError(
            f"Unknown LLM provider '{provider_name}'. "
            f"Supported providers: {supported}. "
            "Set the 'provider' key in your config to one of these values."
        )

    return factory(config)
