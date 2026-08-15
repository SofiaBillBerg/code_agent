"""Generate Quarto (.qmd) documentation files from repository structure.
This inspects files, extracts basic metadata and writes user-friendly .qmd pages
(README.qmd, CODE_AGENT.qmd, FILES.qmd). Optionally uses an LLM to generate content.

Usage:
    from code_agent.docs_generator import generate_quarto_docs
    generate_quarto_docs(output_dir='docs', overwrite=True, use_llm=True)
"""

from __future__ import annotations

from pathlib import Path

from .file_generator import write_file

from langchain.chat_models import BaseChatModel

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
        from code_agent import (
            build_agent,
            create_default_tools,
            create_llm,
            create_project_scaffold,
            load_config,
        )
    except ImportError:
        exports = []

    exports_list = "\n".join(f"- `{e}`" for e in sorted(exports)) if exports else ""

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


def generate_quarto_docs(
        output_dir: Path = Path("docs"),
        overwrite: bool = False,
        use_llm: bool = False,
        llm: BaseChatModel | None = None,
) -> list[str]:
    """Generate a small set of .qmd files in `output_dir`.

    :param output_dir: Directory to write documentation files
    :param overwrite: Whether to overwrite existing files
    :param use_llm: Whether to use LLM for enhanced documentation generation
    :param llm: Optional LLM instance to use for content generation

    :return: List of paths to the generated files
    """
    root = Path()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    info = _gather_repo_info(root)
    written: list[str] = []

    # Generate README.qmd
    readme_q = out / "README.qmd"
    if not overwrite and readme_q.exists():
        print(f"Skipping {readme_q} (already exists and overwrite=False)")
    elif use_llm and llm:
        try:
            # Build a prompt for the LLM to generate a README
            prompt = (
                "You are an expert technical writer. Create a comprehensive README.qmd "
                "for this project. Include sections for: project description, installation, "
                "usage, and examples. Format it in Quarto markdown with a YAML header.\n\n"
                f"Project files:\n"
                f"Python files: {', '.join(info['py_files'][:20])}\n"
                f"Data files: {', '.join(info['data_files'][:10])}\n"
                f"Notebooks: {', '.join(info['notebooks'][:10])}\n"
            )

            # Use the provided LLM instance
            content = llm.invoke(prompt)
            if hasattr(content, "content"):
                content = content.content

            # Ensure we have a valid string
            content = str(content).strip()

            # Ensure it starts with --- for YAML front matter
            if not content.startswith("---"):
                content = (
                        "---\n"
                        'title: "Project Overview"\n'
                        "format:\n"
                        "  markdown_docs:\n"
                        "    css: docs/styles/custom.css\n"
                        "---\n\n" + content
                )

            write_file(readme_q, content)
            written.append(str(readme_q))

        except Exception as e:
            print(f"Error generating README with LLM: {e}")
            print("Falling back to template-based generation")
            content = _render_readme_qmd(info)
            write_file(readme_q, content)
            written.append(str(readme_q))
    else:
        content = _render_readme_qmd(info)
        write_file(readme_q, content)
        written.append(str(readme_q))

    # Generate CODE_AGENT.qmd
    code_agent_q = out / "CODE_AGENT.qmd"
    if not overwrite and code_agent_q.exists():
        print(f"Skipping {code_agent_q} (already exists and overwrite=False)")
    else:
        content = _render_code_agent_qmd()
        write_file(code_agent_q, content)
        written.append(str(code_agent_q))

    # Generate FILES.qmd
    files_q = out / "FILES.qmd"
    if not overwrite and files_q.exists():
        print(f"Skipping {files_q} (already exists and overwrite=False)")
    else:
        content = _render_files_qmd(info)
        write_file(files_q, content)
        written.append(str(files_q))

    return written
