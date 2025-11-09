"""
This module defines the core agent graph using LangGraph.
The graph orchestrates the flow of conversation, tool use, and memory.

The function `build_graph` is designed for direct use, but a thin
wrapper called `graph_factory` is also provided so the graph can be
loaded via `langgraph_api.utils.load_graph` which expects a callable
with the signature `(RunnableConfig) -> Runnable`.
"""

from __future__ import annotations

from typing import TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (AIMessage, BaseMessage, )
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode


# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------
class AgentState(TypedDict):
    """The conversational state.

    Attributes
    ----------
    messages:
        A sequence of chat messages that represents the conversation
        history.
    """

    messages: list[BaseMessage]


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------


def call_llm(state: AgentState, model: Runnable) -> AgentState:
    """Invoke the LLM with the full conversation history and return the
    updated state.

    Parameters
    ----------
    state:
        The current state of the graph.
    model:
        A tool‑aware LLM instance.

    Returns
    -------
    AgentState
        Updated state that contains the new LLM message.
    """
    response = model.invoke(state["messages"])
    # Preserve the conversation history
    return {"messages": state["messages"] + [response]}


def should_continue(state: AgentState) -> str:
    """Decide the next node.

    If the last LLM message contains a tool call, we route to the
    ``action`` node; otherwise we finish the conversation.
    """
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "action"
    return END


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def build_graph(llm: BaseChatModel, tools: list[BaseTool]) -> Runnable:
    """Build a LangGraph ``StateGraph`` for a tool‑aware agent.

    Parameters
    ----------
    llm:
        The underlying language model.
    tools:
        A list of tools that the agent can invoke.

    Returns
    -------
    Runnable
        The compiled graph ready for execution.
    """
    # Bind tools to the LLM
    model = llm.bind_tools(tools)

    graph = StateGraph(AgentState)  # type: ignore

    # Nodes
    graph.add_node("agent", lambda state: call_llm(state, model))
    graph.add_node("action", ToolNode(tools))

    # Entry point
    graph.set_entry_point("agent")

    # Conditional routing
    graph.add_conditional_edges(
            "agent", should_continue, {"action": "action", END: END}, )

    # Return to agent after a tool call
    graph.add_edge("action", "agent")

    # Compile the graph
    return graph.compile()


# ---------------------------------------------------------------------------
# Wrapper for langgraph_api.utils.load_graph
# ---------------------------------------------------------------------------


def graph_factory(config: RunnableConfig) -> Runnable:
    """Return a runnable graph from a :class:`RunnableConfig`.

    ``langgraph_api`` expects a callable that accepts a single
    ``RunnableConfig`` argument.  The configuration is expected to
    contain ``configurable`` entries ``llm`` (``BaseChatModel``)
    and ``tools`` (``List[BaseTool]``).
    """
    cfg = config.get("configurable", {})
    llm: BaseChatModel = cfg["llm"]
    tools: list[BaseTool] = cfg["tools"]
    return build_graph(llm, tools)


# ``__all__`` ensures we only export the public API.
__all__ = ["AgentState", "build_graph", "graph_factory"]
