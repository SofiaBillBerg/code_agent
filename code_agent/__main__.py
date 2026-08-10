"""Main entry point for the code_agent package.

This module provides the command-line interface for the code_agent package.
When run as `python -m code_agent`, it starts the Typer CLI defined in
:mod:`code_agent.cli`.
"""

from code_agent.cli import main


if __name__ == "__main__":
    main()
