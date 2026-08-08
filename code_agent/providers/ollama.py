# providers/ollama.py
"""Ollama LLM provider for the OAP-inspired layer.

Wraps ``langchain_ollama.ChatOllama`` behind the provider-agnostic
``LLMProvider`` contract so business logic never references a concrete
model backend directly. Connection details (scheme/host/port/model/
temperature) are read from config, never hardcoded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_ollama import ChatOllama

from code_agent.providers.base import ProviderBase


class OllamaProvider(ProviderBase):
    """Ollama-backed LLM provider.

    Attributes:
        name: Stable provider identifier, ``"ollama"``.
        model: Ollama model name, e.g. ``"gpt-oss:20b-cloud"``.
        base_url: Ollama server base URL, e.g. ``"http://localhost:11434"``.
    """

    name: str = "ollama"

    def __init__(
            self,
            model: str,
            base_url: str | None = None,
            **kwargs: Any,
    ) -> None:
        """Initialize the Ollama provider.

        Args:
            model: Ollama model name to use for completions.
            base_url: Ollama server base URL. When ``None`` it is derived
                from the ``scheme``/``host``/``port`` keyword arguments
                (defaults ``http``/``localhost``/``11434``).
            **kwargs: Extra options forwarded to ``ChatOllama``, e.g.
                ``temperature``, ``max_tokens``, ``stream``.
        """
        scheme = kwargs.pop("scheme", "http")
        host = kwargs.pop("host", "localhost")
        port = kwargs.pop("port", 11434)
        if base_url is None:
            base_url = f"{scheme}://{host}:{port}"

        self.model = model
        self.base_url = base_url
        self._client = ChatOllama(model=model, base_url=base_url, **kwargs)

    def complete(self, messages: list[dict[str, Any]]) -> str:
        """Generate a completion for the given chat ``messages``.

        Args:
            messages: Chat history as a list of ``{"role": ..., "content": ...}``
                message dicts.

        Returns:
            The model's text completion.

        Raises:
            RuntimeError: If the Ollama backend fails to produce a response.
        """
        try:
            response = self._client.invoke(messages)
        except Exception as exc:
            raise RuntimeError(f"Ollama completion failed: {exc}") from exc
        return str(response.content)

    def bind_capabilities(self, caps: list[Any]) -> "OllamaProvider":
        # Ollama tool-binding is handled by the LangGraph layer; no-op here.
        return self

    @classmethod
    def from_config(
            cls, config: dict[str, Any] | None = None
    ) -> "OllamaProvider":
        """Build an ``OllamaProvider`` from a config mapping.

        Reads ``model``, ``temperature``, ``max_tokens``, ``stream`` and the
        ``ollama_*`` connection keys from ``config`` (or the default config
        file when ``config`` is ``None``).

        Args:
            config: Configuration mapping. When ``None`` the default
                ``code_agent/config/llm_config.json`` is loaded.

        Returns:
            A configured ``OllamaProvider`` instance.
        """
        if config is None:
            config = cls._load_default_config()

        # Prefer the explicit ``ollama_model`` key; fall back to the bare
        # ``model`` key for backward compatibility with older configs/tests.
        model = config.get("ollama_model") or config.get(
            "model", "gpt-oss:20b-cloud"
        )
        scheme = config.get("ollama_scheme", "http")
        host = config.get("ollama_host", "localhost")
        port = config.get("ollama_port", 11434)
        base_url = f"{scheme}://{host}:{port}"

        kwargs: dict[str, Any] = {}
        for key in ("temperature", "max_tokens", "stream"):
            if key in config:
                kwargs[key] = config[key]

        return cls(model=model, base_url=base_url, **kwargs)

    @staticmethod
    def _load_default_config() -> dict[str, Any]:
        """Load the default configuration.

        The typed application settings (sourced from ``.env`` / the environment)
        are the canonical default.  A legacy ``llm_config.json`` is used only as
        a fallback when the settings module is unavailable.
        """
        try:
            from code_agent.settings import get_settings

            return get_settings().model_dump()
        except Exception:
            path = (
                    Path(__file__).resolve().parent.parent
                    / "config"
                    / "llm_config.json"
            )
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
