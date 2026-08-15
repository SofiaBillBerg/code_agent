"""Generate Quarto (.qmd) documentation files from repository structure.
This inspects files, extracts basic metadata and writes user-friendly .qmd pages
(README.qmd, CODE_AGENT.qmd, FILES.qmd). Optionally uses an LLM to generate content.

Usage:
    from code_agent.tools.docs_generator import generate_quarto_docs
    generate_quarto_docs(output_dir='docs', overwrite=True, use_llm=True)
"""

from __future__ import annotations

from ast import parse
from pathlib import Path

from langchain.tools import tool


@tool(name_or_callable="generate_quarto_docs", parse_docstring=True,
    description="Generate Quarto (.qmd) documentation pages for the repository. ",
    response_format="content_and_artifact")
def generate_quarto_docs(
        output_dir: str | Path = "docs",
        overwrite: bool = False,
        use_llm: bool = True,
        root: str | Path | None = None,
) -> list[Path]:
    """Generate Quarto (.qmd) documentation pages for the repository.

    Writes README.qmd, CODE_AGENT.qmd and FILES.qmd into ``output_dir``.
    The rendering is deterministic (no LLM calls); ``use_llm`` is accepted
    for API compatibility and reserved for future LLM-enhanced generation.

    :param output_dir: Directory where the generated .qmd files are written.
    :param overwrite: When False, existing files are left untouched.
    :param use_llm: Reserved for future LLM-enhanced generation (unused today).
    :param root: Repository root to scan. Defaults to the current directory.

    :return: List of paths to the files that were written.
    """
    repo_root = Path(root) if root is not None else Path.cwd()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    info = _gather_repo_info(repo_root)
    renderers: list[tuple[str, str]] = [
        ("README.qmd", _render_readme_qmd(info)),
        ("CODE_AGENT.qmd", _render_code_agent_qmd()),
        ("FILES.qmd", _render_files_qmd(info)),
    ]

    written: list[Path] = []
    for name, content in renderers:
        target = out_dir / name
        if target.exists() and not overwrite:
            continue
        target.write_text(content, encoding="utf-8")
        written.append(target)

    return written


def _gather_repo_info(root: Path) -> dict[str, list[str]]:
    """Gather information about files in the repository.

    :param root: Root directory to scan

    :return: Dictionary with lists of file paths by type
    """
    py_files: list[str] = []
    data_files: list[str] = []
    notebooks: list[str] = []
    tests: list[str] = []

    for p in root.rglob("*"):
        if p.is_file():
            if p.suffix == ".py":
                py_files.append(p.relative_to(root).as_posix())
            elif p.suffix in {".csv", ".tsv", ".json"}:
                data_files.append(p.relative_to(root).as_posix())
            elif p.suffix in {".ipynb", ".qmd"}:
                notebooks.append(p.relative_to(root).as_posix())
            elif p.parts and "tests" in p.parts:
                tests.append(p.relative_to(root).as_posix())

    return {
        "py_files": sorted(set(py_files)),
        "data_files": sorted(set(data_files)),
        "notebooks": sorted(set(notebooks)),
        "tests": sorted(set(tests)),
    }


def _render_readme_qmd(info: dict[str, list[str]]) -> str:
    """Generate content for README.qmd.

    :param info: Dictionary containing file information from _gather_repo_info()

    :return: String containing the README.qmd content
    """
    lines = [
        "---",
        'title: "Project overview"',
        "format:",
        "  markdown_docs:",
        "    css: docs/styles/custom.css",
        "---\n",
        "# Project overview\n",
        "This project contains an automated pipeline and a small code agent used to create ",
        "and edit files and documentation locally (Quarto).",
        "\n## Contents\n",
        "* Top-level Python modules and scripts (auto-detected)",
    ]
    num_lines = 50

    # Add Python files
    for p in info["py_files"][:50]:
        lines.append(f"- `{p}`")
    if len(info["py_files"]) > num_lines:
        lines.append(f"- ... ({len(info['py_files']) - 50} more)")

    # Add data files section
    lines.extend([
        "\n## Data files\n",
        *(f"- `{p}`" for p in info["data_files"][:50]),
        *(
            ["No common data files detected in `data/`"]
            if not info["data_files"]
            else []
        ),
    ])

    # Add notebooks section
    lines.append("\n## Notebooks & docs\n")
    for p in info["notebooks"][:50]:
        lines.append(f"- `{p}`")

    # Add tests section
    lines.append("\n## Tests\n")
    for p in info["tests"][:50]:
        lines.append(f"- `{p}`")

    # Add how to run section
    lines.extend([
        "\n## How to run the pipeline\n",
        "See `RUN_MISTRAL.qmd` for detailed instructions about running the analysis pipeline.",
        "\n## CodeAgent\n",
        "The `code_agent` package provides commands to create files, preview edits (dry-run), ",
        (
            "convert `.py` -> `.ipynb`, and scaffold new projects. Use `python -m code_agent.cli --help` for "
            "details."
        ),
    ])

    return "\n".join(lines)


