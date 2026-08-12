"""Command-line interface for the **code_agent** package.

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
* All file-system interactions are delegated to
  :func:`code_agent.file_generator.write_file` and
  :func:`code_agent.file_generator.py_to_ipynb`.
* ``scaffold`` uses :func:`code_agent.file_generator.create_project_scaffold`.
* ``docs`` simply calls :func:`code_agent.docs_generator.generate_quarto_docs`.
* ``capabilities`` commands build a :class:`CapabilityRegistry` populated
  with the default tools adapted via :func:`tool_to_capability`, then
  discover or dispatch through it.
* ``serve`` selects a provider via :func:`create_provider` from the config
  and runs a small read-eval-print loop against ``provider.complete``.
* Errors are wrapped in :class:`code_agent.exceptions.CodeAgentError` to

The CLI is intentionally **stateless** - it performs the requested
action and exits.  All heavy lifting is done by the helper functions.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, cast
import uuid

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
from code_agent.scaffold import create_project_scaffold
from code_agent.settings import PROJECT_ROOT
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.sessions import Connection
import typer

# Module-level Typer argument/option definitions to avoid
# "function-call-in-default-argument" lint warnings.
FILE_PATH_ARG_CREATE: Path = typer.Argument(
    ..., exists=False, help="Path to the file to create."
)
FILE_PATH_ARG_APPEND: Path = typer.Argument(
    ..., exists=True, help="Path to the file to modify."
)
PYTHON_SRC_ARG: Path = typer.Argument(
    ..., exists=True, help="Python script to convert."
)
NOTEBOOK_DST_ARG: Path = typer.Argument(
    ..., exists=False, help="Target notebook path."
)
SCAFFOLD_TARGET_ARG: Path = typer.Argument(
    ..., exists=False, help="Target directory for the scaffold."
)

app = typer.Typer(name="code_agent", help="Local LLM-driven code assistant")


# ---------------------------------------------------------------------------
# Terminal UX helpers for the chat command
# ---------------------------------------------------------------------------


def _stream_agent_response(  # ruff: ignore[complex-structure]
    agent: Any,
    messages: list[Any],
    thread_id: str,
) -> str:
    """Run the agent and stream visible progress to the terminal.

    Uses :meth:`Runnable.astream_events` when available so the user sees:
    - a spinner while the run is in flight
    - tool start/end events
    - streamed assistant tokens

    Falls back to blocking :meth:`Runnable.invoke` when the runnable does
    not support event streaming.

    :param agent: Compiled LangChain/LangGraph runnable.
    :param messages: Conversation messages to send.
    :param thread_id: Thread id for the checkpointer/config.
    :return: The final assistant text, or ``"(no text response)"`` when no
        assistant message is produced.
    """
    final_text_parts: list[str] = []
    final_messages: list[Any] = []

    spinner_running = True
    spinner_text = itertools.cycle(["Thinking", "Working", "Running"])

    def _spin() -> None:
        """Spin the spinner until the agent run completes."""
        while spinner_running:
            label = next(spinner_text)
            print(f"\r\033[K{label}...", end="", flush=True)
            time.sleep(0.35)

    thread = threading.Thread(target=_spin, daemon=True)
    thread.start()

    try:  # ruff: ignore[too-many-statements-in-try-clause]
        stream_fn = getattr(agent, "astream_events", None)
        if stream_fn is None:
            raise AttributeError("astream_events")

        for event in stream_fn(
            {"messages": messages},
            config={"configurable": {"thread_id": thread_id}},
            version="v2",
        ):
            kind = event.get("event")
            data = event.get("data", {})
            if kind == "on_tool_start":
                name = (
                    data.get("input", {}).get("query")
                    or data.get("name")
                    or "tool"
                )
                print(f"\r\033[K🔧 Tool start: {name}")
            elif kind == "on_tool_end":
                print("\r\033[K✅ Tool end")
            elif kind == "on_chat_model_stream":
                chunk = data.get("chunk")
                if chunk is not None:
                    content = getattr(chunk, "content", None)
                    if content:
                        print(content, end="", flush=True)
                        final_text_parts.append(content)
            elif kind == "on_chain_end" and data.get("output"):
                output = data["output"]
                if isinstance(output, dict):
                    final_messages = output.get("messages", [])
    except Exception:
        response = agent.invoke(
            {"messages": messages},
            config={"configurable": {"thread_id": thread_id}},
        )
        if isinstance(response, dict):
            final_messages = response.get("messages", [])
    finally:
        spinner_running = False
        thread.join(timeout=1)
        print("\r\033[K", end="", flush=True)

    if final_text_parts:
        return "".join(final_text_parts)

    if final_messages:
        for msg in reversed(final_messages):
            if hasattr(msg, "content") and getattr(msg, "content", None):
                return str(msg.content)
    return "(no text response)"


def _build_registry(root_dir: str | None = None) -> CapabilityRegistry:
    """Build a registry populated with the default tool-adapted capabilities.

    Each default tool that can be constructed without an LLM is wrapped via
    :func:`tool_to_capability` and registered under its kebab-cased id. Tools
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
    hash-chained audit :class:`Receipt`. A non-zero exit code is returned
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


