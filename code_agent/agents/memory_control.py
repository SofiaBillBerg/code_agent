from __future__ import annotations

from typing import TypedDict

from langchain.chat_models import init_chat_model
from langchain.messages import AnyMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.graph import MessagesState
import langmem.short_term  # ty: ignore[unresolved-import]

class State(MessagesState):
    summary: str


model = init_chat_model("{model_name}", model_kwargs={"temperature": 0.0})
summarization_model = model.bind(max_tokens=900)


class State(MessagesState):
    context: dict[str, langmem.short_term.RunningSummary]


class LLMInputState(TypedDict):
    """Represent the input state for the LLM node in the graph."""

    messages: list[AnyMessage]
    summarized_messages: list[AnyMessage]
    context: dict[str, langmem.short_term.RunningSummary]


summarization_node = langmem.short_term.SummarizationNode(
    token_counter=count_tokens_approximately,
    model=summarization_model,
    max_tokens=900,
)

"""Work in progress: a graph that summarizes the conversation and then calls the model with the summarized messages.
def call_model(state: LLMInputState) -> dict[str, list[AIMessage]]:
   # 
    messages = trim_messages(
     strategy="last",
        token_counter=count_tokens_approximately,
        max_tokens=900,
        messages=state["messages"],
        start_on="human",
        end_on=("human", "tool"),
    )
    response = model.invoke(messages)

    response = model.invoke(state["summarized_messages"])
    return {"messages": [response]}


checkpointer = InMemorySaver()
builder = StateGraph(State)
builder.add_node(call_model)
builder.add_node("summarize", summarization_node)
builder.add_edge(START, "summarize")
builder.add_edge("summarize", "call_model")
graph = builder.compile(checkpointer=checkpointer)

# Invoke the graph
config = {"configurable": {"thread_id": "1"}}
graph.invoke({"messages": "{}"}, config)
graph.invoke({"messages": "{]"}, config=config)
graph.invoke({"messages": "{]"}, config)
final_response = graph.invoke({"messages": "{}"}, config)

final_response["messages"][-1].pretty_print()
print("\nSummary:", final_response["context"]["running_summary"].summary)


def summarize_conversation(state: State) -> dict[str, list[RemoveMessage] | str]:
    
    # First, we get any existing summary
    summary = state.get("summary", "")

    # Create our summarization prompt
    if summary:
        # A summary already exists
        summary_message = (
            f"This is a summary of the conversation to date: {summary}\n\n"
            "Extend the summary by taking into account the new messages above:"
        )

    else:
        summary_message = "Create a summary of the conversation above:"

    # Add prompt to our history
    messages = state["messages"] + [HumanMessage(content=summary_message)]
    response = model.invoke(messages)
    return {'summary': response.content, 'messages': [RemoveMessage()]}
"""
