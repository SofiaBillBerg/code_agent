"""
Main entry point for the Code Agent CLI.

This script wires together the LLM, embeddings, vector store, and tool set,
builds the LangGraph, and runs an interactive loop.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

# LangChain imports
from langchain_chroma import Chroma
from langchain_community.embeddings import GPT4AllEmbeddings
from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool  # Added import for BaseTool

# Local imports
from code_agent.agents.base_agent import create_default_tools
from code_agent.graph import build_graph
from code_agent.settings import Settings, get_settings


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """Load configuration as a dictionary.

    When *config_path* is provided the JSON file at that location is loaded
    (legacy override).  When it is ``None`` the typed application settings are
    returned instead, so the ``.env`` file / environment remain the single
    source of truth.

    Parameters
    ----------
    config_path:
        Optional path to a JSON configuration file.  If the path points to a
        directory, the function will look for ``llm_config.json`` inside.

    Returns
    -------
    Dict[str, Any]
        Parsed configuration dictionary.
    """
    if config_path is None:
        return get_settings().model_dump()

    cfg_file = Path(config_path)
    if cfg_file.is_dir():
        cfg_file = cfg_file / "llm_config.json"

    if not cfg_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with cfg_file.open("r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------


def create_llm(cfg: Settings | dict[str, Any]) -> BaseChatModel:
    """Create an LLM instance from config, with graceful fallback.

    The function supports an Ollama‑style backend and falls back to a
    lightweight dummy model that returns an error message when the real
    LLM cannot be initialised.

    Parameters
    ----------
    cfg:
        Either a :class:`~code_agent.settings.Settings` instance or a plain
        configuration dictionary (e.g. from :func:`load_config`).
    """
    if isinstance(cfg, Settings):
        cfg = cfg.model_dump()

    scheme = cfg.get("ollama_scheme", "http")
    host = cfg.get("ollama_host", "localhost")
    port = cfg.get("ollama_port", 11434)
    model = cfg.get("ollama_model", "gpt-oss:20b-cloud")
    temperature = cfg.get("temperature", 0.7)

    # ``ChatOllama`` is constructed lazily and never contacts the server, so an
    # invalid port would otherwise slip through and fail only at request time.
    # Build the URL up front and validate the port eagerly so bad configs
    # route to the graceful ``_FallbackLLM`` instead of hanging on a connection.
    base_url = f"{scheme}://{host}:{port}"

    try:
        from langchain_ollama import ChatOllama

        try:
            int(port)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid ollama_port: {port!r}")

        return ChatOllama(
            model=model, base_url=base_url, temperature=temperature
        )
    except Exception as exc:  # pragma: no cover – fallback path

        class _FallbackLLM(BaseChatModel):
            _err: Exception
            _base_url: str

            def __init__(self, err: Exception, base_url: str, **kwargs: Any):
                super().__init__(**kwargs)
                self._err = err
                self._base_url = base_url

            def _generate(
                self,
                messages: list[BaseMessage],
                stop: list[str] | None = None,
                run_manager: CallbackManagerForLLMRun | None = None,
                **kwargs: Any,
            ) -> ChatResult:
                content = json.dumps({
                    "error": "LLM unavailable",
                    "details": (
                        f"Failed to initialise ChatOllama. Error: {self._err}"
                        f". Base URL: {self._base_url}."
                    ),
                })
                return ChatResult(
                    generations=[
                        ChatGeneration(message=AIMessage(content=content))
                    ]
                )

            @property
            def _llm_type(self) -> str:
                return "fallback"

            def bind_tools(
                self,
                tools: Sequence[
                    dict[str, Any] | type | Callable[..., Any] | BaseTool
                ],
                **kwargs: Any,
            ) -> Runnable[LanguageModelInput, AIMessage]:
                return self  # Simply return self for fallback LLM

        return _FallbackLLM(exc, base_url)


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """
    Parse command-line arguments.
    Parses the given list of arguments and returns a
    `argparse.Namespace` object containing the parsed arguments.

    Parameters
    ----------
    argv : Sequence[str] | None
    List of command-line arguments. If `None`, `sys.argv` is used.

    Returns
    -------
    argparse.Namespace
    A namespace object containing the parsed arguments.
    """
    parser = argparse.ArgumentParser(
        prog="code_agent",
        description="An interactive agent for code manipulation.",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Enable DEBUG logs."
    )
    return parser.parse_args(argv)


def _setup_logging(debug: bool) -> None:
    """
    Setup logging for the Code Agent.

    This function sets up the logging module for the Code Agent. The logging level is set to `DEBUG` if the `debug`
    parameter is `True`, otherwise it is set to `INFO`.
    Parameters
    ----------
    debug : bool  Whether to enable DEBUG logs.

    Returns
    -------
    None This function does not return any value.
    """
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> None:
    """Entry point for the code agent CLI.

    Parameters
    ----------
    argv:
        Optional argument vector.  If ``None`` the function will read from
        :data:`sys.argv`.
    """
    print("=== Code Agent CLI ===")
    print("Type 'exit' or 'quit' to end the session.\n")

    args = _parse_args(argv)
    _setup_logging(args.debug)
    log.info("Starting Code Agent...")

    try:
        cfg = load_config()
        llm = create_llm(cfg)
        root_dir = Path(cfg.get("root_dir", ".")).resolve()
        tools = create_default_tools(root_dir=str(root_dir), llm=llm)

        # Build the LangGraph
        app = build_graph(llm, tools)

        # Vector store for retrieval‑augmented generation
        memory_dir = root_dir / ".code_agent_memory"
        memory_dir.mkdir(exist_ok=True)

        embeddings = GPT4AllEmbeddings(client=None)
        vectorstore = Chroma(
            collection_name="code_agent_conversations",
            embedding_function=embeddings,
            persist_directory=str(memory_dir),
        )

        log.info(f"Agent initialized with root: {root_dir}")
        log.info(f"Persistent memory initialized at: {memory_dir}")
        print(f"Available tools: {[t.name for t in tools]}\n")
    except Exception as e:
        log.critical(
            "Error loading or initializing agent: %s", e, exc_info=True
        )
        print(f"❌ Critical Error: {e}")
        sys.exit(1)

    print("\n✅ Agent ready! Type 'quit' or 'q' to exit.\n")
    _main_loop(app, vectorstore)


# ---------------------------------------------------------------------------
# Interactive loop
# ---------------------------------------------------------------------------


def _handle_retrieval(
    vectorstore: Chroma, user_input: str, chat_history: list[BaseMessage]
) -> None:
    """Retrieve relevant documents and update chat history."""
    retrieved_docs = vectorstore.similarity_search(user_input, k=2)
    if retrieved_docs:
        print("\n🧠 Retrieved from memory:")
        for doc in retrieved_docs:
            chat_history.append(
                HumanMessage(content=f"Past context: {doc.page_content}")
            )
            print(f"- {doc.page_content[:100]}...")


def _process_agent_event(event: dict) -> AIMessage | None:
    """Process a single event from the agent stream and print tool calls."""
    final_response = None
    for node, output in event.items():
        if node == "agent":
            agent_response = output.get("messages", [])[0]
            if getattr(agent_response, "tool_calls", None):
                for tool_call in agent_response.tool_calls:
                    print(
                        f"🛠️  Agent decided to use tool: **{tool_call['name']}**"
                    )
                    print(f"   With arguments: {tool_call['args']}")
            else:
                final_response = agent_response
        elif node == "action":
            print(f"✅ Tool output: {output}")
    return final_response


def _update_history_and_persist(
    vectorstore: Chroma,
    user_input: str,
    final_response: AIMessage,
    chat_history: list[BaseMessage],
) -> None:
    """Update chat history and persist to vector store."""
    print("\n=== Agent response ===")
    print(final_response.content)
    chat_history.append(final_response)
    vectorstore.add_texts(
        texts=[user_input, str(final_response.content)],
        metadatas=[
            {"type": "user_query"},
            {"type": "agent_response"},
        ],
    )


def _main_loop(app: Runnable, vectorstore: Chroma) -> None:
    """Run an interactive chat loop."""
    chat_history: list[BaseMessage] = []
    while True:
        try:
            user_input = input("You: ").strip()
            if user_input.lower() in {"exit", "quit", "q"}:
                print("Goodbye!")
                break
            if not user_input:
                continue

            log.info("User input: %s", user_input)
            _handle_retrieval(vectorstore, user_input, chat_history)
            chat_history.append(HumanMessage(content=user_input))

            print("\n=== Agent working... ===")
            final_response = None
            for event in app.stream({"messages": chat_history}):
                response = _process_agent_event(event)
                if response:
                    final_response = response

            if final_response:
                _update_history_and_persist(
                    vectorstore, user_input, final_response, chat_history
                )

            print("-" * 60)

        except KeyboardInterrupt:
            print("\n\nInterrupted. Goodbye!")
            break
        except Exception as e:
            log.exception("Error during agent execution")
            print(f"❌ An unexpected error occurred: {e}\n")


if __name__ == "__main__":
    main()
