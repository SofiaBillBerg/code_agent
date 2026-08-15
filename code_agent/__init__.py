"""Top-level package for *code_agent*."""

from __future__ import annotations

from code_agent.agents.base_agent import create_default_tools
from code_agent.agents.deepagents_agent import (
    build_deep_agent,
    make_backend,
    make_default_permissions,
)

# Import agent-related functions
from code_agent.agents.persistent_agent import (
    PersistentAgent,
    build_agent,
    get_persistent_agent,
)

# OAP-inspired capability layer (public API)
from code_agent.capabilities.audit import AuditLog, Receipt
from code_agent.capabilities.base import Capability, CapabilityBase, RiskClass
from code_agent.capabilities.envelope import (
    InvocationRequest,
    InvocationResponse,
)
from code_agent.capabilities.registry import CapabilityRegistry
from code_agent.capabilities.tool_adapter import tool_to_capability
from code_agent.exceptions import (
    CodeAgentError,
    FileCreationError,
    InvalidToolError,
)
from code_agent.main import create_llm, load_config

# Provider-agnostic LLM layer (public API)
from code_agent.providers.base import LLMProvider, ProviderBase
from code_agent.providers.factory import create_provider
from code_agent.providers.ollama import OllamaProvider
from code_agent.providers.openai import OpenAIProvider

# Explicitly expose the public API members
__all__ = [
    "AuditLog",
    "Capability",
    "CapabilityBase",
    "CapabilityRegistry",
    "CodeAgentError",
    "FileCreationError",
    "InvalidToolError",
    "InvocationRequest",
    "InvocationResponse",
    "LLMProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "PersistentAgent",
    "ProviderBase",
    "Receipt",
    "RiskClass",
    "build_agent",
    "build_deep_agent",
    "create_default_tools",
    "create_llm",
    "create_provider",
    "get_persistent_agent",
    "load_config",
    "make_backend",
    "make_default_permissions",
    "tool_to_capability",
]
