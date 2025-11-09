"""Command‑line interface for the **code_agent** package.

The CLI is intentionally small – it only exposes the most common
operations that a developer would want when working in a local
repository:

* ``create`` – create a new file with supplied content.
* ``append`` – append to an existing file.
* ``scaffold`` – generate a minimal project structure.
* ``py2ipynb`` – convert a Python script to a Jupyter notebook.
* ``docs`` – generate Quarto documentation for the current tree.

Implementation details
----------------------
* Uses **Typer** for argument parsing – it provides a pleasant
  developer experience (automatic ``--help`` generation, type checking
  and rich error messages).
* All file‑system interactions are delegated to
  :func:`code_agent.file_generator.write_file` and
  :func:`code_agent.file_generator.py_to_ipynb`.
* ``scaffold`` uses :func:`code_agent.file_generator.create_project_scaffold`.
* ``docs`` simply calls :func:`code_agent.docs_generator.generate_quarto_docs`.
* Errors are wrapped in :class:`code_agent.exceptions.CodeAgentError` to

The CLI is intentionally **stateless** – it performs the requested
action and exits.  All heavy lifting is done by the helper functions.
"""

import subprocess
from pathlib import Path

import typer

from code_agent.agents.base_agent import build_agent, create_default_tools
from code_agent.docs_generator import generate_quarto_docs
from code_agent.exceptions import CodeAgentError
from code_agent.file_generator import py_to_ipynb, write_file
from code_agent.main import create_llm, load_config
from code_agent.scaffold import create_project_scaffold

app = typer.Typer(name = "code_agent", help = "Local LLM‑driven code assistant")


@app.command(help = "Create a new file with the supplied content.")
def create(
        file_path: Path = typer.Argument(
                ..., exists = False, help = "Path to the file to create."
                ), content: str = typer.Option(..., help = "Content to write into the file."),
        overwrite: bool = typer.Option(
                False, is_flag = True, help = "Allow overwriting an existing file."
                ), ):
    """Create ``file_path`` with ``content``.

    The file is written atomically – a temporary file is written first
    and then renamed to the target path.  If the file already exists
    and ``overwrite`` is not set, the command exits with a non‑zero
    status code.
    """

    try:
        if file_path.exists() and not overwrite:
            raise CodeAgentError(
                    f"File '{file_path}' already exists. Use --overwrite to replace."
                    )
        write_file(file_path, content)
        typer.echo(f"File written: {file_path}")
    except Exception as exc:  # pragma: no cover – exercised via tests
        raise CodeAgentError(str(exc)) from exc


@app.command(help = "Append text to an existing file.")
def append(
        file_path: Path = typer.Argument(
                ..., exists = True, help = "Path to the file to modify."
                ), content: str = typer.Option(..., help = "Text to append to the file."), ):
    """Append ``content`` to ``file_path``.

    The function opens the file in append mode and writes the supplied
    content.  File locking is *not* required for the use‑cases
    envisioned in this project.
    """

    try:
        file_path.write_text(
                file_path.read_text(encoding = "utf-8") + content, encoding = "utf-8", )
        typer.echo(f"Appended to: {file_path}")
    except Exception as exc:  # pragma: no cover – exercised via tests
        raise CodeAgentError(str(exc)) from exc


@app.command(help = "Create a minimal project scaffold.")
def scaffold(
        target: Path = typer.Argument(
                ..., exists = False, help = "Target directory for the scaffold."
                ), project_name: str = typer.Option(
                "sample_project", "--name", "-n", help = "Project name used in scaffold files.", ),
        overwrite: bool = typer.Option(
                False, is_flag = True, help = "Overwrite existing files in the target directory.", ), ):
    """Generate a project skeleton.

    Creates a minimal Python project with the following structure:
    - docs/ - Documentation directory
    - src/<project_name>/ - Source code directory
    - tests/ - Test directory
    - .GitHub/workflows/ - GitHub Actions workflows
    - requirements.txt - Project dependencies
    - README.qmd - Project documentation
    """

    try:
        create_project_scaffold(
                str(target), project_name = project_name, overwrite = overwrite
                )
        typer.echo(f"Scaffold created: {target}")
    except Exception as exc:  # pragma: no cover – exercised via tests
        raise CodeAgentError(str(exc)) from exc


