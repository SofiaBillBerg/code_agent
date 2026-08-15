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

from code_agent.providers.base import ProviderBase
from code_agent.settings import as_config_dict
from langchain_ollama import ChatOllama

#: Shared helper so the provider layer and ``main.create_llm`` build
#: ``ChatOllama`` from the same config keys.  Keeping this in one place
#: means key renames or constructor signature changes only need updating
#: once.
def _chat_ollama_from_config(config: dict[str, Any]) -> ChatOllama:
    """Construct a ``ChatOllama`` from a config mapping.

    Reads ``ollama_model`` / ``model``, ``ollama_scheme``, ``ollama_host``,
    ``ollama_port`` and the generation keys ``temperature``, ``max_tokens``,
    ``stream``.  The canonical ``codeagent.jsonc``,
        ``codeagent.json``, ``codeagent.yml`` or ``codeagent.yaml`` keys (``ollama_*``) take
    precedence over the bare ``model`` / ``temperature`` etc. keys.

    :param config: Configuration mapping, typically from :func:`code_agent.settings.as_config_dict`.
    :return: A configured ``ChatOllama`` instance.
    """
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
    return ChatOllama(model=model, base_url=base_url, **kwargs)


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

        :param messages: Chat history as a list of ``{"role": ..., "content": ...}`` message dicts.
        :return: The model's text completion.
        :raises RuntimeError: If the Ollama backend fails to produce a response.
        """
        try:
            response = self._client.invoke(messages)
        except Exception as exc:
            raise RuntimeError(f"Ollama completion failed: {exc}") from exc
        return str(response.content)

    def bind_capabilities(self, caps: list[Any]) -> OllamaProvider:
        """Bind capabilities to the Ollama provider.

        :param caps: List of capabilities to bind.
        :return: The provider with bound capabilities.
        """
        # Ollama tool-binding is handled by the LangGraph layer; no-op here.
        return self

    @staticmethod
    def _load_default_config() -> dict[str, Any] | None:
        """Load the default configuration.

        The typed application settings (sourced from ``.env`` / the environment)
        are the canonical default.  Also support ``codeagent.jsonc``,
        ``codeagent.json``, ``codeagent.yml`` and``codeagent.yaml`` is used only as
        a fallback when the settings module is unavailable.

        :return: The default configuration mapping.
        """
        try:
            return as_config_dict()
        except Exception:
            config_file_candidates = [
                "codeagent.jsonc",
                "codeagent.json",
                "codeagent.yml",
                "codeagent.yaml",
            ]
            for filename in config_file_candidates:
                path = Path(__file__).resolve().parent.parent / "config" / filename
                if path.exists():
                    with path.open("r", encoding="utf-8") as f:
                        suffix = path.suffix.lower()
                        if suffix == ".jsonc":
                            import json5

                            return json5.load(f)
                        if suffix == ".json":
                            return json.load(f)
                        if suffix in {".yaml", ".yml"}:
                            import yaml

                            return yaml.safe_load(f)
                        raise ValueError(
                            f"Unsupported config file extension: {suffix!r} "
                            f"(expected .jsonc, .json, .yaml or .yml)"
                        )

    @classmethod
    def from_config(
        cls, config: dict[str, Any] | None = None
    ) -> OllamaProvider:
        """Build an ``OllamaProvider`` from a config mapping.

        Reads ``model``, ``temperature``, ``max_tokens``, ``stream`` and the
        ``ollama_*`` connection keys from ``config`` (or the default config
        file when ``config`` is ``None``).

        :param config: Configuration mapping. When ``None`` the typed application settings are used, falling back to ``codeagent.jsonc``,
        ``codeagent.json``, ``codeagent.yml``, ``codeagent.yaml`` if settings are unavailable.
        :return: A configured ``OllamaProvider`` instance.
        """
        if config is None:
            config = cls._load_default_config() or {}

        client = _chat_ollama_from_config(config)
        return cls(
            model=client.model,
            base_url=client.base_url,
            temperature=config.get("temperature", 0.7),
            max_tokens=config.get("max_tokens", 6000),
            stream=config.get("stream", True),
        )
