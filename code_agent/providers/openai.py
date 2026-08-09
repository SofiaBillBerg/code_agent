"""OpenAI LLM provider for the OAP-inspired layer.

Wraps ``langchain_openai.ChatOpenAI`` behind the provider-agnostic
``LLMProvider`` contract so business logic never references a concrete
model backend directly. The model name, API key and base URL are read
from constructor arguments (the API key falls back to the
``OPENAI_API_KEY`` environment variable), never hardcoded.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from typing import Any

from code_agent.providers.base import ProviderBase
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

@dataclass
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
        api_key: SecretStr | Callable[[], str] | None = None,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the OpenAI provider.

        :param model: OpenAI model name to use for completions.
        :param api_key: OpenAI API key. When ``None`` it is read from the  ``OPENAI_API_KEY`` environment variable.
        :param base_url: Optional base URL for the API, e.g. when using a proxy or service emulator.
        :param **kwargs: Extra options forwarded to ``ChatOpenAI``, e.g. ``temperature``, ``max_tokens``, ``stream``.
        :return: The initialized provider.
        """
        if api_key is None:
            api_key = SecretStr(os.environ["OPENAI_API_KEY"])
        elif isinstance(api_key, str):
            api_key = SecretStr(api_key)

        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        # ChatOpenAI expects a plain string (or lazy callable), not a SecretStr.
        client_api_key = (
            api_key.get_secret_value()
            if isinstance(api_key, SecretStr)
            else api_key
        )
        self._client = ChatOpenAI(
            model=model, api_key=client_api_key, base_url=base_url, **kwargs
        )

    def complete(self, messages: list[dict[str, Any]]) -> str:
        """Generate a completion for the given chat ``messages``.

        :param messages: Chat history as a list of ``{"role": ..., "content": ...}`` message dicts.
        :return: The model's text completion.
        :raises RuntimeError: If the OpenAI backend fails to produce a response.
        """
        try:
            response = self._client.invoke(messages)
        except Exception as exc:
            raise RuntimeError(f"OpenAI completion failed: {exc}") from exc
        content = response.content
        if isinstance(content, list):
            content = "\n".join(str(part) for part in content)
        return str(content)

    def bind_capabilities(self, caps: list[Any]) -> OpenAIProvider:
        """Bind capabilities to the OpenAI provider.

        :param caps: List of capabilities to bind.
        :return: The provider with bound capabilities.
        """
        # OpenAI tool-binding is handled by the LangGraph layer; no-op here.
        return self
