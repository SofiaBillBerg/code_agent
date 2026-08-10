"""Typed application configuration loaded from environment / ``.env``.

All runtime configuration for the agent is centralised in a single
:class:`Settings` model built on ``pydantic_settings.BaseSettings``. Values are
sourced, in increasing precedence, from:

1. the process environment variables, and
2. a ``.env`` file at the project root (``CODE_AGENT_OLLAMA_PORT``,
   ``CODE_AGENT_OPENAI_API_KEY`` ...).

Sensible defaults live on the model so the application runs with zero
configuration, while every value can be overridden per environment without
touching code. Secrets (e.g. ``CODE_AGENT_OPENAI_API_KEY``) are never
hardcoded - they are read from the environment / ``.env`` only, satisfying
the project's security requirement that provider credentials come from
config, not source.

Field names map to upper-case environment variables with the ``CODE_AGENT_``
prefix (``ollama_port`` -> ``CODE_AGENT_OLLAMA_PORT``). The provider layer
reads the same values from the ``model_dump()`` dict using the ``ollama_*`` /
``openai_*`` key convention, so this module is the single source of truth.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


#: Project root (parent of the ``code_agent`` package), where ``.env`` lives.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: Default system prompt used when none is supplied via config / ``.env``.
DEFAULT_SYSTEM_PROMPT = """You are an elite software architect and data science expert with deep knowledge of Python, R, and modern development practices.

CAPABILITIES:
- Design and implement complete, production-ready systems
- Perform sophisticated code analysis and refactoring
- Create comprehensive documentation and explanations
- Solve complex algorithmic and architectural challenges
- Optimize performance and maintainability
- Apply advanced design patterns and best practices

APPROACH:
- Provide thorough, well-reasoned solutions
- Consider edge cases and potential issues
- Write clean, maintainable, well-documented code
- Explain complex concepts clearly and completely
- Suggest improvements and alternatives
- Think holistically about system design

STANDARDS:
- Production-quality code with proper error handling
- Comprehensive docstrings and comments
- Type hints and validation where appropriate
- Following language-specific conventions (PEP 8, tidyverse style)
- Security and performance considerations
- Scalability and maintainability focus

When using tools, use them strategically to gather information before providing complete solutions.
Never give minimal or toy examples - always provide professional, complete implementations."""


class Settings(BaseSettings):
    """Application settings sourced from the environment and ``.env``.

    Every field has a safe default so the agent runs out of the box; override
    any value with an environment variable or a ``.env`` entry at the project
    root. Unknown environment variables are ignored (``extra="ignore"``).
    """

    model_config = SettingsConfigDict(
        env_prefix="CODE_AGENT_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Provider selection -------------------------------------------------
    provider: str = "ollama"

    # --- Ollama connection --------------------------------------------------
    ollama_scheme: str = "http"
    ollama_host: str = "localhost"
    ollama_port: int = 11434
    ollama_model: str = "gpt-oss:20b"

    # --- OpenAI (optional; falls back to the OPENAI_API_KEY env var) --------
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"
    openai_base_url: str | None = None

    # --- Sampling / generation ---------------------------------------------
    temperature: float = 0.7
    max_tokens: int = 6000
    stream: bool = True

    # --- Application behavior ---------------------------------------------
    auth_token: str | None = None
    root_dir: str = "."
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    verbose: bool = True
    log_level: str = "INFO"
    max_iterations: int = 50
    max_execution_time: int = 5000

    @model_validator(mode="after")
    def _split_combined_ollama_host(self) -> Settings:
        """Accept Ollama's combined ``host:port`` form in ``ollama_host``.

        Ollama's own ``OLLAMA_HOST`` uses ``host:port``.  If ``ollama_host``
        carries a trailing port, split it off so the connection URL is built
        correctly instead of duplicating the port.

        :return: The validated settings.
        """
        host = self.ollama_host
        if host and ":" in host:
            head, _, port = host.rpartition(":")
            if port.isdigit():
                self.ollama_host = head
                self.ollama_port = int(port)
        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance.

    The result is memoised so the ``.env`` file and environment are read only
    once per process.

    :return: The validated settings.
    """
    return Settings()


def as_config_dict() -> dict[str, Any]:
    """Return the settings as a plain dict for the provider/config layer.

    :return: The settings as a plain dict.
    """
    return get_settings().model_dump()
