"""Agent factory helpers."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from code_agent.graph import build_graph

__all__ = ["build_agent", "create_default_tools"]


def build_agent(llm: BaseChatModel, tools: Iterable[BaseTool]) -> Runnable:
    """Builds a LangChain runnable with tools bound to the LLM."""
    return build_graph(llm, list(tools))


def create_default_tools(
        root_dir: str | None = None, llm: BaseChatModel | None = None
        ) -> list[BaseTool]:
    """Return a list of default tools."""

    from code_agent.tools import (EditFileTool, FormatCodeTool, GeneralChatTool, GenerateTestTool, LinkerTool,
                                  NewFileTool, NotebookTool, ReadFileTool, RScriptTool, SearchExplainTool, )

    root_path = Path(root_dir) if root_dir else Path.cwd()

    standard_tools: list[BaseTool | None] = [ReadFileTool(root_dir = root_path), EditFileTool(root_dir = root_path),
            (SearchExplainTool(root_dir = root_path, llm_instance = llm) if llm else None),
            LinkerTool(root_dir = root_path), NewFileTool(root_dir = root_path),
            (GenerateTestTool(root_dir = root_path, llm_instance = llm) if llm else None),
            FormatCodeTool(root_dir = root_path),
            (NotebookTool(root_dir = root_path, llm_instance = llm) if llm else None),
            (GeneralChatTool(llm_instance = llm) if llm else None), RScriptTool(), ]

    tools: list[BaseTool] = [tool for tool in standard_tools if tool is not None]

    return tools
