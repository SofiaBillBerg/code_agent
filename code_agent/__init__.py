"""Top‑level package for *code_agent*."""

from __future__ import annotations

# Import agent-related functions
from .agents import build_agent, create_default_tools
# OAP-inspired capability layer (public API)
from .capabilities.audit import AuditLog, Receipt
from .capabilities.base import Capability, CapabilityBase, RiskClass
from .capabilities.base import Capability, CapabilityBase, RiskClass
from .capabilities.envelope import InvocationRequest, InvocationResponse
from .capabilities.envelope import InvocationRequest, InvocationResponse
from .capabilities.registry import CapabilityRegistry
from .capabilities.registry import CapabilityRegistry
from .capabilities.tool_adapter import tool_to_capability
from .capabilities.tool_adapter import tool_to_capability
from .core import create_project_scaffold
from .core import create_project_scaffold
# First import non-dependent modules
from .exceptions import CodeAgentError, FileCreationError, InvalidToolError
# First import non-dependent modules
from .exceptions import CodeAgentError, FileCreationError, InvalidToolError
from .file_generator import create_from_template, py_to_ipynb, write_file
from .file_generator import create_from_template, py_to_ipynb, write_file
from .main import create_llm, load_config
from .main import create_llm, load_config
# Provider-agnostic LLM layer (public API)
from .providers.base import LLMProvider, ProviderBase
from .providers.factory import create_provider
from .providers.ollama import OllamaProvider
from .providers.openai import OpenAIProvider

# Explicitly expose the public API members
__all__ = [
    "CodeAgentError",
    "FileCreationError",
    "InvalidToolError",
    "build_agent",
    "create_default_tools",
    "create_project_scaffold",
    "create_from_template",
    "py_to_ipynb",
    "write_file",
    "create_llm",
    "load_config",
    "AuditLog",
    "Capability",
    "CapabilityBase",
    "CapabilityRegistry",
    "InvocationRequest",
    "InvocationResponse",
    "Receipt",
    "RiskClass",
    "tool_to_capability",
    "create_provider",
    "LLMProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "ProviderBase",
]
