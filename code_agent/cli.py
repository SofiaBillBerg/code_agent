"""Command‑line interface for the **code_agent** package.

The CLI is intentionally small - it only exposes the most common
operations that a developer would want when working in a local
repository:

* ``create`` - create a new file with supplied content.
* ``append`` - append to an existing file.
* ``scaffold`` - generate a minimal project structure.
* ``py2ipynb`` - convert a Python script to a Jupyter notebook.
* ``docs`` - generate Quarto documentation for the current tree.
* ``chat`` - start an interactive chat session with the agent.
* ``capabilities list`` - list the registered capabilities.
* ``capabilities invoke`` - dispatch an invocation through the registry.
* ``serve`` - start the LLM provider selected by the config.

Implementation details
----------------------
* Uses **Typer** for argument parsing - it provides a pleasant
  developer experience (automatic ``--help`` generation, type checking
  and rich error messages).
* All file‑system interactions are delegated to
  :func:`code_agent.file_generator.write_file` and
  :func:`code_agent.file_generator.py_to_ipynb`.
* ``scaffold`` uses :func:`code_agent.file_generator.create_project_scaffold`.
* ``docs`` simply calls :func:`code_agent.docs_generator.generate_quarto_docs`.
* ``capabilities`` commands build a :class:`CapabilityRegistry` populated
  with the default tools adapted via :func:`tool_to_capability`, then
  discover or dispatch through it.
* ``serve`` selects a provider via :func:`create_provider` from the config
  and runs a small read‑eval‑print loop against ``provider.complete``.
* Errors are wrapped in :class:`code_agent.exceptions.CodeAgentError` to

The CLI is intentionally **stateless** - it performs the requested
action and exits.  All heavy lifting is done by the helper functions.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid

from pathlib import Path
from typing import Any

import typer

from langchain_core.tools import BaseTool

from code_agent.agents.base_agent import build_agent, create_default_tools
from code_agent.capabilities.audit import Receipt
from code_agent.capabilities.envelope import (
    InvocationRequest,
    InvocationResponse,
)
from code_agent.capabilities.registry import CapabilityRegistry
from code_agent.capabilities.tool_adapter import tool_to_capability
from code_agent.docs_generator import generate_quarto_docs
from code_agent.exceptions import CodeAgentError
from code_agent.file_generator import py_to_ipynb, write_file
from code_agent.main import create_llm, load_config
from code_agent.providers.factory import create_provider
from code_agent.scaffold import create_project_scaffold


app = typer.Typer(name="code_agent", help="Local LLM‑driven code assistant")


def _build_registry(root_dir: str | None = None) -> CapabilityRegistry:
    """Build a registry populated with the default tool‑adapted capabilities.

    Each default tool that can be constructed without an LLM is wrapped via
    :func:`tool_to_capability` and registered under its kebab‑cased id. Tools
    that require an LLM (e.g. ``search-explain``, ``generate-test``) are
    intentionally omitted so ``capabilities`` commands stay stateless and do
    not require a running model backend.

    :param root_dir: Root directory the tools operate within; defaults to the
            current working directory.

    :return: A :class:`CapabilityRegistry` with the adapted tools registered.
    """
    registry = CapabilityRegistry()
    for tool in create_default_tools(root_dir=root_dir):
        registry.register(tool_to_capability(tool))  # type: ignore[arg-type]
    return registry


def _echo_response(response: InvocationResponse, receipt: Receipt) -> None:
    """Print an invocation response and its audit receipt.

    :param response: The invocation response to display.
    :param receipt: The audit receipt recorded for the dispatch.
    :return: None
    """
    if response.status == "error":
        typer.echo("status: error")
        typer.echo(f"error: {response.error}")
    else:
        typer.echo("status: ok")
        typer.echo(f"result: {json.dumps(response.result, default=str)}")
    typer.echo(f"duration_ms: {response.duration_ms}")
    typer.echo(
        f"receipt: request_id={receipt.request_id} "
        f"status={receipt.status} timestamp={receipt.timestamp} "
        f"receipt_hash={receipt.receipt_hash}"
    )


capabilities_app = typer.Typer(
    help="Inspect and invoke the registered capabilities."
)
app.add_typer(capabilities_app, name="capabilities")


@capabilities_app.command("list", help="List all registered capabilities.")
def capabilities_list() -> None:
    """List every registered capability (id, intent, risk class).

    The catalog is built from the default tools adapted into capabilities.
    Each row shows the capability ``id``, its ``risk_class`` and its
    ``intent`` (a human description of what the capability does).

    :return: None
    """
    capabilities = _build_registry().discover()
    if not capabilities:
        typer.echo("No capabilities registered.")
        return

    rows: list[tuple[str, str, str]] = [
        (cap["id"], cap["risk_class"], cap["intent"]) for cap in capabilities
    ]
    id_width = max(len(row[0]) for row in rows)
    risk_width = max(len(row[1]) for row in rows)
    for cap_id, risk_class, intent in rows:
        typer.echo(
            f"{cap_id:<{id_width}}  {risk_class:<{risk_width}}  {intent}"
        )


@capabilities_app.command(
    "invoke", help="Dispatch a request through the registry."
)
def capabilities_invoke(
    capability_id: str = typer.Argument(
        ..., help="Identifier of the capability to invoke."
    ),
    params: str = typer.Option(
        "{}", help="JSON object of invocation parameters."
    ),
) -> None:
    """Invoke a capability and print the response and audit receipt.

    Builds an :class:`InvocationRequest` for ``capability_id`` with the
    supplied ``params`` (a JSON object), dispatches it through the registry
    and prints the resulting :class:`InvocationResponse` together with the
    hash‑chained audit :class:`Receipt`. A non‑zero exit code is returned
    when the dispatch reports an error.

    :param capability_id: Stable identifier of the capability to invoke.
    :param params: JSON object of parameters for the capability.
    :return: None
    """
    try:
        parsed_params: dict[str, Any] = json.loads(params)
    except json.JSONDecodeError as exc:
        raise CodeAgentError(f"Invalid --params JSON: {exc}") from exc

    request = InvocationRequest(
        request_id=uuid.uuid4().hex,
        capability_id=capability_id,
        params=parsed_params,
        caller="cli",
    )
    response, receipt = _build_registry().dispatch(request)
    _echo_response(response, receipt)
    if response.status == "error":
        raise typer.Exit(code=1)


@app.command(help="Start the LLM provider selected by the config.")
def serve(
    config_path: str | None = typer.Option(
        None,
        help="Optional path to a JSON configuration file (overrides .env settings).",
    ),
    web: bool = typer.Option(
        False,
        "--web",
        is_flag=True,
        help="Serve the web UI instead of the console loop.",
    ),
    web_host: str = typer.Option(
        "127.0.0.1",
        "--web-host",
        help="Host to bind the web UI server to.",
    ),
    web_port: int = typer.Option(
        8000,
        "--web-port",
        help="Port to bind the web UI server to.",
    ),
) -> None:
    """Start the provider selected by the config and serve prompts.

    Loads the config, constructs the provider via :func:`create_provider`
    and runs a small read‑eval‑print loop: each line of input is sent to
    ``provider.complete`` and the completion is printed. Type ``exit``,
    ``quit`` or ``q`` (or press Ctrl‑C) to end the session.

    With ``--web`` the command instead starts a local HTTP server for the
    web UI (``code_agent.ui.web``): ``GET /capabilities`` lists the
    capability catalog and ``POST /invoke`` dispatches audited invocations.
    The built React app is served from ``code_agent/ui/webapp/dist`` when
    present. The server binds to ``127.0.0.1:8000``; pass ``--web-port`` to
    change the port. No API keys or prompt content are ever logged.

    :param config_path: Path to the JSON configuration file.
    :param web: Whether to serve the web UI instead of the console loop.
    :param web_host: Host to bind the web UI server to.
    :param web_port: Port to bind the web UI server to.
    :return: None
    """
    if web:
        import uvicorn

        typer.echo(f"Web UI at http://{web_host}:{web_port}")
        uvicorn.run(
            "code_agent.ui.web:app",
            host=web_host,
            port=web_port,
            log_level="info",
        )
        return

    try:
        cfg = load_config(config_path)
        provider = create_provider(cfg)
    except Exception as exc:  # pragma: no cover - exercised via tests
        raise CodeAgentError(str(exc)) from exc

    model = getattr(provider, "model", "unknown")
    typer.echo(f"Serving provider '{provider.name}' (model: {model}).")
    typer.echo("Type 'exit', 'quit' or 'q' to end the session.")

    while True:
        try:
            prompt = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            typer.echo("\nGoodbye!")
            break
        if not prompt:
            continue
        if prompt.lower() in {"exit", "quit", "q"}:
            typer.echo("Goodbye!")
            break
        try:
            response = provider.complete([{"role": "user", "content": prompt}])
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            typer.echo(f"Error: {exc}")
            continue
        typer.echo(response)


@app.command(help="Create a new file with the supplied content.")
def create(
    file_path: Path = typer.Argument(
        ..., exists=False, help="Path to the file to create."
    ),
    content: str = typer.Option(..., help="Content to write into the file."),
    overwrite: bool = typer.Option(
        False, is_flag=True, help="Allow overwriting an existing file."
    ),
) -> None:
    """Create ``file_path`` with ``content``.

    The file is written atomically - a temporary file is written first
    and then renamed to the target path.  If the file already exists
    and ``overwrite`` is not set, the command exits with a non‑zero
    status code.

    :param file_path: Path to the file to create.
    :param content: Content to write into the file.
    :param overwrite: Allow overwriting an existing file.
    """
    try:
        if file_path.exists() and not overwrite:
            raise CodeAgentError(
                f"File '{file_path}' already exists. Use --overwrite to replace."
            )
        write_file(file_path, content)
        typer.echo(f"File written: {file_path}")
    except Exception as exc:  # pragma: no cover - exercised via tests
        raise CodeAgentError(str(exc)) from exc


@app.command(help="Append text to an existing file.")
def append(
    file_path: Path = typer.Argument(
        ..., exists=True, help="Path to the file to modify."
    ),
    content: str = typer.Option(..., help="Text to append to the file."),
):
    """Append ``content`` to ``file_path``.

    The function opens the file in append mode and writes the supplied
    content.  File locking is *not* required for the use‑cases
    envisioned in this project.

    :param file_path: Path to the file to modify.
    :param content: Text to append to the file.
    """
    try:
        file_path.write_text(
            file_path.read_text(encoding="utf-8") + content,
            encoding="utf-8",
        )
        typer.echo(f"Appended to: {file_path}")
    except Exception as exc:  # pragma: no cover - exercised via tests
        raise CodeAgentError(str(exc)) from exc


@app.command(help="Create a minimal project scaffold.")
def scaffold(
    target: Path = typer.Argument(
        ..., exists=False, help="Target directory for the scaffold."
    ),
    project_name: str = typer.Option(
        "sample_project",
        "--name",
        "-n",
        help="Project name used in scaffold files.",
    ),
    overwrite: bool = typer.Option(
        False,
        is_flag=True,
        help="Overwrite existing files in the target directory.",
    ),
) -> None:
    """Generate a project skeleton.

    Creates a minimal Python project with the following structure:
    - docs/ - Documentation directory
    - src/<project_name>/ - Source code directory
    - tests/ - Test directory
    - .GitHub/workflows/ - GitHub Actions workflows
    - requirements.txt - Project dependencies
    - README.qmd - Project documentation


    The function uses :func:`code_agent.file_generator.create_project_scaffold`.

    :param target: Target directory for the scaffold.
    :param project_name: Project name used in scaffold files.
    :param overwrite: Allow overwriting existing files.
    :return: None
    """
    try:
        create_project_scaffold(
            str(target), project_name=project_name, overwrite=overwrite
        )
        typer.echo(f"Scaffold created: {target}")
    except Exception as exc:  # pragma: no cover - exercised via tests
        raise CodeAgentError(str(exc)) from exc


@app.command(help="Convert a Python script to a Jupyter notebook.")
def py2ipynb(
    src: Path = typer.Argument(
        ..., exists=True, help="Python script to convert."
    ),
    dst: Path = typer.Argument(..., exists=False, help="Target notebook path."),
) -> None:
    """Create a minimal Jupyter notebook from a Python file.

    The notebook contains a single code cell with the full source
    code.  The function uses :func:`code_agent.file_generator.py_to_ipynb`.

    :param src: Python script to convert.
    :param dst: Target notebook path.
    :return: None
    """
    try:
        py_to_ipynb(src, dst)
        typer.echo(f"Notebook written: {dst}")
    except Exception as exc:  # pragma: no cover - exercised via tests
        raise CodeAgentError(str(exc)) from exc


@app.command(help="Generate and render Quarto documentation.")
def docs(
    output_dir: str = typer.Option(
        "docs", help="Directory to write docs into."
    ),
    overwrite: bool = typer.Option(
        True, help="Overwrite existing files in the output directory."
    ),
) -> None:
    """Generate a minimal set of QMD files and render the Quarto site.

    The function uses :func:`code_agent.file_generator.generate_quarto_docs`.

    :param output_dir: Directory to write docs into.
    :param overwrite: Overwrite existing files in the output directory.
    :return: None
    """
    try:
        generate_quarto_docs(output_dir=Path(output_dir), overwrite=overwrite)
        typer.echo(f"Docs generated in: {output_dir}")
        typer.echo("Rendering Quarto site...")
        subprocess.run(["quarto", "render"], check=True)
        typer.echo("Quarto site rendered successfully.")
    except FileNotFoundError:
        typer.echo(
            "Error: 'quarto' command not found. Please ensure Quarto is installed and in your PATH."
        )
    except Exception as exc:  # pragma: no cover - exercised via tests
        raise CodeAgentError(str(exc)) from exc


@app.command(help="Start an interactive chat session with the code agent.")
def chat(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show verbose streaming 'thinking' output from the agent.",
    ),
) -> None:
    """Start an interactive chat session with the code agent.

    :param verbose: Show verbose streaming 'thinking' output from the agent.
    :return: None
    """
    try:
        cfg = load_config()
        llm = create_llm(cfg)

        # Setup agent and tools
        agent, tools, root_dir = _setup_agent_and_tools(cfg, llm)

        # Set verbose flag on the agent so it can stream internal steps
        if hasattr(agent, "verbose"):
            agent.verbose = verbose

        _show_startup_info(root_dir, tools)

        conversation_state = {"messages": []}

        # Main chat loop
        while True:
            try:
                user_input = input("You: ").strip()

                # Handle lifecycle and simple commands separately
                cont, conversation_state = _handle_command(
                    user_input, conversation_state, tools
                )
                if not cont:
                    break
                if conversation_state is None:
                    # command handled (like 'help' or 'tools')
                    continue

                # Add user message and query the agent
                conversation_state["messages"].append(("human", user_input))
                print("\n🤖 Thinking...")
                try:
                    response = agent.invoke(conversation_state)
                    conversation_state = _display_agent_response(
                        response, conversation_state
                    )
                except Exception as e:
                    print(f"\n❌ Error processing your request: {e!s}\n")
                    continue

            except KeyboardInterrupt:
                print("\n\n👋 Session ended by user. Goodbye!")
                break
            except Exception as e:
                print(f"\n❌ An unexpected error occurred: {e!s}\n")
                continue

    except Exception as e:
        print(f"\n❌ Failed to start chat: {e}", file=sys.stderr)
        sys.exit(1)


def _setup_agent_and_tools(
    cfg: dict[str, Any], llm
) -> tuple[Any, list[BaseTool], Path]:
    """Setup the agent and tools for the chat session.

    :param cfg: Configuration dictionary.
    :param llm: Language model instance.
    :return: Tuple of (agent, tools, root_dir)
    """
    root_dir = Path(cfg.get("root_dir", ".")).resolve()
    tools = create_default_tools(root_dir=str(root_dir), llm=llm)
    agent = build_agent(llm=llm, tools=tools)
    return agent, tools, root_dir


def _show_startup_info(root_dir: Path, tools: list[BaseTool]):
    """Show startup information for the chat session.

    :param root_dir: Root directory for the agent.
    :param tools: List of available tools.
    :return: None
    """
    print("\n" + "=" * 50)
    print("=== Code Agent Chat ===")
    print("Type 'exit', 'quit', or 'q' to end the session.")
    print("Type 'help' to see available commands.\n")
    print(f"Root directory: {root_dir}")
    print(f"Available tools: {[t.name for t in tools]}")
    print("=" * 50 + "\n")


def _handle_command(
    user_input: str,
    conversation_state: dict[Any, Any] | None,
    tools: list,
) -> tuple[bool, dict[Any, Any] | None]:
    """Handle simple chat commands. Returns (continue_session, conversation_state or None).

    If a command is handled that should not continue into agent invocation (help, tools, clear),
    the function returns (True, None). If the session should end, returns (False, _).
    Otherwise, returns (True, conversation_state) to proceed.

    :param user_input: User input string.
    :param conversation_state: Current conversation state.
    :param tools: List of available tools.
    :return: Tuple of (continue_session, conversation_state or None)
    """
    if user_input.lower() in ["exit", "quit", "q"]:
        print("\nGoodbye!")
        return False, conversation_state

    if user_input.lower() == "help":
        print("\nAvailable commands:")
        print("- help: Show this help message")
        print("- exit/quit/q: End the session")
        print("- clear: Clear the conversation history")
        print("- tools: List available tools")
        print(
            "\nYou can also type natural language requests and the agent will try to help you."
        )
        return True, None

    if user_input.lower() == "clear":
        print("Conversation history cleared.\n")
        return True, None

    if user_input.lower() == "tools":
        print("\nAvailable tools:")
        for tool in tools:
            print(f"- {tool.name}: {getattr(tool, 'description', '').strip()}")
        print()
        return True, None

    if not user_input:
        return True, None

    return True, conversation_state


def _display_agent_response(response: Any, conversation_state) -> dict | Any:
    """Display the agent's response to the user.

    :param response: Response from the agent.
    :param conversation_state: Current conversation state.
    :return: Updated conversation state.
    """
    if isinstance(response, dict) and "messages" in response:
        print("\n" + "=" * 50)
        print("🛠️  Agent response:")
        messages = response["messages"]
        for msg in reversed(messages):
            if (
                isinstance(msg, (list, tuple))
                and len(msg) > 1
                and msg[0] in {"ai", "assistant"}
            ):
                print(msg[1])
                break
        print("=" * 50 + "\n")
        return response
    else:
        print("\n" + "=" * 50)
        print("🛠️  Agent response:")
        print(str(response))
        print("=" * 50 + "\n")
        return conversation_state


def main() -> None:  # pragma: no cover - thin wrapper
    """Entry point used by ``python -m code_agent.cli``.

    This function initializes and runs the Typer CLI application.

    :return: None
    """
    app()


if __name__ == "__main__":
    # This allows the script to be run directly with `python -m code_agent.cli`
    main()
