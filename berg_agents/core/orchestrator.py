"""Core framework-agnostic orchestrator for the berg_agents package.

This module provides a host orchestrator that is the central control point
for `berg_agents`. It does not depend on LangGraph, LangChain, DeepAgents,
or any other LLM framework. It loads agents and workflows from *plugin*
directories supplied at construction time, defaulting to the active
project's standard `.opencode` location if a `bergagent.jsonc` opts into it.
"""

from __future__ import annotations

from collections.abc import Iterable
import json
from pathlib import Path
from typing import Any

class Orchestrator:
    """Discovers agents/workflows from plugin directories and routes tasks.

    Paths are *not* hardcoded. Plugins are passed in, typically from a
    configuration file (e.g. `bergagent.jsonc`). If no plugins are given,
    the orchestrator has zero external agents and the host software's own
    native Python agents (imported in `berg_agents.agents.codeagent` and
    elsewhere) remain the only authoritative agents.
    """

    def __init__(self, plugins: Iterable[Path] | None = None) -> None:
        self.plugins: list[Path] = [Path(p) for p in (plugins or [])]
        self.registry: dict[str, list[dict[str, Any]]] = {
            "agents": [],
            "workflows": [],
        }
        self._load_all_plugins()

    def _load_all_plugins(self) -> None:
        for plugin in self.plugins:
            registry_file = plugin / "registry.json"
            if not registry_file.exists():
                continue
            try:
                with Path(registry_file).open(encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            self.registry["agents"].extend(data.get("agents", []))
            self.registry["workflows"].extend(data.get("workflows", []))

    def route_to_agent(self, agent_name: str) -> dict[str, Any]:
        for agent in self.registry.get("agents", []):
            if agent.get("name") == agent_name:
                return agent
        raise KeyError(f"Agent {agent_name} not found in registered plugins")

    def execute_workflow(
        self, workflow_name: str, context: dict[str, Any]
    ) -> Any:
        # Framework-agnostic execution hook. Concrete frameworks (LangGraph,
        # native Python, etc.) provide their own executors and call into
        # this orchestrator to discover workflows.
        return {
            "workflow": workflow_name,
            "context": context,
            "status": "dispatched",
        }