def _ensure_webapp_built() -> None:
    """Build the React SPA into ``webapp/dist`` if it is missing.

    ``dist/`` is gitignored, so a fresh checkout ships no built UI until the
    frontend is compiled. When Node/npm are available we build it lazily so
    ``code-agent serve --web`` works out of the box. A missing toolchain is
    non-fatal: the API still serves, just without the static single-page app.

    :return: None
    """
    webapp_dir = Path(__file__).resolve().parent / "ui" / "webapp"
    dist_dir = webapp_dir / "dist"
    if dist_dir.is_dir():
        return
    if not webapp_dir.is_dir():
        typer.echo(
            "Note: webapp source not found; serving the API without the web UI.",
            err=True,
        )
        return
    npm = shutil.which("npm")
    if npm is None:
        typer.echo(
            "Note: webapp/dist not found and npm is not on PATH; serving the "
            "API without the web UI. Run `npm install && npm run build` in "
            "code_agent/ui/webapp to build it.",
            err=True,
        )
        return
    typer.echo(
        "Building web UI into webapp/dist (npm install && npm run build)..."
    )
    try:
        subprocess.run(
            [npm, "install"],
            cwd=str(webapp_dir),
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [npm, "run", "build"],
            cwd=str(webapp_dir),
            check=True,
            capture_output=True,
            text=True,
        )
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
    ) as exc:  # pragma: no cover - environment dependent
        detail = (getattr(exc, "stderr", "") or "").strip() or str(exc)
        typer.echo(
            f"Warning: failed to build web UI ({detail}); serving API without it.",
            err=True,
        )


def _normalize_mcp_servers(raw: str) -> list[dict[str, Any]]:
    """Parse MCP server configs from inline JSON or a file path.

    Supports:
    * Inline JSON array of server configs
    * Inline JSON object ``{ "mcpServers": { name: cfg, ... } }``
    * Path to a JSON file containing either of the above shapes
    """
    value = raw.strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, list):
        servers = parsed
    elif isinstance(parsed, dict):
        if "mcpServers" in parsed:
            servers = [
                {"name": name, **cfg}
                for name, cfg in parsed["mcpServers"].items()
            ]
        else:
            servers = [parsed]
    else:
        servers = None

    if servers is None:
        path = Path(value)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.is_file():
            typer.echo(
                f"Warning: mcp_servers file not found: {path}; skipping MCP tools.",
                err=True,
            )
            return []
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            typer.echo(
                "Warning: invalid mcp_servers file JSON; skipping MCP tools.",
                err=True,
            )
            return []

        if isinstance(parsed, list):
            servers = parsed
        elif isinstance(parsed, dict):
            if "mcpServers" in parsed:
                servers = [
                    {"name": name, **cfg}
                    for name, cfg in parsed["mcpServers"].items()
                ]
            else:
                servers = [parsed]
        else:
            servers = []

    return [cfg for cfg in servers if cfg.get("enabled") is not False]


