"""Natural Language Processing tool for the code agent."""

import json
import logging

from langchain.chat_models import BaseChatModel
from langchain.messages import AIMessage
from langchain.tools import BaseTool, tool
from pydantic import BaseModel

logger = logging.getLogger(__name__)


def make_natural_language_tool(
    llm: BaseChatModel | None = None,
    tools: list[BaseTool] | None = None,
) -> BaseTool:
    """Create a ``process_natural_language`` tool for routing queries.

    The LLM and tool registry are captured in the closure at construction time
    so the tool is a plain :func:`@tool`-decorated function (no custom
    ``BaseTool`` subclass fields), which is how recent langchain-core expects
    tools to be registered.

    :param llm: The language model to use for processing natural language queries.
    :param tools: The tools to delegate to. May be empty at construction time
        and assigned by the agent afterwards.
    :return: A LangChain tool that routes natural-language queries to tools.
    """
    available_tools = tools if tools is not None else []

    @tool(
        "process_natural_language",
        description=(
            "Process natural language queries and delegate to the appropriate tool. "
            "Use this when the user asks a question or makes a request in plain English."
        ),
    )
    def process_natural_language(query: str) -> str:
        """Process a natural language query and delegate to the appropriate tool.

        :param query: The natural language query to process.
        :return: A JSON string describing the tool call to delegate to.
        """
        if not llm:
            return json.dumps({"error": "Language model not initialized"})

        # Create a detailed tool manifest for the prompt
        tool_manifest: list[str] = []
        for t in available_tools:
            args_schema = getattr(t, "args_schema", None)
            if (
                t.name == process_natural_language.name
                or not isinstance(args_schema, type)
                or not issubclass(args_schema, BaseModel)
            ):
                continue

            schema = args_schema.schema()
            properties = schema.get("properties", {})
            required_args = schema.get("required", [])

            arg_details: list[str] = []
            for arg_name, arg_info in properties.items():
                is_required = (
                    "required" if arg_name in required_args else "optional"
                )
                arg_desc = arg_info.get("description", "No description")
                arg_details.append(
                    f"      - `{arg_name}` ({is_required}): {arg_desc}"
                )

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

        content = ""
        try:
            response: AIMessage = llm.invoke(prompt)
            raw = (
                response.content
                if hasattr(response, "content")
                else str(response)
            )
            if isinstance(raw, list):
                raw = "\n".join(str(part) for part in raw)
            content = str(raw)
            logger.debug(f"Raw LLM response for tool selection: {content}")

            # Clean the response content
            content = content.strip()
            content = content.removeprefix("```json")
            content = content.removesuffix("```")
            content = content.strip()

            tool_call = json.loads(content)

            if not isinstance(tool_call, dict) or "tool" not in tool_call:
                return json.dumps({
                    "error": "LLM failed to select a valid tool."
                })

            return json.dumps(tool_call)

        except json.JSONDecodeError as e:
            logger.error(f"JSONDecodeError: {e}. LLM response was: {content}")
            return json.dumps({
                "error": "Invalid JSON format from LLM.",
                "raw_response": content,
            })
        except Exception as e:
            logger.error(f"Error in process_natural_language: {e}")
            return json.dumps({"error": f"An unexpected error occurred: {e!s}"})

    return process_natural_language
