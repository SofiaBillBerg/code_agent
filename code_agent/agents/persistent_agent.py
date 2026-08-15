"""Persistent agent implementation for the code_agent package."""

import json
from pathlib import Path
from typing import Any, Self
import uuid

from code_agent.agents.base_agent import build_agent
from langchain.chat_models import BaseChatModel
from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langchain.tools import BaseTool
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable

class PersistentAgent:
    """A persistent agent that maintains state between sessions."""

    _instance = None
    _state_file = Path.home() / ".code_agent" / "state.json"

    def __new__(cls: type[Self], *args: Any, **kwargs: Any) -> Any | Self:
        """Ensure only one instance of the agent exists.

        :param args: Positional arguments.
        :param kwargs: Keyword arguments.
        :return: The singleton instance of the agent.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, llm: BaseChatModel, tools: list[BaseTool]) -> None:
        """Initialize the agent with the given LLM and tools.

        :param llm: The language model to use.
        :param tools: The tools to use.
        :return: None
        """
        if self._initialized:  # type: ignore[has-type]
            return

        self.agent: Runnable = build_agent(llm=llm, tools=tools)
        self.conversation_history: list[dict[str, str]] = []
        self.settings: dict[str, Any] = {}
        self.thread_id = str(uuid.uuid4())
        self._initialized = True
        self._load_state()

    def _ensure_state_dir(self) -> None:
        """Ensure the state directory exists.

        :return: None
        """
        self._state_file.parent.mkdir(parents=True, exist_ok=True)

    def _load_state(self) -> None:
        """Load agent state from disk.

        :return: None
        """
        self._ensure_state_dir()
        if self._state_file.exists():
            try:
                with Path(self._state_file).open(encoding="utf-8") as f:
                    data = json.load(f)
                    self.conversation_history = data.get(
                        "conversation_history", []
                    )
                    self.settings = data.get("settings", {})
            except Exception as e:
                print(f"⚠️  Warning: Could not load state: {e}")

    def _save_state(self) -> None:
        """Save agent state to disk.

        :return: None
        """
        self._ensure_state_dir()
        try:
            data = {
                "conversation_history": self.conversation_history,
                "settings": self.settings,
            }
            with Path(self._state_file).open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"⚠️  Warning: Could not save state: {e}")

    def chat(self, message: str) -> str:
        """Process a message and return a response.

        Prefers event streaming when the underlying runnable supports it so
        intermediate tool calls can be surfaced through the chat interface.
        Falls back to blocking invocation when streaming is unavailable.

        :param message: The message to process.
        :return: The response from the agent.
        """
        self.conversation_history.append({"role": "user", "content": message})

        try:
            stream_fn = getattr(self.agent, "astream_events", None)
            if stream_fn is not None:
                response_content = self._chat_stream(stream_fn)
            else:
                response_content = self._chat_invoke()

            self.conversation_history.append({
                "role": "assistant",
                "content": response_content,
            })
            self._save_state()
            return response_content

        except Exception as e:
            error_msg = f"❌ Error: {e!s}"
            self.conversation_history.append({
                "role": "error",
                "content": error_msg,
            })
            self._save_state()
            return error_msg

    def _chat_invoke(self) -> str:
        """Run a blocking invoke and return the last assistant message content.

        :return: The response content from the agent.
        """
        response = self.agent.invoke(
            {"messages": self._history_to_messages()},
            config={"configurable": {"thread_id": self.thread_id}},
        )
        messages: list[BaseMessage] = (
            response.get("messages", []) if isinstance(response, dict) else []
        )
        for msg in reversed(messages):
            if hasattr(msg, "content") and getattr(msg, "content", None):
                return str(msg.content)
        return "(no text response)"

    def _chat_stream(self, stream_fn: Any) -> str:
        """Stream agent events and return the final assistant text.

        :param stream_fn: Callable that yields agent event dicts.
        :return: The assembled assistant response text.
        """
        final_text_parts: list[str] = []
        for event in stream_fn(
                {"messages": self._history_to_messages()},
                config={"configurable": {"thread_id": self.thread_id}},
                version="v2",
        ):
            data = event.get("data", {})
            if event.get("event") == "on_chat_model_stream":
                chunk = data.get("chunk")
                if chunk is not None:
                    content = getattr(chunk, "content", None)
                    if content:
                        print(content, end="", flush=True)
                        final_text_parts.append(content)
        return "".join(final_text_parts) or "(no text response)"

    def _history_to_messages(self) -> list[BaseMessage]:
        """Convert stored conversation history into LangChain messages.

        :return: Chronological list of :class:`BaseMessage` objects.
        """
        messages: list[BaseMessage] = []
        for entry in self.conversation_history:
            role = entry.get("role")
            content = entry.get("content", "")
            if role == "assistant":
                messages.append(AIMessage(content=content))
            elif role == "system":
                messages.append(SystemMessage(content=content))
            else:
                messages.append(HumanMessage(content=content))
        return messages

    def reset_conversation(self) -> None:
        """Reset the conversation history.

        :return: None
        """
        self.conversation_history = []
        self._save_state()


agent = None


def get_persistent_agent(
        llm: BaseChatModel, tools: list[Any]
) -> Any | PersistentAgent | None:
    """
    Get persistent agent.

    :param llm: Description of llm
    :param tools: Description of tools
    :return: Description of return value.

    Example::

        >>> result = get_persistent_agent(llm="example_llm", tools="example_tools")
    """
    global agent  # ruff: ignore[global-statement, undefined-export]
    if agent is None:
        agent = PersistentAgent(llm=llm, tools=tools)
    return agent


def main() -> None:
    """Run the interactive chat interface.

    This function provides a simple command-line interface for interacting with the agent.
    It handles user input, processes it through the agent, and displays the response.
    The interface also supports special commands like 'exit', 'quit', 'q', and 'clear'.
    The 'clear' command resets the conversation history.
    The 'help' command displays a list of available commands.

    :return: None
    """
    from code_agent.agents.base_agent import create_default_tools
    from code_agent.main import create_llm, load_config

    print("\n" + "=" * 50)
    print("=== Code Agent (Persistent) ===")
    print("Type 'exit', 'quit', or 'q' to end the session.")
    print("Type 'clear' to reset the conversation history.")
    print("Type 'help' for more options.")
    print("=" * 50 + "\n")

    try:
        cfg = load_config()
        llm = create_llm(cfg)
        tools = create_default_tools(llm=llm)
        agent = get_persistent_agent(llm, tools)
    except Exception as e:
        print(f"❌ Failed to initialize agent: {e}")
        return

    assert agent is not None

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break
        if user_input.lower() in {"exit", "quit", "q"}:
            print("Goodbye!")
            break
        if user_input.lower() == "clear":
            agent.reset_conversation()
            print("Conversation history cleared.")
            continue
        if user_input.lower() == "help":
            print("Commands: exit, quit, q, clear, help")
            continue
        if not user_input:
            continue
        print(f"Agent: {agent.chat(user_input)}")


if __name__ == "__main__":
    main()
