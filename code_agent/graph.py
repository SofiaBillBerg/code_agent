"""Agent graph implementation using LangChain's create_agent.

This replaces the previous custom StateGraph with the supported
LangChain agent harness, including:
- Proper tool registration via create_agent
- Checkpointer for conversation memory (InMemorySaver)
- Human-in-the-loop middleware for sensitive tools
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langgraph.checkpoint.memory import InMemorySaver


def build_graph(llm: BaseChatModel, tools: list[BaseTool]) -> Runnable:
    """Build a LangChain agent with the given LLM and tools.

    Uses create_agent with:
    - InMemorySaver checkpointer for conversation memory
    - HumanInTheLoopMiddleware for write/edit/format/notebook/r-script tools

    :param llm: The underlying language model.
    :param tools: A list of tools that the agent can invoke.
    :returns: A compiled agent runnable ready for execution.
    """
    tool_names = {t.name for t in tools}
    interrupt_on = {}

    if "edit-file" in tool_names:
        interrupt_on["edit-file"] = True
    if "new-file" in tool_names:
        interrupt_on["new-file"] = True
    if "format-code" in tool_names:
        interrupt_on["format-code"] = True
    if "notebook" in tool_names:
        interrupt_on["notebook"] = True
    if "r-script" in tool_names:
        interrupt_on["r-script"] = True

    middleware = []
    if interrupt_on:
        middleware.append(
            HumanInTheLoopMiddleware(
                interrupt_on=interrupt_on,
                description_prefix="Tool execution requires approval",
            )
        )

    return create_agent(
        model=llm,
        tools=list(tools),
        checkpointer=InMemorySaver(),
        middleware=middleware,
        system_prompt=(
            "You are a coding agent. Use tools for every filesystem action.\n"
            "All file operations are relative to the project root unless the user provides an absolute path.\n"
            "ALWAYS use tools for filesystem operations. Never describe hypothetical files or directories.\n"
            "When asked to read, create, edit, or search files, call the appropriate tool immediately.\n"
            "Do not summarize or fabricate file contents you have not read.\n"
            "Keep responses concise and actionable."
        ),
    )
