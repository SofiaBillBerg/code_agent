"""Agent factory helpers."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from code_agent.tools.notebook_tool import py_to_ipynb
from code_agent.utils.graph import Harness, build_graph
from langchain.chat_models import BaseChatModel
from langchain.tools import BaseTool
from langchain_core.runnables import Runnable

__all__ = ["build_agent", "create_default_tools"]


def build_agent(
    llm: BaseChatModel,
    tools: Iterable[BaseTool],
    *,
    harness: Harness = "deepagents",
    root_dir: str | Path = ".",
    **kwargs: Any,
) -> Runnable:
    """Builds a LangChain runnable with tools bound to the LLM.

    :param llm: The language model to use.
    :param tools: The tools to bind to the LLM.
    :param harness: Agent harness to use - ``"deepagents"`` (default, a
        DeepAgents/LangGraph agent with a virtual filesystem and
        permission-based human-in-the-loop) or ``"create_agent"`` (LangChain's
        ``create_agent``).
    :param root_dir: Working directory mounted at ``/workspace/`` when
        *harness* is ``"deepagents"``.
    :param kwargs: Extra keyword arguments forwarded to the harness builder.

    :return: A LangChain runnable.
    """
    return build_graph(
        llm, list(tools), harness=harness, root_dir=root_dir, **kwargs
    )


def create_default_tools(
    root_dir: str | None = None, llm: BaseChatModel | None = None
) -> list[BaseTool]:
    """Return a list of default tools.

    :param root_dir: The root directory to use for the tools.
    :param llm: The language model to use for the tools.

    :return: A list of default tools.
    """
    from functools import wraps

    from code_agent.tools import (
        edit_file,
        generate_test,
        make_format_code_tool,
        make_general_chat_tool,
        make_new_file_tool,
        make_r_script_tool,
        make_search_explain_tool,
        read_file,
    )
    from langchain_core.tools import StructuredTool

    root_path = Path(root_dir) if root_dir else Path.cwd()

    def bind_root_dir(tool: BaseTool) -> BaseTool:
        """Bind the configured root directory to a function-based tool.

        LangGraph's ``ToolNode`` introspects the underlying callable to find
        injected arguments, which ``functools.partial`` objects do not
        support.  A ``functools.wraps`` closure keeps the original signature
        (``get_type_hints`` follows ``__wrapped__``) while binding ``root_dir``.

        :param tool: The tool to bind the root directory to.
        :return: The tool with the root directory bound.
        """
        func = getattr(tool, "func", None) or tool.invoke
        root = root_path

        @wraps(func)
        def _bound(*args: Any, **kwargs: Any) -> Any:
            """The bound root_dir always wins over any caller-supplied value so tools cannot escape the configured working directory.

            :param args: The arguments to pass to the function.
            :param kwargs: The keyword arguments to pass to the function.
            :return: The result of the function.
            """
            kwargs.pop("root_dir", None)
            return func(*args, root_dir=root, **kwargs)

        return StructuredTool.from_function(
            func=_bound,
            name=tool.name,
            description=tool.description,
            args_schema=tool.args_schema,
        )

    standard_tools: list[BaseTool | None] = [
        bind_root_dir(read_file),
        bind_root_dir(edit_file),
        (
            make_search_explain_tool(root_dir=root_path, llm=llm)
            if llm
            else None
        ),
        make_new_file_tool(root_dir=root_path),
        bind_root_dir(generate_test),
        make_format_code_tool(root_dir=root_path),
        # ``py_to_ipynb`` is a plain function, not a ``BaseTool``; wrap it so
        # downstream code that expects ``.name``/``.args_schema`` (e.g. the
        # capability adapter) behaves. The function stays callable for its
        # direct callers.
        StructuredTool.from_function(py_to_ipynb),
        (make_general_chat_tool(llm=llm) if llm else None),
        make_r_script_tool(),
    ]

    tools: list[BaseTool] = [
        tool for tool in standard_tools if tool is not None
    ]

    return tools
