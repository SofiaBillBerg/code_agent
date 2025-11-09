"""Top‑level package for *code_agent*."""

from __future__ import annotations

# Import agent-related functions
from .agents import build_agent, create_default_tools
from .core import create_project_scaffold

# First import non-dependent modules
from .exceptions import CodeAgentError, FileCreationError, InvalidToolError
from .file_generator import create_from_template, py_to_ipynb, write_file
from .main import create_llm, load_config

# Explicitly expose the public API members
__all__ = ["build_agent", "create_default_tools", "create_llm", "write_file", "create_from_template", "py_to_ipynb",
        "create_project_scaffold", "load_config", "CodeAgentError", "InvalidToolError", "FileCreationError", ]
