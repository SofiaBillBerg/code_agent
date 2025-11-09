"""Natural Language Processing tool for the code agent."""

import json
import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool


class NaturalLanguageTool(BaseTool):
    """Tool for processing natural language queries and delegating to appropriate tools."""

    name: str = "process_natural_language"
    description: str = """
    Process natural language queries and delegate to the appropriate tool.
    Use this when the user asks a question or makes a request in plain English.
    """

    llm: BaseChatModel | None = None
    tools: list = []  # This will be set later by the agent

    def _run(self, query: str, **kwargs: Any) -> str:
        """Process a natural language query and delegate to the appropriate tool."""
        if not self.llm:
            return json.dumps({"error": "Language model not initialized"})

        # Create a detailed tool manifest for the prompt
        tool_manifest = []
        for t in self.tools:
            if t.name == self.name or not hasattr(t, "args_schema"):
                continue

            schema = t.args_schema.schema()
            properties = schema.get("properties", {})
            required_args = schema.get("required", [])

            arg_details = []
            for arg_name, arg_info in properties.items():
                is_required = "required" if arg_name in required_args else "optional"
                arg_desc = arg_info.get("description", "No description")
                arg_details.append(f"      - `{arg_name}` ({is_required}): {arg_desc}")

            tool_manifest.append(
                    f"  - Tool: `{t.name}`\n"
                    f"    Description: {t.description}\n"
                    f"    Arguments:\n" + "\n".join(arg_details)
                    )

        tool_manifest_str = "\n".join(tool_manifest)

        prompt = f"""You are a JSON-only API endpoint. Your sole purpose is to translate a user's natural language 
        request into a single, valid JSON object that conforms to the provided tool specifications.

Your output MUST be ONLY the JSON object. Do not include ```json``` markers, explanations, or any other text.

**CRITICAL RULES**:
1. If the user asks to 'edit', 'improve', 'fix', or 'modify' an existing file, you MUST use the `read-file` tool 
FIRST to understand the file's current content.
2. If the user's query is a general question, a 'how-to' question, or does not match any specific tool, you MUST use 
the `general-chat` tool.

The JSON object must contain:
1. 'tool': The name of the tool to use.
2. 'arguments': A dictionary of arguments for the tool, matching the specification exactly.

Here are the available tools and their required arguments:
{tool_manifest_str}

User query: "{query}"

Valid JSON Response:"""

        try:
            response: AIMessage = self.llm.invoke(prompt)
            content = (response.content if hasattr(response, "content") else str(response))
            logging.debug(f"Raw LLM response for tool selection: {content}")

            # Clean the response content
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            tool_call = json.loads(content)

            if not isinstance(tool_call, dict) or "tool" not in tool_call:
                return json.dumps({"error": "LLM failed to select a valid tool."})

            return json.dumps(tool_call)

        except json.JSONDecodeError as e:
            logging.error(f"JSONDecodeError: {e}. LLM response was: {content}")
            return json.dumps(
                    {"error": "Invalid JSON format from LLM.", "raw_response": content, }
                    )
        except Exception as e:
            logging.error(f"Error in NaturalLanguageTool: {e}")
            return json.dumps({"error": f"An unexpected error occurred: {str(e)}"})
