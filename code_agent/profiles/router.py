"""Profile routing for DeepAgents harness profiles.

This module bridges the project's configuration into DeepAgents'
``register_harness_profile`` mechanism.  Instead of requiring callers to
manually construct and register ``HarnessProfile`` objects, it reads declared
profiles and registers them under their ``provider:model`` keys from two
sources:

* :func:`register_profiles_from_settings` - profiles declared in
  :class:`~code_agent.config.settings.Settings` (e.g. the ``CODE_AGENT_PROFILES``
  ``.env`` entry), and
* :func:`register_profiles_from_config_file` - profiles declared in the
  user-editable config file :data:`DEFAULT_PROFILES_CONFIG`
  (``/home/nvidia/code_agent/config/profiles.yaml``), which
  :func:`code_agent.agents.deepagents_agent.build_deep_agent` calls by default.

The router is additive: it only registers profiles that are explicitly
declared, so it never surprises existing behavior with unexpected defaults.

The router is also stateful: every registration records its source in the
module-level :data:`_registered` registry (``"settings"`` or
``"config-file"``), and :func:`resolve_profile` returns the *effective*
merged profile for a key (exact-model profile merged over provider-level
profile, matching DeepAgents' own resolution order).
"""

from __future__ import annotations

import logging

from pathlib import Path
from typing import Any

import yaml

from deepagents import HarnessProfile, register_harness_profile

from code_agent.config.settings import get_settings


log = logging.getLogger(__name__)

#: Default location of the user-editable profiles config (repo-root config dir).
DEFAULT_PROFILES_CONFIG = Path("/home/nvidia/code_agent/config/profiles.yaml")

#: Stateful registry of profile keys this router has registered, mapping
#: ``provider:model`` key -> source label (``"settings"`` or ``"config-file"``).
#: Used by :func:`resolve_profile` to report where a profile came from.
_registered: dict[str, str] = {}


def _get_effective_profile(key: str) -> HarnessProfile | None:
    """Return the effective (merged) profile for *key*.

    Delegates to DeepAgents' internal resolver so the result matches exactly
    what the harness will apply: an exact-model profile merged over a
    provider-level profile when both exist.  Falls back to a plain registry
    lookup if the private API moves.

    :param key: ``provider:model`` profile key.
    :return: The effective :class:`HarnessProfile`, or ``None``.
    """
    try:
        from deepagents.profiles.harness.harness_profiles import (
            _get_harness_profile,  # ruff: ignore[import-private-name] - private API, intentional
        )

        return _get_harness_profile(key)
    except (ImportError, AttributeError):
        from deepagents.profiles.harness.harness_profiles import (
            _HARNESS_PROFILES,  # ruff: ignore[import-private-name] - private API, intentional
        )

        return _HARNESS_PROFILES.get(key)


def resolve_profile(key: str) -> HarnessProfile | None:
    """Resolve the effective harness profile for a ``provider:model`` key.

    Returns the merged profile the harness would apply for *key* (exact-model
    profile merged over provider-level profile), or ``None`` when nothing was
    registered.  Logs the source (``"settings"`` / ``"config-file"``) when the
    key was registered by this router.

    :param key: ``provider:model`` profile key.
    :return: The effective :class:`HarnessProfile`, or ``None``.
    """
    profile = _get_effective_profile(key)
    source = _registered.get(key)
    if profile is not None:
        log.debug(
            "Resolved harness profile for %r%s.",
            key,
            f" (registered via {source})" if source else "",
        )
    return profile


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
        coerced = dict(raw)
        # HarnessProfile expects frozen sets; YAML/JSON give lists.  Without
        # this, merging a config profile with a built-in one fails with
        # "frozenset | list" during profile resolution.
        if "excluded_tools" in coerced and not isinstance(
            coerced["excluded_tools"], frozenset
        ):
            coerced["excluded_tools"] = frozenset(
                coerced["excluded_tools"] or []
            )
        if "excluded_middleware" in coerced and not isinstance(
            coerced["excluded_middleware"], frozenset
        ):
            coerced["excluded_middleware"] = frozenset(
                coerced["excluded_middleware"] or []
            )
        return HarnessProfile(**coerced)
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
        _registered[str(profile_key)] = "settings"


def load_profiles_from_config_file(
    path: str | Path = DEFAULT_PROFILES_CONFIG,
) -> dict[str, HarnessProfile]:
    """Read harness profiles from a YAML (or JSON) config file.

    Each top-level key is a ``provider:model`` profile key; its value is a
    mapping of :class:`HarnessProfile` fields.  ``None``/empty values are
    skipped.  JSON files are also accepted (JSON is a YAML subset).

    :param path: Path to the profiles' config.  Defaults to
        :data:`DEFAULT_PROFILES_CONFIG`.
    :return: Mapping of profile key -> :class:`HarnessProfile`.  Empty when the
        file does not exist.
    """
    path = Path(path)
    if not path.exists():
        log.info(
            "Profiles config '%s' not found; no profiles registered.", path
        )
        return {}

    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise TypeError(
            f"Profiles config '{path}' must be a mapping, got "
            f"{type(parsed).__name__}"
        )

    profiles: dict[str, HarnessProfile] = {}
    for profile_key, entry in parsed.items():
        profile = _coerce_profile_entry(entry)
        if profile is None:
            continue
        profiles[str(profile_key)] = profile
    log.info("Loaded %d harness profile(s) from '%s'", len(profiles), path)
    return profiles


def register_profiles_from_config_file(
    path: str | Path = DEFAULT_PROFILES_CONFIG,
) -> None:
    """Register DeepAgents harness profiles declared in a config file.

    Reads the config at *path* (default :data:`DEFAULT_PROFILES_CONFIG`) and
    registers every declared profile under its ``provider:model`` key via
    :func:`deepagents.register_harness_profile`.  A missing file is not an
    error - it simply registers nothing.

    :param path: Path to the profiles config file.
    :return: None
    """
    for profile_key, profile in load_profiles_from_config_file(path).items():
        register_harness_profile(profile_key, profile)
        _registered[profile_key] = "config-file"
