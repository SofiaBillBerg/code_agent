"""Module for middleware functions.

Note:
    This module is intended for internal use within the code_agent package.
    The implementation is not finished, this may be considered a work in progress and only as a draft.
"""

from __future__ import annotations

from deepagents import create_deep_agent
from deepagents.backends import (
    CompositeBackend,
    FilesystemBackend,
    StateBackend,
)
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    ModelRetryMiddleware,
    SummarizationMiddleware,
    ToolRetryMiddleware,
)

from code_agent.tools import (
    edit_file,
    generate_test,
    make_general_chat_tool,
    make_linker_tool,
    make_natural_language_tool,
    make_new_file_tool,
    make_r_script_tool,
    make_search_explain_tool,
    py_to_ipynb,
    read_file,
)
from code_agent.tools.docs_generator import generate_quarto_docs
from code_agent.utils.checkpointer import build_checkpointer


default_middleware = [
    ToolRetryMiddleware(
        max_retries=3,
        backoff_factor=2.0,
        initial_delay=1.0,
    ),
    ModelRetryMiddleware(
        max_retries=3,
        backoff_factor=2.0,
        initial_delay=1.0,
    ),
    SummarizationMiddleware(
        model="{summarization_model}",
        trigger=("fraction", 0.8),
        keep=("fraction", 0.3),
    ),
    HumanInTheLoopMiddleware(
        interrupt_on={
            "make_natural_language_tool": {
                "allowed_decisions": ["approve", "edit", "reject"],
            },
            "edit_file": {
                "allowed_decisions": ["approve", "edit", "reject"],
            },
            "generate_test": {
                "allowed_decisions": ["approve", "edit", "reject"],
            },
            "generate_quarto_docs": {
                "allowed_decisions": ["approve", "edit", "reject"],
            },
            "notebook-tool": {
                "allowed_decisions": ["approve", "edit", "reject"],
            },
            "make_notebook_tool": {
                "allowed_decisions": ["approve", "edit", "reject"],
            },
            "make_linker_tool": {
                "allowed_decisions": ["approve", "edit", "reject"],
            },
            "make_r_script_tool": {
                "allowed_decisions": ["approve", "edit", "reject"],
            },
            "make_search_explain_tool": {
                "allowed_decisions": ["approve", "edit", "reject"],
            },
            "read_file": {
                "allowed_decisions": ["approve", "edit", "reject"],
            },
            "search_explain_tool": {
                "allowed_decisions": ["approve", "edit", "reject"],
            },
        }
    ),
]
default_backend = CompositeBackend(
    default=StateBackend(),
    routes={
        "/memories/": FilesystemBackend(
            root_dir="/workspace/code_agent", virtual_mode=True
        ),
    },
)

main_agent = create_deep_agent(
    name="CodeAgent",
    model="{model}",
    checkpointer=build_checkpointer(checkpoint_dir="/workspace/.checkpoints"),
    tools=[
        py_to_ipynb,
        make_general_chat_tool,
        make_linker_tool,
        make_r_script_tool,
        make_search_explain_tool,
        make_new_file_tool,
        make_natural_language_tool,
        edit_file,
        read_file,
        generate_test,
        generate_quarto_docs,
    ],
    middleware=default_middleware,
    memory=[".code_agent_memory/", "AGENTS.md"],
)
