"""Profile routing for DeepAgents harness profiles.

This module bridges the project's :class:`~code_agent.config.settings.Settings`
into DeepAgents' ``register_harness_profile`` mechanism.  Instead of
requiring callers to manually construct and register ``HarnessProfile``
objects, :func:`register_profiles_from_settings` reads the active config
and registers any declared profiles under their ``provider:model`` keys.

The router is additive: it only registers profiles that are explicitly
declared in settings, so it never surprises existing behavior with
unexpected defaults.
"""

from __future__ import annotations

from typing import Any

from deepagents import HarnessProfile, register_harness_profile

from code_agent.config.settings import get_settings


def _coerce_profile_entry(raw: Any) -> HarnessProfile | None:
    """Convert a raw settings entry into a :class:`HarnessProfile`.

    Accepts either a ``HarnessProfile`` instance, a dict of keyword
    arguments, or ``None``.  Returns ``None`` when the entry is ``None``
    or empty.

    :param raw: Raw profile entry from settings.
    :return: A configured profile, or ``None``.
    """
    if raw is None:
        return None
    if isinstance(raw, HarnessProfile):
        return raw
    if isinstance(raw, dict):
        if not raw:
            return None
        return HarnessProfile(**raw)
    raise TypeError(
        f"Profile entry must be a dict or HarnessProfile, got {type(raw).__name__}"
    )


def register_profiles_from_settings() -> None:
    """Register DeepAgents harness profiles declared in settings.

    Reads ``settings.profiles``, which may be:

    * a JSON string representing a mapping of ``profile_key -> profile_kwargs``,
    * a dict mapping ``profile_key -> profile_kwargs``, or
    * ``None`` / missing, in which case no profiles are registered.

    Example ``.env`` entry::

        CODE_AGENT_PROFILES = (
            '{"ollama:gpt-oss:20b": {"system_prompt_suffix": "Be concise."}}'
        )

    :return: None
    """
    import json

    settings = get_settings()
    raw = getattr(settings, "profiles", None)
    if raw is None:
        return

    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"CODE_AGENT_PROFILES is not valid JSON: {exc}"
            ) from exc
    else:
        parsed = raw

    if not isinstance(parsed, dict):
        raise TypeError(
            f"CODE_AGENT_PROFILES must be a JSON object, got {type(parsed).__name__}"
        )

    for profile_key, entry in parsed.items():
        profile = _coerce_profile_entry(entry)
        if profile is None:
            continue
        register_harness_profile(str(profile_key), profile)
