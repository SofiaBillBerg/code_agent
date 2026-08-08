# providers/openai.py
"""OpenAI LLM provider for the OAP-inspired layer.

Wraps ``langchain_openai.ChatOpenAI`` behind the provider-agnostic
``LLMProvider`` contract so business logic never references a concrete
model backend directly. The model name, API key and base URL are read
from constructor arguments (the API key falls back to the
``OPENAI_API_KEY`` environment variable), never hardcoded.
"""

from __future__ import annotations

import os
from typing import Any

from langchain_openai import ChatOpenAI

from code_agent.providers.base import ProviderBase


class OpenAIProvider(ProviderBase):
    """OpenAI-backed LLM provider.

    Attributes:
        name: Stable provider identifier, ``"openai"``.
        model: OpenAI model name, e.g. ``"gpt-4o"``.
        api_key: OpenAI API key, or ``None`` when read from ``OPENAI_API_KEY``.
        base_url: Optional base URL for the API, e.g. for proxies or
            emulators such as ``"https://api.openai.com/v1"``.
    """

    name: str = "openai"

    def __init__(
            self,
            model: str,
            api_key: str | None = None,
            base_url: str | None = None,
            **kwargs: Any,
    ) -> None:
        """Initialize the OpenAI provider.

        Args:
            model: OpenAI model name to use for completions.
            api_key: OpenAI API key. When ``None`` it is read from the
                ``OPENAI_API_KEY`` environment variable.
            base_url: Optional base URL for the API, e.g. when using a
                proxy or service emulator.
            **kwargs: Extra options forwarded to ``ChatOpenAI``, e.g.
                ``temperature``, ``max_tokens``, ``stream``.
        """
        if api_key is None:
            api_key = os.environ.get("OPENAI_API_KEY")

        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self._client = ChatOpenAI(
            model=model, api_key=api_key, base_url=base_url, **kwargs
        )

    def complete(self, messages: list[dict[str, Any]]) -> str:
        """Generate a completion for the given chat ``messages``.

        Args:
            messages: Chat history as a list of ``{"role": ..., "content": ...}``
                message dicts.

        Returns:
            The model's text completion.

        Raises:
            RuntimeError: If the OpenAI backend fails to produce a response.
        """
        try:
            response = self._client.invoke(messages)
        except Exception as exc:
            raise RuntimeError(f"OpenAI completion failed: {exc}") from exc
        return response.content

    def bind_capabilities(self, caps: list[Any]) -> "OpenAIProvider":
        # OpenAI tool-binding is handled by the LangGraph layer; no-op here.
        return self
