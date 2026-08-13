"""Tools for the code_agent package.

The registry exports two kinds of tools:

- function-based tools (``edit_file``, ``read_file``, ``generate_test``) which
  are :class:`langchain_core.tools.StructuredTool` instances created with the
  ``@tool`` decorator and accept ``root_dir`` at call time, and
- factory-based tools (``make_format_code_tool``, ``make_linker_tool``, ...)
  which return ``@tool``-decorated functions with ``root_dir`` (and optionally
  an ``llm`` instance) captured in the closure at construction time.
"""

from __future__ import annotations

from .edit_file_tool import edit_file
from .format_code_tool import make_format_code_tool
from .general_chat_tool import make_general_chat_tool
from .generate_test_tool import generate_test
from .linker_tool import make_linker_tool
from .new_file_tool import make_new_file_tool
from .nlp_tool import make_natural_language_tool
from .notebook_tool import make_notebook_tool
from .r_tool import make_r_script_tool
from .read_file_tool import read_file
from .search_explain_tool import make_search_explain_tool


__all__ = [
    "edit_file",
    "generate_test",
    "make_format_code_tool",
    "make_general_chat_tool",
    "make_linker_tool",
    "make_natural_language_tool",
    "make_new_file_tool",
    "make_notebook_tool",
    "make_r_script_tool",
    "make_search_explain_tool",
    "read_file",
]
