# providers/base.py
"""Provider-agnostic LLM contract for the OAP-inspired layer.

Defines ``LLMProvider`` (the structural protocol every concrete provider —
ollama, openai, ... — must satisfy) and ``ProviderBase`` (a convenient ABC
that implements the protocol's ``bind_capabilities`` default). No concrete
model backend is referenced here; providers are selected by config via
``providers/factory.py``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Structural contract every LLM provider must satisfy.

    Attributes:
        name: Stable provider identifier, e.g. ``"ollama"`` or ``"openai"``.
    """

    name: str

    def complete(self, messages: list[dict[str, Any]]) -> str:
        """Generate a completion for the given chat ``messages``.

        Args:
            messages: Chat history as a list of ``{"role": ..., "content": ...}``
                message dicts.

        Returns:
            The model's text completion.
        """
        ...

    def bind_capabilities(self, caps: list[Any]) -> "LLMProvider":
        """Return a provider bound to the given capabilities.

        Providers that need tool-binding (e.g. function calling) may return a
        new provider instance configured with ``caps``; others return ``self``.

        Args:
            caps: Capabilities available to the provider.

        Returns:
            A provider instance bound to ``caps``.
        """
        ...


class ProviderBase(ABC):
    """Base class for LLM providers (ollama, openai, ...).

    Subclasses must set ``name`` and implement ``complete``. ``bind_capabilities``
    defaults to a no-op that returns ``self``; providers that require tool-binding
    override it.
    """

    name: str = "base"

    @abstractmethod
    def complete(self, messages: list[dict[str, Any]]) -> str:
        """Generate a completion for the given chat ``messages``.

        Args:
            messages: Chat history as a list of ``{"role": ..., "content": ...}``
                message dicts.

        Returns:
            The model's text completion.
        """
        ...

    def bind_capabilities(self, caps: list[Any]) -> "ProviderBase":
        # Default: providers ignore capabilities unless they need tool-binding.
        return self
