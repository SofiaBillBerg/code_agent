"""BergAgents — main application class.

This is the primary entry point for the BergAgents system. It wires together:
- Orchestrator (core engine)
- ModelRouter (complexity → model selection)
- OrchestratorServer (HTTP API)
- FastAPI web server
- CLI (Rich terminal UI)

Usage:
    # As a library
    app = BergAgentsApp.create()
    app.serve()  # Start web server

    # CLI
    # $ berg-agents serve
    # $ berg-agents orchestrate "refactor auth module"
"""

from __future__ import annotations

import logging
from typing import Any

from berg_agents.core.model_router import ModelRouter
from berg_agents.core.orchestrator import Orchestrator
from berg_agents.ui.orchestrator_server import OrchestratorServer

logger = logging.getLogger(__name__)


class BergAgentsApp:
    """Main BergAgents application.

    Wires together the orchestrator, model router, and web server.
    Provides both programmatic and CLI interfaces.
    """

    def __init__(
        self,
        *,
        router: ModelRouter | None = None,
        orchestrator: Orchestrator | None = None,
        enable_learning: bool = True,
    ) -> None:
        """Initialize the BergAgents app.

        Args:
            router: Optional custom ModelRouter instance.
            orchestrator: Optional custom Orchestrator instance.
            enable_learning: Whether to enable the learning gate.
        """
        self.router = router or ModelRouter()
        self.orchestrator = orchestrator or Orchestrator(
            router=self.router,
            enable_learning=enable_learning,
        )
        self.server = OrchestratorServer()
        # Share the orchestrator with the server
        self.server.orchestrator = self.orchestrator

    @classmethod
    def create(cls, config: dict[str, Any] | None = None) -> BergAgentsApp:
        """Factory: create and configure the app.

        Args:
            config: Optional configuration dict. Keys:
                - enable_learning: bool (default True)
                - complexity_rules: dict for ModelRouter
                - tier_config: dict for ModelRouter

        Returns:
            Configured BergAgentsApp instance.
        """
        enable_learning = True
        router_kwargs = {}

        if config:
            enable_learning = config.get("enable_learning", enable_learning)
            if "complexity_rules" in config:
                router_kwargs["complexity_rules"] = config["complexity_rules"]
            if "tier_config" in config:
                router_kwargs["tier_config"] = config["tier_config"]

        router = ModelRouter(**router_kwargs) if router_kwargs else None
        return cls(router=router, enable_learning=enable_learning)

    def serve(self, host: str = "0.0.0.0", port: int = 8001) -> None:
        """Start the FastAPI web server.

        Args:
            host: Host to bind to.
            port: Port to listen on.
        """
        import uvicorn

        from berg_agents.ui.web import app as fastapi_app

        logger.info("Starting BergAgents server on %s:%d", host, port)
        uvicorn.run(fastapi_app, host=host, port=port)

    def execute(
        self, description: str, task_type: str = "generic"
    ) -> dict[str, Any]:
        """Execute a task through the orchestrator.

        Args:
            description: Task description.
            task_type: Type of task.

        Returns:
            Execution result dict.
        """
        task = {"description": description, "task_type": task_type}
        return self.orchestrator.execute_task(task)

    def list_agents(self) -> list[dict[str, Any]]:
        """List all registered agents.

        Returns:
            List of agent info dicts.
        """
        return self.orchestrator.get_agent_info()

    def get_learning_stats(self) -> dict[str, Any]:
        """Get learning/outcome statistics.

        Returns:
            Dict with outcome stats.
        """
        return self.orchestrator.get_learning_stats()

    def register_agent(self, name: str, agent: Any) -> None:
        """Register a custom agent.

        Args:
            name: Agent name.
            agent: Agent instance implementing AbstractAgent.
        """
        self.orchestrator.register_agent(name, agent)


# ---------------------------------------------------------------------------
# Singleton for CLI/server use
# ---------------------------------------------------------------------------

_app: BergAgentsApp | None = None


def get_app() -> BergAgentsApp:
    """Return the singleton BergAgentsApp instance."""
    global _app
    if _app is None:
        _app = BergAgentsApp.create()
    return _app
