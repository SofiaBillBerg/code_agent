# tools/general_chat_tool.py
from __future__ import annotations

from typing import Any

from langchain.tools import BaseTool
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field


class GeneralChatArgs(BaseModel):
    """Arguments for a general chat query."""

    query: str = Field(
            ..., description = "The user's question or message for a general chat response.", )


class GeneralChatTool(BaseTool):
    """A tool for general conversation and questions."""

    name: str = "general-chat"
    description: str = ("Use this tool as a last resort if no other tool is appropriate for the user's query. "
                        "It is for general conversation, questions, and answering 'how-to' style inquiries.")
    args_schema: type[BaseModel] = GeneralChatArgs

    llm: BaseChatModel

    def __init__(self, llm_instance: BaseChatModel, **kwargs):
        super().__init__(llm = llm_instance, **kwargs)

    def _run(self, query: str) -> str:
        """Sends the query directly to the LLM for a conversational response."""

        prompt = f"""You are a helpful and knowledgeable AI assistant. A user has asked a question that does not fit
        any of the specialized tools. Provide a direct, helpful, and conversational answer to their query.

User's query: "{query}"

Your response:"""

        try:
            response = self.llm.invoke([HumanMessage(content = prompt)])
            if hasattr(response, "content"):
                return str(response.content)
            return str(response)
        except Exception as e:
            return f"❌ Error during general chat: {e}"

    async def _arun(self, **kwargs: Any) -> str:
        """Async version."""
        # Simplified for now
        query = kwargs.get("query", "")
        return self._run(query)