@app.command(help = "Convert a Python script to a Jupyter notebook.")
def py2ipynb(
        src: Path = typer.Argument(
                ..., exists = True, help = "Python script to convert."
                ), dst: Path = typer.Argument(
                ..., exists = False, help = "Target notebook path."
                ), ):
    """Create a minimal Jupyter notebook from a Python file.

    The notebook contains a single code cell with the full source
    code.  The function uses :func:`code_agent.file_generator.py_to_ipynb`.
    """

    try:
        py_to_ipynb(src, dst)
        typer.echo(f"Notebook written: {dst}")
    except Exception as exc:  # pragma: no cover – exercised via tests
        raise CodeAgentError(str(exc)) from exc


@app.command(help = "Generate and render Quarto documentation.")
def docs(
        output_dir: str = typer.Option(
                "docs", help = "Directory to write docs into."
                ), overwrite: bool = typer.Option(
                True, help = "Overwrite existing files in the output directory."
                ), ):
    """Generate a minimal set of QMD files and render the Quarto site."""

    try:
        generate_quarto_docs(output_dir = Path(output_dir), overwrite = overwrite)
        typer.echo(f"Docs generated in: {output_dir}")
        typer.echo("Rendering Quarto site...")
        subprocess.run(["quarto", "render"], check = True)
        typer.echo("Quarto site rendered successfully.")
    except FileNotFoundError:
        typer.echo(
                "Error: 'quarto' command not found. Please ensure Quarto is installed and in your PATH."
                )
    except Exception as exc:  # pragma: no cover – exercised via tests
        raise CodeAgentError(str(exc)) from exc


@app.command(help = "Start an interactive chat session with the code agent.")
def chat(
        verbose: bool = typer.Option(
                False, "--verbose", "-v",
                help = "Show verbose streaming 'thinking' output from the agent.", ), ) -> None:
    """Start an interactive chat session with the code agent."""
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
                    print(f"\n❌ Error processing your request: {str(e)}\n")
                    continue

            except KeyboardInterrupt:
                print("\n\n👋 Session ended by user. Goodbye!")
                break
            except Exception as e:
                print(f"\n❌ An unexpected error occurred: {str(e)}\n")
                continue

    except Exception as e:
        print(f"\n❌ Failed to start chat: {e}", file = sys.stderr)
        sys.exit(1)


def _setup_agent_and_tools(cfg, llm):
    root_dir = Path(cfg.get("root_dir", ".")).resolve()
    tools = create_default_tools(root_dir = str(root_dir), llm = llm)
    agent = build_agent(llm = llm, tools = tools)
    return agent, tools, root_dir


def _show_startup_info(root_dir, tools):
    print("\n" + "=" * 50)
    print("=== Code Agent Chat ===")
    print("Type 'exit', 'quit', or 'q' to end the session.")
    print("Type 'help' to see available commands.\n")
    print(f"Root directory: {root_dir}")
    print(f"Available tools: {[t.name for t in tools]}")
    print("=" * 50 + "\n")


def _handle_command(user_input: str, conversation_state: dict, tools: list):
    """Handle simple chat commands. Returns (continue_session, conversation_state or None).

    If a command is handled that should not continue into agent invocation (help, tools, clear),
    the function returns (True, None). If the session should end, returns (False, _).
    Otherwise, returns (True, conversation_state) to proceed.
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


def _display_agent_response(response, conversation_state):
    if isinstance(response, dict) and "messages" in response:
        print("\n" + "=" * 50)
        print("🛠️  Agent response:")
        messages = response["messages"]
        for msg in reversed(messages):
            if (isinstance(msg, (list, tuple)) and len(msg) > 1 and msg[0] in ["ai", "assistant"]):
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


# Register the chat command
app.command(help = "Start an interactive chat session with the code agent")(chat)


def main() -> None:  # pragma: no cover – thin wrapper
    """Entry point used by ``python -m code_agent.cli``.

    This function initializes and runs the Typer CLI application.
    """
    app()


if __name__ == "__main__":
    # This allows the script to be run directly with `python -m code_agent.cli`
    import sys

    main()
