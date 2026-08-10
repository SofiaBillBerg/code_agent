"""Library helpers for the *code_agent* package.

This module exposes the public functions :func:`load_config` and
:func:`create_llm` that the CLI, the agent runtime and the test-suite all
share.  The interactive chat loop lives in :mod:`code_agent.cli` instead,
so ``python -m code_agent`` routes there through :mod:`code_agent.__main__`.
"""  # noqa: E501

from __future__ import annotations

import json

from pathlib import Path
from typing import Any
from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic_settings import BaseSettings

from code_agent.settings import Settings, get_settings


__all__ = ["create_llm", "load_config"]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """Load configuration as a dictionary.

    When *config_path* is provided the JSON file at that location is loaded
    (legacy override).  When it is ``None`` the typed application settings are
    returned instead, so the ``.env`` file / environment remain the single
    source of truth.

    :param config_path: Optional path to a JSON configuration file.  If the
        path points to a directory, the function will look for
        ``llm_config.json`` inside.

    :returns: Parsed configuration dictionary.
    """  # noqa: E501
    if config_path is None:
        return get_settings().model_dump()

    cfg_file = Path(config_path)
    if cfg_file.is_dir():
        cfg_file /= "llm_config.json"

    if not cfg_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with cfg_file.open("r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# LLM construction
# ---------------------------------------------------------------------------


def create_llm(cfg: Settings | dict[str, Any]) -> BaseChatModel:
    """Create an LLM instance from config, with graceful fallback.

    The function supports an Ollama-style backend and falls back to a
    lightweight dummy model that returns an error message when the real
    LLM cannot be initialized.

    :param cfg: Either a :class:`~code_agent.settings.Settings` instance or
        a plain configuration dictionary (e.g. from :func:`load_config`).

    :returns: A :class:`~langchain_core.language_models.BaseChatModel`
        instance.
    """
    if isinstance(cfg, BaseSettings):
        cfg = cfg.model_dump()

    # ``ChatOllama`` is constructed lazily and never contacts the server, so
    # an invalid port would otherwise slip through and fail only at request
    # time.  Validate eagerly so bad configs route to the graceful
    # ``_FallbackLLM`` instead of hanging on a connection.
    port = cfg.get("ollama_port", 11434)
    try:
        int(port)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid ollama_port: {port!r}")

    try:
        from code_agent.providers.ollama import _chat_ollama_from_config

        return _chat_ollama_from_config(cfg)
    except Exception as exc:  # pragma: no cover - fallback path
        base_url = (
            f"{cfg.get('ollama_scheme', 'http')}://"
            f"{cfg.get('ollama_host', 'localhost')}:{port}"
        )

        class _FallbackLLM(BaseChatModel):
            """Graceful fallback when Ollama is unreachable."""

            _err: Exception
            _base_url: str

            def __init__(
                self,
                err: Exception,
                base_url: str,
                **kwargs: Any,
            ) -> None:
                super().__init__(**kwargs)
                self._err = err
                self._base_url = base_url

            def _generate(
                self,
                messages: list[BaseMessage],
                stop: list[str] | None = None,
                run_manager: Any = None,
                **kwargs: Any,
            ) -> ChatResult:
                content = json.dumps({
                    "error": "LLM unavailable",
                    "details": (
                        f"Failed to initialise ChatOllama. "
                        f"Error: {self._err}. "
                        f"Base URL: {self._base_url}."
                    ),
                })
                return ChatResult(
                    generations=[
                        ChatGeneration(message=AIMessage(content=content))
                    ]
                )

            @property
            def _llm_type(self) -> str:
                """Return type of llm.

                :return: Returns "fallback"
                """
                return "fallback"

            def bind_tools(
                self,
                tools: Sequence[Any],
                **kwargs: Any,
            ) -> Any:
                return self

        return _FallbackLLM(exc, base_url)