def _render_code_agent_qmd() -> str:
    """Generate content for CODE_AGENT.qmd.

    Dynamically inspects the code_agent module and generates documentation
    based on actual exports, architecture, and capabilities.

    :return: String containing the CODE_AGENT.qmd content
    """
    try:
        from code_agent import __all__ as exports
    except ImportError:
        exports = []

    exports_list = (
        "\n".join(f"- `{e}`" for e in sorted(exports)) if exports else ""
    )

    return f"""---
title: "Code Agent"
format:
  markdown_docs:
    css: docs/styles/custom.css
---

# Code Agent

`code_agent` is a lightweight, LLM-driven assistant that can scaffold projects,
edit files, generate documentation, and operate as an interactive chatbot.

## Quick Start

```bash
# Install dependencies (uv is recommended)
uv venv .venv
source .venv/bin/activate
uv pip install -e .[dev]

# Run the interactive agent
code-agent chat
```

## Public API

The package exports these main functions and classes:

{exports_list}

### Core Functions

```python
from code_agent import (
    load_config,           # Load configuration from .env
    create_llm,             # Create the language model instance
    build_agent,            # Build the agent runnable with tools
    create_default_tools,   # Get default set of capabilities
)

# Initialize the agent
config = load_config()  # Reads from .env or defaults
llm = create_llm(config)
agent = build_agent(llm=llm, tools=create_default_tools())

# Run the agent
response = agent.invoke({{"messages": [["human", "Add a function to utils.py"]]}})
```

## Provider Layer (LLM Agnostic)

The agent supports multiple LLM providers through a provider-agnostic abstraction:

```python
# Automatically selects provider based on environment or config
config = load_config()

# Creates ChatOpenAI, ChatOllama, or any LangChain-compatible model
llm = create_llm(config)

# Provider types
# - OllamaProvider (default): Local models via Ollama
# - OpenAIProvider: OpenAI API models
```

## File Operations

```python
from code_agent import create_file, append_file, edit_file, write_file

# Create a new file
create_file("hello.py", 'print("Hello, World!")')

# Append to existing file
append_file("notes.txt", "\\n- Added new note")

# Write with validation
write_file("config.json", {{"key": "value"}}, validate_json=True)

# Convert Python to Jupyter notebook
from code_agent import py_to_ipynb
py_to_ipynb("script.py", "notebook.ipynb")
```

## Project Scaffolding

```python
from code_agent import create_project_scaffold

# Create a new project with standard structure
create_project_scaffold(
    path="./myproject",
    name="myproject",
    author="Your Name"
)
```

Output structure:
```
myproject/
├── docs/         # Quarto documentation
├── src/          # Source code
├── tests/        # Test files
├── .github/      # GitHub Actions workflows
└── pyproject.toml
```

## Tool Capabilities

The agent provides these built-in capabilities:

| Capability | Description |
|------------|-------------|
| `search-explain` | Search codebase and explain patterns |
| `generate-test` | Create pytest test scaffolds |
| `format-code` | Format Python/R using black/ruff |
| `notebook` | Execute code in notebook environment |

All tools are registered via `CapabilityRegistry` and follow the OAP-inspired
capability-based security model with hash-chained audit logs.

## CLI Usage

```bash
# Show help
code-agent help

# Chat mode
code-agent chat

# Create file
code-agent create <path> <content>

# Edit file (dry-run preview)
code-agent edit <path> <edit>

# Convert Python to notebook
code-agent py2ipynb <input.py> <output.ipynb>

# Scaffold project
code-agent scaffold <path> --name=<project_name>
```

## Configuration

Set environment variables in `.env`:

```bash
# LLM Configuration
OLLAMA_MODEL=llama3
OPENAI_API_KEY=sk-...

# Agent Settings
CODE_AGENT_CHECKPOINT_DIR=~/.code_agent/checkpoints/
STREAM_ENABLED=true
```

See [CONFIGURATION.md](../CONFIGURATION.md) for full configuration options.

## Architecture

The agent uses a capability-based design with:

1. **Provider Layer**: Ollama/OpenAI abstraction
2. **Orchestration**: LangGraph/Runnable-based agent graph
3. **Tool Registry**: Capability registration and auditing
4. **Memory**: Chroma vector store for RAG
5. **Audit Trail**: Cryptographic receipts for all actions
"""


def _render_files_qmd(info: dict[str, list[str]]) -> str:
    """Generate content for FILES.qmd.

    :param info: Dictionary containing file information from _gather_repo_info()

    :return: String containing the FILES.qmd content
    """
    lines = [
        "---",
        'title: "Files"',
        "format:",
        "  markdown_docs:",
        "    css: docs/styles/custom.css",
        "---\n",
        "# Project files\n",
    ]

    # Add all files
    for file_type in ["py_files", "data_files", "notebooks"]:
        for p in info[file_type]:
            lines.append(f"- `{p}`")

    return "\n".join(lines)