def _to_langchain_connection(cfg: dict[str, Any]) -> dict[str, Any]:
    """Normalize an MCP server config to a langchain-mcp-adapters connection dict.

    :param cfg: A server config object.
    :return: A connection dict for langchain-mcp-adapters.
    """
    cfg = dict(cfg)
    cfg.pop("name", None)
    cfg.pop("enabled", None)

    mcp_type = cfg.pop("type", None)
    transport = None
    if mcp_type == "remote":
        transport = "http"
    elif mcp_type == "local":
        transport = "stdio"
    elif mcp_type in {"stdio", "sse", "http", "streamable_http", "websocket"}:
        transport = mcp_type

    if not transport:
        if "url" in cfg:
            transport = "http"
        elif "command" in cfg:
            transport = "stdio"

    if transport:
        cfg["transport"] = transport

    if "environment" in cfg:
        cfg["env"] = cfg.pop("environment")

    command = cfg.get("command")
    if isinstance(command, list):
        head = command[0]
        if isinstance(head, str) and " " in head:
            cfg["command"] = head.split()[0]
            cfg.setdefault("args", head.split()[1:] + command[1:])
        else:
            cfg["command"] = head
            cfg.setdefault("args", command[1:])

    if transport == "http":
        cfg.pop("oauth", None)

    return cfg


def _load_mcp_tools(cfg: dict[str, Any]) -> list[BaseTool]:
    """Load tools from configured MCP servers.

    Reads ``mcp_servers`` from *cfg*. The value may be either:

    * a JSON-encoded MCP server config object, or
    * a path to a JSON file containing a server config object.

    Tools are imported via ``langchain_mcp_adapters`` when available.
    Missing dependencies or malformed configs are logged and skipped
    so the rest of the agent still works.

    :param cfg: Configuration mapping, typically from :func:`load_config`.
    :return: A list of :class:`BaseTool` instances from MCP servers.
    """
    raw: str | None = cfg.get("mcp_servers")
    if not raw:
        return []

    servers = _normalize_mcp_servers(str(raw))  # type: ignore
    if not servers:
        return []

    try:
        from langchain_mcp_adapters.tools import load_mcp_tools
    except ImportError:
        typer.echo(
            "Warning: langchain-mcp-adapters not installed; skipping MCP tools. "
            "Install it with: pip install langchain-mcp-adapters",
            err=True,
        )
        return []

    async def _load() -> list[BaseTool]:
        """Async helper to load tools from MCP servers.

        :return: A list of :class:`BaseTool` instances from MCP servers.
        """
        tools: list[BaseTool] = []
        for server_cfg in servers:
            connection = _to_langchain_connection(server_cfg)
            transport = connection.get("transport")
            if transport not in {
                "stdio",
                "sse",
                "http",
                "streamable_http",
                "websocket",
            }:
                typer.echo(
                    f"Warning: unsupported MCP server transport {transport!r}; skipping.",
                    err=True,
                )
                continue
            server_name = server_cfg.get("name", transport)
            try:
                server_tools = await load_mcp_tools(
                    None, connection=cast(Connection, connection)
                )
            except Exception as exc:  # pragma: no cover - external dependency
                typer.echo(
                    f"Warning: failed to load MCP tools from {server_name}: {exc}",
                    err=True,
                )
                continue
            tools.extend(server_tools)
            typer.echo(
                f"Loaded {len(server_tools)} tool(s) from MCP server ({server_name})."
            )
        return tools

    try:
        return asyncio.run(_load())
    except Exception as exc:  # pragma: no cover - defensive guard
        typer.echo(f"Warning: failed to load MCP tools: {exc}", err=True)
        return []


