"""DeepAgents profile routing.

This package reads project settings and registers DeepAgents harness profiles
so agent behavior can be tuned per model without manual wiring.
"""

from __future__ import annotations

from code_agent.profiles.router import register_profiles_from_settings

__all__ = ["register_profiles_from_settings"]
