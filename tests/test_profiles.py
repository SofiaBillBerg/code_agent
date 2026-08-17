"""Tests for the DeepAgents profile router."""

from __future__ import annotations

import json

from typing import Any

import pytest

from deepagents import HarnessProfile

from code_agent.config.settings import Settings
from code_agent.profiles import register_profiles_from_settings


def test_register_profiles_from_settings_noop_when_missing(
    monkeypatch: Any,
) -> None:
    """No profiles should be registered when settings.profiles is missing.

    This should not raise an exception.

    :param monkeypatch: The pytest-mock monkeypatch fixture.
    :raises AssertionError: If any profiles were registered.
    """
    settings = Settings(profiles=None)
    monkeypatch.setattr(
        "code_agent.profiles.router.get_settings",
        lambda: settings,
    )
    register_profiles_from_settings()


def test_register_profiles_from_settings_json(monkeypatch: Any) -> None:
    """Profiles declared as JSON should be registered.


    :param monkeypatch: The pytest-mock monkeypatch fixture.

    :raises AssertionError: If the expected profile was not registered.

    """
    captured: dict[str, HarnessProfile] = {}

    def fake_register(key: str, profile: HarnessProfile) -> None:
        """Capture the profile.

        :param key: The profile key.
        :param profile: The profile.

        """
        captured[key] = profile

    monkeypatch.setattr(
        "code_agent.profiles.router.get_settings",
        lambda: Settings(
            profiles=json.dumps({
                "ollama:gpt-oss:20b": {
                    "base_system_prompt": "You are a test agent.",
                    "system_prompt_suffix": "Be brief.",
                }
            })
        ),
    )
    monkeypatch.setattr(
        "code_agent.profiles.router.register_harness_profile",
        fake_register,
    )

    register_profiles_from_settings()

    assert "ollama:gpt-oss:20b" in captured
    profile = captured["ollama:gpt-oss:20b"]
    assert profile.base_system_prompt == "You are a test agent."
    assert profile.system_prompt_suffix == "Be brief."


def test_register_profiles_from_settings_dict(monkeypatch: Any) -> None:
    """Profiles declared as a dict should be registered.


    :param monkeypatch: The pytest-mock monkeypatch fixture.

    :raises AssertionError: If the expected profile was not registered.

    """
    captured: dict[str, HarnessProfile] = {}

    def fake_register(key: str, profile: HarnessProfile) -> None:
        """Capture the profile.

        :param key: The profile key.
        :param profile: The profile.

        """
        captured[key] = profile

    monkeypatch.setattr(
        "code_agent.profiles.router.get_settings",
        lambda: Settings(
            profiles={
                "openai:gpt-4o": {
                    "excluded_tools": ["execute"],
                }
            }
        ),
    )
    monkeypatch.setattr(
        "code_agent.profiles.router.register_harness_profile",
        fake_register,
    )

    register_profiles_from_settings()

    assert "openai:gpt-4o" in captured
    assert "execute" in captured["openai:gpt-4o"].excluded_tools


def test_register_profiles_from_settings_invalid_json(monkeypatch: Any) -> None:
    """Invalid JSON should raise ``ValueError``.

    :param monkeypatch: The pytest-mock monkeypatch fixture.

    :raises AssertionError: If the expected profile was not registered.

    :raises ValueError: If the JSON is invalid.

    """
    monkeypatch.setattr(
        "code_agent.profiles.router.get_settings",
        lambda: Settings(profiles="not-json"),
    )

    with pytest.raises(ValueError, match="not valid JSON"):
        register_profiles_from_settings()


def test_register_profiles_from_settings_invalid_type(monkeypatch: Any) -> None:
    """Non-dict profile values should raise ``TypeError`` during coercion.

    :param monkeypatch: The pytest-mock monkeypatch fixture.

    :raises AssertionError: If the expected profile was not registered.

    :raises TypeError: If the profile value is not a dict or HarnessProfile.

    """
    from code_agent.profiles.router import _coerce_profile_entry

    with pytest.raises(TypeError, match="must be a dict or HarnessProfile"):
        _coerce_profile_entry(["bad"])


def test_register_profiles_from_settings_none_entry(monkeypatch: Any) -> None:
    """None entries in the profiles mapping should be skipped.

    :param monkeypatch: The pytest-mock monkeypatch fixture.

    :raises AssertionError: If the expected profile was not registered.

    """
    captured: dict[str, HarnessProfile] = {}

    def fake_register(key: str, profile: HarnessProfile) -> None:
        """Capture the profile.

        :param key: The profile key.
        :param profile: The profile.

        """
        captured[key] = profile

    monkeypatch.setattr(
        "code_agent.profiles.router.get_settings",
        lambda: Settings(
            profiles=json.dumps({
                "ollama:gpt-oss:20b": None,
                "openai:gpt-4o": {"system_prompt_suffix": "hi"},
            })
        ),
    )
    monkeypatch.setattr(
        "code_agent.profiles.router.register_harness_profile",
        fake_register,
    )

    register_profiles_from_settings()

    assert "ollama:gpt-oss:20b" not in captured
    assert "openai:gpt-4o" in captured
