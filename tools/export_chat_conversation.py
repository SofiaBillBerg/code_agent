"""Core Message Export Pattern - Integration Ready for berg_agents."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from langchain.messages import AnyMessage


# LangChain message types work with the agent runtime's built-in tools
try:
    from langchain_core.messages import AIMessage  # type: ignore[import]
except ImportError as e:
    raise ImportError(f"langchain-core required for export. Error: {e}") from e


def format_message_for_export(
    msg: AnyMessage,
) -> tuple[str, str]:
    """Format a single message into Markdown components.

    This function handles the three main message types used by berg_agents's
    built-in tools (read_file_tool, edit_file_tool, etc.) which return messages
    through LangGraph state rather than direct API calls.

    Args:
        msg: Message object from agent thread history. Can be HumanMessage,
            AIMessage, ToolMessage, or SystemMessage.

    Returns:
        Tuple of (display_role_name, formatted_content_string).

    Example::

        >>> from langchain_core.messages import HumanMessage  # type: ignore[import]
        >>> msg = HumanMessage(content="What is pandas?", name=None)
        >>> role, content = format_message_for_export(msg)
        >>> print(role)  # "User"

    """  # noqa: E501
    try:
        if isinstance(msg, AIMessage):
            return ("Assistant", str(msg.content))

        elif hasattr(msg, "type") and msg.type == "human":
            return ("User", str(msg.content) or "")

        elif hasattr(msg, "name"):  # ToolMessage has a name attribute
            try:
                output_lines = (
                    (str(msg.content)).split("\n")[:5]
                    if str(msg.content)[:100].strip()
                    else ""
                )
                func_name = (
                    msg.name.split(".")[-1] if "." in msg.name else msg.name
                )
                return (
                    f"Tool (`{func_name}`)",
                    "*Output:* " + "\n".join(output_lines),
                )
            except Exception:
                pass

        elif hasattr(msg, "role") and msg.role in ("system",):
            return (f"System (`{msg.name}`)", str(msg.content) or "")

    except Exception as e:  # noqa: E501 - Catch all message formatting errors
        raise ValueError(
            f"Failed to format message type {type(msg).__name__}: {e}"
        ) from e

    # Fallback for unknown types (shouldn't happen with berg_agents's tools)
    return ("Message", str(msg.content or getattr(msg, "__dict__", {})))


def export_conversation_as_markdown(
    messages: list[Any],  # type: ignore[type-arg] - Generic for flexibility
    thread_id: str | None = None,
) -> tuple[str, dict]:
    """Export conversation messages as formatted Markdown with YAML frontmatter.

    This is the core export function that integrates directly into berg_agents's
    agent runtime using its built-in file-system tools and configuration system.

    Unlike standalone FastAPI implementations (which don't match deepagents' architecture),
    this uses `get_settings()` for config access and `_atomic_write()` from berg_agents.tools._io.

    Args:
        messages: List of message objects from agent thread history. These come
            through LangGraph state after running via the built-in tools (read_file, edit_file, etc.).
        thread_id: Optional identifier used by deepagents for filename generation and metadata tracking.

    Returns:
        A tuple containing:

        * markdown_content (str): The complete Markdown document with YAML frontmatter.
          Can be written directly to a file via _atomic_write() or returned as response content.

        * export_metadata (dict): Metadata dictionary including thread_id, timestamp,
          message_count, tools_used list for filtering/searching later.

    Example usage in berg_agents::

        from langchain_core.messages import BaseMessage  # type: ignore[import]


        def get_thread_history(thread_id: str) -> dict:
            '''Fetch history via agent state (not external SDK calls).'''
            try:
                from deepagents.backends.state import StateBackend  # type: ignore[attr-defined, no-redef]

                backend = get_state_backend() or create_default_state_backend(
                    working_dir=Path.cwd()
                )
                return (
                    backend.get(thread_id)["values"]
                    if hasattr(backend, "get")
                    else {}
                )
            except Exception as e:
                from berg_agents.exceptions import CodeAgentError  # noqa: F401

                raise CodeAgentError(
                    f"Failed to get thread history for {thread_id}: {e}"
                )


        def export_thread(thread_id: str) -> tuple[str, dict]:
            '''Export a complete conversation.'''

            messages = get_thread_history(thread_id=thread_id)["messages"] or []
            markdown_content, metadata = export_conversation_as_markdown(
                messages, thread_id
            )

            return (markdown_content.strip(), metadata)

    Note: The function gracefully handles empty message lists and truncates very long
    tool outputs to keep exports readable while preserving key information.

    """  # noqa: E501
    if not messages or len(messages) == 0:
        content = (
            "# No Messages\n---\n\n*This conversation has no recorded history.*"
        )
        return (
            content,
            {"thread_id": thread_id or "no-history", "message_count": 0},
        )

    timestamp = datetime.now().isoformat()

    # Determine display title - use provided ID or auto-generate from content if needed
    first_content: str | None = (
        messages[0].content if hasattr(messages[0], "content") else ""
    )

    thread_display_name = (
        f" #{thread_id[-8:]}"
        if thread_id and len(thread_id) > 12
        else "#untitled-conversation"
    )

    # Build YAML frontmatter section using berg_agents's standard format conventions
    yaml_lines: list[str] = [
        "---",
        f"title: Conversation Note{thread_display_name}",
        "tags:",
        "- langchain - deepagents conversation export",
        "",
        f"> **Exported:** `{timestamp}` | **Thread ID:** `#{thread_id[-8:] if thread_id else 'N/A'}`",
        "",
        "summary: |",
        "  *This conversation was exported from berg_agents's agent runtime using built-in tools.*",
    ]

    # Collect tool names from messages that used built-in tools (read_file, edit_file, etc.)
    tools_used: set[str] = set()

    for msg in reversed(
        messages
    ):  # Process latest first to get most recent tools
        try:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                tc_list = getattr(msg, "tool_calls", []) or []

                for tc_item in tc_list[
                    :3
                ]:  # Only last few tool calls matter usually
                    func_obj = (tc_item.get("function")) or {}

                    if isinstance(func_obj, dict):
                        full_name: str | None = func_obj.get("name")

                        if full_name and "." in full_name:
                            tools_used.add(
                                full_name.split(".")[-1]
                            )  # Extract just the tool name part

        except (AttributeError, KeyError):
            pass

    yaml_lines.extend([""] * max(len(tools_used), 2))

    for tool_name in sorted(tools_used):
        yaml_lines.append(f"- {tool_name}")

    # Add model info if settings are available (berg_agents's config system)
    try:
        from berg_agents.config.settings import get_settings as _get_settings

        settings = _get_settings()  # type: ignore[assignment]

        provider_info = getattr(settings, "model", {}) or {}

        model_name: str | None = (
            provider_info
            if isinstance(provider_info, dict)
            else {"name": ""}.get("name")
            if hasattr(provider_info, "__getitem__")
            else ""
        )  # type: ignore[index]

        if model_name and len(model_name.strip()) > 0:
            yaml_lines.append(f"model_used: {str(model_name)[:35]}")

    except ImportError:
        pass

    except Exception as e:  # noqa: E501 - Catch other config errors gracefully
        print(f"Warning: Could not read model info for export metadata: {e}")

    yaml_content = "\n".join(yaml_lines) + "---\n\n"

    # Format message body with proper Markdown structure
    content_parts: list[str] = []

    for msg in messages[
        :100
    ]:  # Limit to first 100 messages (configurable via settings if needed)
        try:
            role_title, formatted_content = format_message_for_export(msg)

            if (
                not formatted_content.strip()
            ):  # Skip empty tool outputs that add no value
                continue

            content_parts.append(f"\n{formatted_content}")

        except ValueError as e:
            print(
                f"Skipping malformed message {len(messages)} in thread {thread_id}: {e}"
            )

    markdown_body = "\n".join(content_parts) if content_parts else ""

    full_content = yaml_content + markdown_body

    export_metadata: dict[str, Any] = {
        "thread_id": thread_id or str(hash(thread_id))[-8:]
        if thread_id
        else None,  # noqa: S324 - Hash for fallback ID
        "created_at": timestamp,
        "message_count": len(messages),
        "tools_used": sorted(tools_used) if tools_used else [],
        "has_summary": False,  # Will be set to True later by export_with_summary tool
    }

    return (full_content.strip(), export_metadata)


# Export this function for use in CLI commands and agent capabilities registry
__all__: list[str] = [
    "export_conversation_as_markdown",
    "format_message_for_export",
]
