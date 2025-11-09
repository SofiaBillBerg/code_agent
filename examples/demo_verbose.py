from code_agent.agents.persistent_agent import get_persistent_agent


class DummyLLM:
    def invoke(self, messages):
        """
        Invoke the LLM with a list of messages and return a response.

        Parameters
        ----------
        messages : list[HumanMessage]
            The list of messages to send to the LLM.

        Returns
        -------
        R
            A response object with a content attribute containing the response text.
        """

        class R:
            pass

        r = R()
        # Simple echo-style response, and include no tool call markers (so agent returns it)
        r.content = ("I will review the repository: I'll look for structure, tests, docs "
                     "and refactor opportunities. First step: run tests and linter.")
        return r


if __name__ == "__main__":
    llm = DummyLLM()
    agent = get_persistent_agent(llm = llm, tools = [])
    agent.verbose = True
    resp = agent.chat(
            "Could you please review and refactor the codebase for code_Agent (exclude revised_pipeline)?"
            )
    print("\nAgent returned:\n", resp)
