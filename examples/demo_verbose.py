from __future__ import annotations

from code_agent.agents.persistent_agent import get_persistent_agent
from langchain.messages import HumanMessage

class DummyLLM:
    """Dummy LLM that always returns the same message."""

    def invoke(self, messages: list[HumanMessage]) -> R:
        """
        Invoke the LLM with a list of messages and return a response.

        :param messages : list[HumanMessage] The list of messages to send to the LLM.
        :return R: A response object with a content attribute containing the response text.
        """
        print("LLM invoked with messages:", messages)

        # Create a response object
        R = type("R", (), {})()
        # Set the content of the response
        R.content = (
            "I'm a dummy LLM. I don't know how to respond to your message."
        )
        return R


if __name__ == "__main__":
    llm = DummyLLM()
    agent = get_persistent_agent(llm=llm, tools=[])
    agent.verbose = True
    resp = agent.chat(
        "Could you please review and refactor the codebase for code_Agent (exclude revised_pipeline)?"
    )
    print("\nAgent returned:\n", resp)
