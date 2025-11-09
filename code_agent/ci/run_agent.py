# ci/run_agent.py
"""Run agent on staged files for CI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from ..agents.base_agent import build_agent, create_default_tools
from ..main import create_llm, load_config


def get_staged_files() -> list[str]:
    """Get list of staged files from git."""
    result = subprocess.run(
            ["git", "diff", "--name-only", "--cached", "--diff-filter=ACM"], capture_output = True, text = True, )
    return [f.strip() for f in result.stdout.split("\n") if f.strip()]


def main():
    """Run agent review on staged files."""
    staged = get_staged_files()

    if not staged:
        print("No staged files to review.")
        sys.exit(0)

    print(f"Reviewing {len(staged)} staged files...")

    # Load config and create agent
    cfg = load_config()
    llm = create_llm(cfg)
    root_dir = Path(cfg.get("root_dir", ".")).resolve()
    tools = create_default_tools(root_dir = str(root_dir), llm = llm)
    agent = build_agent(llm = llm, tools = tools)

    # Create review prompt
    files_list = "\n".join(f"- {f}" for f in staged)
    prompt = f"""Review these staged files for potential issues:

{files_list}

Check for:
- Code quality issues
- Potential bugs
- Security concerns
- Best practice violations

Provide a comprehensive review."""

    # Run review
    response = agent.invoke({"input": prompt})

    # Save review
    review_path = Path(".ci/llm_review.txt")
    review_path.parent.mkdir(exist_ok = True)

    output = (response.get("output", str(response)) if isinstance(response, dict) else str(response))
    review_path.write_text(output, encoding = "utf-8")

    print(f"Review saved to {review_path}")


if __name__ == "__main__":
    main()
