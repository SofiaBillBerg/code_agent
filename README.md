# Code Agent

Sofia Billger Bergström
2025-11-10

<!-- README.md is generated from README.Rmd. Please edit that file -->

<!-- badges: start -->

[![Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/SofiaBillBerg/code_agent/main/HEAD?urlpath=%2Fdoc%2Ftree%2Fdocs%2FREADME.qmd)
<!-- badges: end -->

> A lightweight, LLM-driven assistant that can scaffold projects, edit
> files, generate documentation, and operate as an interactive chatbot.

## Quick start

``` bash
# Install dependencies (uv is recommended)
uv venv .venv
source .venv/bin/activate
uv pip install -e .

# Run the interactive agent
code-agent
```

You can now type queries, e.g.:

```cli
    > Show me a simple project scaffold
    > Add a new function to utils.py
```

## MCP and HITL Configuration

This project implements Model Context Protocol (MCP) server integration with human-in-the-loop (HITL) gating for sensitive operations:

- **MCP tool prefixing**: All 43 tools use `mcp_<server>__<tool>` naming format (e.g., `mcp_github__list_files`, `mcp_memory__search_entities`, `mcp_context7__resolve-library-id`)
- **Sensitive server gating**: `github` and `memory` servers are intercepted for explicit human approval per security policy. Read-only servers (`context7`, `docs-langchain`, `reference-langchain`) function without interruption
- **Environment variable expansion**: `${VAR}` placeholders in `.mcp.json` resolved from gitignored `.env` file at startup. Example: `${GITHUB_PERSONAL_ACCESS_TOKEN}` expands to actual token from `.env`
- **.mcp.json hardening**: Secrets replaced with `${VAR}` placeholders (`${GITHUB_PERSONAL_ACCESS_TOKEN}`, `${CONTEXT7_API_KEY}`); actual values stored in gitignored `.env` file. No hardcoded API keys or secrets
- **System prompt guardrail**: `DEFAULT_SYSTEM_PROMPT` includes MCP security policy section documenting the interception and approval flow for sensitive tools

## Package structure and class diagram
```

## Package structure and class diagram

**Package diagram**: The following diagram illustrates the main packages and their relationships within the Code Agent project.
![Package diagram](docs/visualizations/svg/packages.svg)

**Classes diagram**: The following diagram illustrates the main classes and their relationships within the Code Agent project.

![Classes diagram](docs/visualizations/svg/classes.svg)

For a deeper dive, see the following sections:

- **[CODE_AGENT](docs/CODE_AGENT.qmd)** - Core components and internals.
- **[USAGE](docs/USAGE.qmd)** - Detailed usage patterns.
- **[FILES](docs/FILES.qmd)** - File-level overview of the repo.
- **[FAQ & Troubleshooting](docs/FAQ.qmd)** - Common questions and solutions.
- **[CONTRIBUTING](docs/CONTRIBUTING.qmd)** - Guidelines for contributing to
  the project.
- **[LICENSE](./LICENSE)** - Project licensing information.
- **[ROADMAP](docs/ROADMAP.qmd)** - Future plans and development.
- **[CHANGELOG](CHANGELOG.qmd)** - Version history and changes.
- **[Agent Workflow](docs/AGENT_WORKFLOW.qmd)**
- **[Class Visualizations](docs/visualizations/svg/classes.svg)** - Visual representation of class relationships. All class diagrams are generated using [Pyreverse](https://www.logilab.org/project/pyreverse) from the [Pylint](https://pylint.pycqa.org/) project.
- **[Package Visualizations](docs/visualizations/svg/packages.svg)** - Visual representation of package relationships. All package diagrams are generated using [Pyreverse](https://www.logilab.org/project/pyreverse) from the [Pylint](https://pylint.pycqa.org/) project.
