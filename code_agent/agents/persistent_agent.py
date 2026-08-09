"""Persistent agent implementation for the code_agent package."""

import json

from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from typing_extensions import Self

from code_agent.agents.base_agent import build_agent


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
        if self._initialized:
            return

        self.agent: Runnable = build_agent(llm=llm, tools=tools)
        self.conversation_history: list[dict[str, str]] = []
        self.settings: dict[str, Any] = {}
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

        :param message: The message to process.
        :return: The response from the agent.
        """
        if not self.agent:
            return "❌ Agent not initialized. Please check the configuration."

        self.conversation_history.append({"role": "user", "content": message})

        try:
            response = self.agent.invoke({
                "input": message,
                "chat_history": self.conversation_history,
            })
            response_content = response.get("output", str(response))
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

    def reset_conversation(self) -> None:
        """Reset the conversation history.

        :return: None
        """
        self.conversation_history = []
        self._save_state()


agent = None


def get_persistent_agent(llm, tools: list[Any]) -> Any | None | PersistentAgent:
    global agent
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
    print("\n" + "=" * 50)
    print("=== Code Agent (Persistent) ===")
    print("Type 'exit', 'quit', or 'q' to end the session.")
    print("Type 'clear' to reset the conversation history.")
    print("Type 'help' for more options.")
    print("=" * 50 + "\n")

    # This part needs to be refactored to be called from the main entry point  # For now, it serves as a placeholder.


if __name__ == "__main__":
    main()
