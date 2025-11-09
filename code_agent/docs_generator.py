"""
Generate Quarto (.qmd) documentation files from repository structure.
This inspects files, extracts basic metadata and writes user-friendly .qmd pages
(README.qmd, CODE_AGENT.qmd, FILES.qmd). Optionally uses an LLM to generate content.

Usage:
    from code_agent.docs_generator import generate_quarto_docs
    generate_quarto_docs(output_dir='docs', overwrite=True, use_llm=True)
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel

from .file_generator import write_file


def _gather_repo_info(root: Path) -> dict[str, list[str]]:
    """Gather information about files in the repository.

    Args:
        root: Root directory to scan

    Returns:
        Dictionary with lists of file paths by type
    """
    py_files = []
    data_files = []
    notebooks = []
    tests = []

    for p in root.rglob("*"):
        if p.is_file():
            if p.suffix == ".py":
                py_files.append(p.relative_to(root).as_posix())
            elif p.suffix in (".csv", ".tsv", ".json"):
                data_files.append(p.relative_to(root).as_posix())
            elif p.suffix in (".ipynb", ".qmd"):
                notebooks.append(p.relative_to(root).as_posix())
            elif p.parts and "tests" in p.parts:
                tests.append(p.relative_to(root).as_posix())

    return {"py_files": sorted(set(py_files)), "data_files": sorted(set(data_files)),
            "notebooks": sorted(set(notebooks)), "tests": sorted(set(tests)), }


def _render_readme_qmd(info: dict[str, list[str]]) -> str:
    """Generate content for README.qmd.

    Args:
        info: Dictionary containing file information from _gather_repo_info()

    Returns:
        String containing the README.qmd content
    """
    lines = ["---", 'title: "Project overview"', "format:", "  markdown_docs:", "    css: docs/styles/custom.css",
            "---\n", "# Project overview\n",
            "This project contains an automated pipeline and a small code agent used to create ",
            "and edit files and documentation locally (Quarto).", "\n## Contents\n",
            "* Top-level Python modules and scripts (auto-detected)", ]

    # Add Python files
    for p in info["py_files"][:50]:
        lines.append(f"- `{p}`")
    if len(info["py_files"]) > 50:
        lines.append(f"- ... ({len(info['py_files']) - 50} more)")

    # Add data files section
    lines.extend(
            ["\n## Data files\n", *(f"- `{p}`" for p in info["data_files"][:50]),
                    *(["No common data files detected in `data/`"] if not info["data_files"] else []), ]
            )

    # Add notebooks section
    lines.append("\n## Notebooks & docs\n")
    for p in info["notebooks"][:50]:
        lines.append(f"- `{p}`")

    # Add tests section
    lines.append("\n## Tests\n")
    for p in info["tests"][:50]:
        lines.append(f"- `{p}`")

    # Add how to run section
    lines.extend(
            ["\n## How to run the pipeline\n",
                    "See `RUN_MISTRAL.qmd` for detailed instructions about running the analysis pipeline.",
                    "\n## CodeAgent\n",
                    "The `code_agent` package provides commands to create files, preview edits (dry-run), ",
                    "convert `.py` -> `.ipynb`, and scaffold new projects. Use `python -m code_agent.cli --help` for "
                    "details.", ]
            )

    return "\n".join(lines)


def _render_code_agent_qmd() -> str:
    """Generate content for CODE_AGENT.qmd.

    Returns:
        String containing the CODE_AGENT.qmd content
    """
    return """---
title: "Code Agent"
format:
  markdown_docs:
    css: docs/styles/custom.css
---

# Code Agent

`code_agent` is a small local utility that provides:

- File creation and editing (atomic writes)
- Preview edits with unified diff (`--dry-run`)
- Convert Python scripts with `# %%` to notebooks
- Scaffold a new project (docs, src, tests, CI)

## CLI examples

```bash
python -m code_agent.cli --dry-run create README.qmd "# Title"
python -m code_agent.cli create docs/index.qmd "# Project"
python -m code_agent.cli py2ipynb analysis_notebook.py analysis_notebook.ipynb
python -m code_agent.cli scaffold ./myproject --name=myproject
```
"""


def _render_files_qmd(info: dict[str, list[str]]) -> str:
    """Generate content for FILES.qmd.

    Args:
        info: Dictionary containing file information from _gather_repo_info()

    Returns:
        String containing the FILES.qmd content
    """
    lines = ["---", 'title: "Files"', "format:", "  markdown_docs:", "    css: docs/styles/custom.css", "---\n",
            "# Project files\n", ]

    # Add all files
    for file_type in ["py_files", "data_files", "notebooks"]:
        for p in info[file_type]:
            lines.append(f"- `{p}`")

    return "\n".join(lines)


def generate_quarto_docs(
        output_dir: Path = "docs", overwrite: bool = True, use_llm: bool = False, llm: BaseChatModel | None = None,
        ) -> \
list[str]:
    """Generate a small set of .qmd files in `output_dir`.

    Args:
        output_dir: Directory to write documentation files
        overwrite: Whether to overwrite existing files
        use_llm: Whether to use LLM for enhanced documentation generation
        llm: Optional LLM instance to use for content generation

    Returns:
        List of paths to the generated files
    """
    root = Path(".")
    out = Path(output_dir)
    out.mkdir(parents = True, exist_ok = True)
    info = _gather_repo_info(root)
    written = []

    # Generate README.qmd
    readme_q = out / "README.qmd"
    if not overwrite and readme_q.exists():
        print(f"Skipping {readme_q} (already exists and overwrite=False)")
    else:
        if use_llm and llm:
            try:
                # Build a prompt for the LLM to generate a README
                prompt = ("You are an expert technical writer. Create a comprehensive README.qmd "
                          "for this project. Include sections for: project description, installation, "
                          "usage, and examples. Format it in Quarto markdown with a YAML header.\n\n"
                          f"Project files:\n"
                          f"Python files: {', '.join(info['py_files'][:20])}\n"
                          f"Data files: {', '.join(info['data_files'][:10])}\n"
                          f"Notebooks: {', '.join(info['notebooks'][:10])}\n")

                # Use the provided LLM instance
                content = llm.invoke(prompt)
                if hasattr(content, "content"):
                    content = content.content

                # Ensure we have a valid string
                content = str(content).strip()

                # Ensure it starts with --- for YAML front matter
                if not content.startswith("---"):
                    content = ("---\n"
                               'title: "Project Overview"\n'
                               "format:\n"
                               "  markdown_docs:\n"
                               "    css: docs/styles/custom.css\n"
                               "---\n\n" + content)

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
