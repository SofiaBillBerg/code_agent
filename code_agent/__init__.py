"""Top-level package for *code_agent*."""

from __future__ import annotations

# Import agent-related functions
from .agents import build_agent, create_default_tools

# OAP-inspired capability layer (public API)
from .capabilities.audit import AuditLog, Receipt
from .capabilities.base import Capability, CapabilityBase, RiskClass
from .capabilities.envelope import InvocationRequest, InvocationResponse
from .capabilities.registry import CapabilityRegistry
from .capabilities.tool_adapter import tool_to_capability
from .exceptions import CodeAgentError, FileCreationError, InvalidToolError
from .file_generator import (
    append_file,
    create_file,
    create_from_template,
    py_to_ipynb,
    write_file,
)
from .main import create_llm, load_config

# Provider-agnostic LLM layer (public API)
from .providers.base import LLMProvider, ProviderBase
from .providers.factory import create_provider
from .providers.ollama import OllamaProvider
from .providers.openai import OpenAIProvider
from .scaffold import create_project_scaffold


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
    "ProviderBase",
    "Receipt",
    "RiskClass",
    "append_file",
    "build_agent",
    "create_default_tools",
    "create_file",
    "create_from_template",
    "create_llm",
    "create_project_scaffold",
    "create_provider",
    "load_config",
    "py_to_ipynb",
    "tool_to_capability",
    "write_file",
]