@app.command(help="Start the LLM provider selected by the config.")
def serve(  # ruff: ignore [complex-structure]
    config_path: str | None = typer.Option(
        None,
        help="Optional path to a JSON configuration file (overrides .env settings).",
    ),
    web: bool = typer.Option(
        False,  # ruff: ignore [boolean-positional-value-in-call]
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
    and runs a small read-eval-print loop: each line of input is sent to
    ``provider.complete`` and the completion is printed. Type ``exit``,
    ``quit`` or ``q`` (or press Ctrl-C) to end the session.

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
        _ensure_webapp_built()
        import uvicorn

        typer.echo(f"Web UI at http://{web_host}:{web_port}")
        uvicorn.run(
            "code_agent.ui.web:app",
            host=web_host,
            port=web_port,
            log_level="info",
        )
        return

    try:  # ruff: ignore [too-many-statements-in-try-clause]
        from code_agent.agents.base_agent import create_default_tools
        from code_agent.main import create_llm

        cfg = load_config(config_path)
        llm = create_llm(cfg)
        tools = create_default_tools(root_dir=str(Path.cwd()), llm=llm)

        # Inject MCP tools if configured
        mcp_tools = _load_mcp_tools(cfg)
        if mcp_tools:
            tools.extend(mcp_tools)

        agent = build_agent(llm=llm, tools=tools)

        model_name = getattr(
            llm, "model", getattr(cfg, "ollama_model", "unknown")
        )
        thread_id = str(uuid.uuid4())
    except Exception as exc:  # pragma: no cover - exercised via tests
        raise CodeAgentError(f"Failed to initialize agent: {exc}") from exc

    typer.echo(
        f"Serving agent with model '{model_name}' and {len(tools)} tools."
    )
    typer.echo("Type 'exit', 'quit' or 'q' to end the session.")
    typer.echo("Type 'tools' to list available tools.")

    conversation_history: list[dict[str, Any]] = []

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
        if prompt.lower() == "tools":
            typer.echo(f"Available tools: {', '.join(t.name for t in tools)}")
            continue
        if prompt.lower() == "clear":
            conversation_history = []
            typer.echo("Conversation history cleared.")
            continue
        try:  # ruff: ignore [too-many-statements-in-try-clause]
            from langchain_core.messages import HumanMessage, SystemMessage

            messages: list[BaseMessage] = [
                SystemMessage(content=cfg.get("system_prompt", ""))
            ]
            for entry in conversation_history:
                if entry["role"] == "assistant":
                    messages.append(AIMessage(content=entry["content"]))
                elif entry["role"] == "user":
                    messages.append(HumanMessage(content=entry["content"]))
            messages.append(HumanMessage(content=prompt))

            response = agent.invoke(
                {"messages": messages},
                config={"configurable": {"thread_id": thread_id}},
            )

            # Find the last AIMessage (skip ToolMessages from intermediate steps)
            ai_messages = [
                msg
                for msg in response["messages"]
                if isinstance(msg, AIMessage)
            ]
            if not ai_messages:
                response_content = "(no text response)"
            else:
                response_content = ai_messages[-1].content or "(empty response)"

            conversation_history.append({"role": "user", "content": prompt})
            conversation_history.append({
                "role": "assistant",
                "content": response_content,
            })
        except Exception as exc:
            typer.echo(f"Error: {exc}")
            continue
        typer.echo(f"Agent: {response_content}")


@app.command(help="Create a new file with the supplied content.")
def create(
    file_path: Path = FILE_PATH_ARG_CREATE,
    content: str = typer.Option(..., help="Content to write into the file."),
    overwrite: bool = typer.Option(
        False,  # ruff: ignore [boolean-positional-value-in-call]
        is_flag=True,
        help="Allow overwriting an existing file.",
    ),
) -> None:
    """Create ``file_path`` with ``content``.

    The file is written atomically - a temporary file is written first
    and then renamed to the target path.  If the file already exists
    and ``overwrite`` is not set, the command exits with a non-zero
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
    file_path: Path = FILE_PATH_ARG_APPEND,
    content: str = typer.Option(..., help="Text to append to the file."),
) -> None:
    """Append ``content`` to ``file_path``.

    The function opens the file in append mode and writes the supplied
    content.  File locking is *not* required for the use-cases
    envisioned in this project.

    :param file_path: Path to the file to modify.
    :param content: Text to append to the file.
    :return: None
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
    target: Path = SCAFFOLD_TARGET_ARG,
    project_name: str = typer.Option(
        "sample_project",
        "--name",
        "-n",
        help="Project name used in scaffold files.",
    ),
    overwrite: bool = typer.Option(
        False,  # ruff: ignore [boolean-positional-value-in-call]
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
    src: Path = PYTHON_SRC_ARG,
    dst: Path = NOTEBOOK_DST_ARG,
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
        True,  # ruff: ignore [boolean-positional-value-in-call]
        help="Overwrite existing files in the output directory.",
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
def chat(  # ruff: ignore [complex-structure]
    verbose: bool = typer.Option(
        False,  # ruff: ignore [boolean-positional-value-in-call]
        "--verbose",
        "-v",
        help="Show verbose streaming 'thinking' output from the agent.",
    ),
) -> None:
    """Start an interactive chat session with the code agent.

    :param verbose: Show verbose streaming 'thinking' output from the agent.
    :return: None
    """
    try:  # ruff: ignore [too-many-statements-in-try-clause]
        cfg = load_config()
        llm = create_llm(cfg)

        # Setup agent and tools
        agent, tools, root_dir = _setup_agent_and_tools(cfg, llm)

        # Set verbose flag on the agent so it can stream internal steps
        if hasattr(agent, "verbose"):
            agent.verbose = verbose

        _show_startup_info(root_dir, tools)

        from langchain_core.messages import HumanMessage, SystemMessage

        system_prompt = cfg.get("system_prompt", "")
        if system_prompt:
            system_prompt = system_prompt.format(root_dir=root_dir)
        conversation_messages: list[Any] = (
            [SystemMessage(content=system_prompt)] if system_prompt else []
        )
        thread_id = str(uuid.uuid4())

        # Main chat loop
        while True:
            try:
                user_input = input("You: ").strip()
            except EOFError:
                print("\nGoodbye!")
                break
            except KeyboardInterrupt:
                print("\n\n👋 Session ended by user. Goodbye!")
                break

            try:  # ruff: ignore [too-many-statements-in-try-clause]
                # Handle lifecycle and simple commands separately
                cont, cmd_result = _handle_command(
                    user_input, conversation_messages, tools
                )
                if not cont:
                    break
                if cmd_result is not None:
                    # command handled (like 'help' or 'tools')
                    conversation_messages = cmd_result
                    continue

                # Add user message and query the agent
                conversation_messages.append(HumanMessage(content=user_input))
                print("\n🤖 Thinking...")
                try:  # ruff: ignore [too-many-statements-in-try-clause]
                    response_text = _stream_agent_response(
                        agent=agent,
                        messages=conversation_messages,
                        thread_id=thread_id,
                    )
                    print(f"\n🛠️  Agent response:\n{response_text}")
                    print("=" * 50 + "\n")
                except Exception as e:
                    print(f"\n❌ Error processing your request: {e!s}\n")
                    continue
            except Exception as e:
                print(f"\n❌ An unexpected error occurred: {e!s}\n")
                continue

    except Exception as e:
        print(f"\n❌ Failed to start chat: {e}", file=sys.stderr)
        sys.exit(1)


def _setup_agent_and_tools(
    cfg: dict[str, Any], llm: BaseChatModel
) -> tuple[Any, list[BaseTool], Path]:
    """Setup the agent and tools for the chat session.

    :param cfg: Configuration dictionary.
    :param llm: Language model instance.
    :return: Tuple of (agent, tools, root_dir)
    """
    root_dir = Path(cfg.get("root_dir", ".")).resolve()
    tools = create_default_tools(root_dir=str(root_dir), llm=llm)
    tools.extend(_load_mcp_tools(cfg))
    agent = build_agent(llm=llm, tools=tools)
    return agent, tools, root_dir


def _show_startup_info(root_dir: Path, tools: list[BaseTool]) -> None:
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
    conversation_messages: list[Any],
    tools: list,
) -> tuple[bool, list[Any] | None]:
    """Handle simple chat commands. Returns (continue_session, messages or None).

    If a command is handled that should not continue into agent invocation (help, tools, clear),
    the function returns (True, None). If the session should end, returns (False, _).
    Otherwise, returns (True, conversation_messages) to proceed.

    :param user_input: User input string.
    :param conversation_messages: Current conversation messages list.
    :param tools: List of available tools.
    :return: Tuple of (continue_session, conversation_messages or None)
    """
    if user_input.lower() in {"exit", "quit", "q"}:
        print("\nGoodbye!")
        return False, conversation_messages

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
        return True, []

    if user_input.lower() == "tools":
        print("\nAvailable tools:")
        for tool in tools:
            print(f"- {tool.name}: {getattr(tool, 'description', '').strip()}")
        print()
        return True, None

    if not user_input:
        return True, None

    return True, None


def _display_agent_response(
    response: Any, conversation_state: dict[str, Any]
) -> dict | Any:
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
