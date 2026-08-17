"""Library helpers for the *code_agent* package.

This module exposes the public functions :func:`load_config` and
:func:`create_llm` that the CLI, the agent runtime and the test-suite all
share.  The interactive chat loop lives in :mod:`code_agent.cli` instead,
so ``python -m code_agent`` routes there through :mod:`code_agent.__main__`.
"""

from __future__ import annotations

import json

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from langchain.chat_models import BaseChatModel
from langchain.messages import AIMessage
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic_settings import BaseSettings

from code_agent.config.jsonc import loads as jsonc_loads
from code_agent.config.settings import Settings, get_settings


__all__ = ["create_llm", "load_config"]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """Load configuration as a dictionary.

    When *config_path* is provided the JSON or YAML file at that location is
    loaded (override).  When it is ``None`` the typed application
    settings are returned instead, so the ``.env`` file / environment remain
    the single source of truth.

    Supported extensions are ``.json``, ``.yaml`` and ``.yml``; the loader
    is chosen from the file suffix.  A ``FileNotFoundError`` is raised when
    the target does not exist, and a ``ValueError`` for unsupported
    extensions.

    :param config_path: Optional path to a JSON/YAML configuration file.  If
        the path points to a directory, the function will look for ``codeagent.jsonc``,
        ``codeagent.json``, ``codeagent.yml``, ``codeagent.yaml``.
        inside, in that order.

    :returns: Parsed configuration dictionary.
    """  # ruff: noqa: E501
    if config_path is None:
        return get_settings().model_dump()

    cfg_file = Path(config_path)
    if cfg_file.is_dir():
        for candidate in (
            "codeagent.jsonc",
            "codeagent.json",
            "codeagent.yml",
            "codeagent.yaml",
        ):
            probe = cfg_file / candidate
            if probe.exists():
                cfg_file = probe
                break
        else:
            raise FileNotFoundError(
                f"No codeagent.jsonc/.json/yaml/yml found in directory: {config_path}"
            )

    if not cfg_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    suffix = cfg_file.suffix.lower()
    with cfg_file.open("r", encoding="utf-8") as f:
        if suffix == ".jsonc":
            return jsonc_loads(f.read())
        if suffix == ".json":
            return json.load(f)
        if suffix in {".yaml", ".yml"}:
            return yaml.safe_load(f)
        raise ValueError(
            f"Unsupported config file extension: {suffix!r} "
            f"(expected .jsonc, .json, .yaml or .yml)"
        )


# ---------------------------------------------------------------------------
# LLM construction
# ---------------------------------------------------------------------------


def create_llm(cfg: Settings | dict[str, Any]) -> BaseChatModel:
    """Create an LLM instance from config, with graceful fallback.

    The function supports an Ollama-style backend and falls back to a
    lightweight dummy model that returns an error message when the real
    LLM cannot be initialized.

    :param cfg: Either a :class:`~code_agent.config.settings.Settings` instance or
        a plain configuration dictionary (e.g. from :func:`load_config`).

    :returns: A :class:`~langchain.chat_models.BaseChatModel`
        instance.
    """
    if isinstance(cfg, BaseSettings):
        cfg = cfg.model_dump()

    # ``ChatOllama`` is constructed lazily and never contacts the server, so
    # an invalid port would otherwise slip through and fail only at request
    # time.  Validate eagerly so bad configs route to the graceful
    # ``_FallbackLLM`` instead of hanging on a connection.
    try:
        from code_agent.providers.ollama import _chat_ollama_from_config

        return _chat_ollama_from_config(cfg)
    except Exception as exc:  # pragma: no cover - fallback path
        port = cfg.get("ollama_port", 11434)
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
                """Initialise the fallback LLM.

                :param err: The exception that caused the fallback.
                :param base_url: The base URL of the Ollama server.
                :param kwargs: Additional keyword arguments.
                :return: None
                """
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
                """Generate a response to the given messages.

                :param messages: The messages to generate a response to.
                :param stop: A list of strings to stop generation on.
                :param run_manager: The run manager.
                :param kwargs: Additional keyword arguments.
                :return: A :class:`~langchain_core.outputs.ChatResult`
                    instance.
                """
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
                """Access the type of llm.

                :return: Returns "fallback"
                """
                return "fallback"

            def bind_tools(
                self,
                tools: Sequence[Any],
                **kwargs: Any,
            ) -> Any:
                """Bind tools to the LLM.

                :param tools: The tools to bind.
                :param kwargs: Additional keyword arguments.
                :return: The LLM with the tools bound.
                """
                return self

        return _FallbackLLM(exc, base_url)
