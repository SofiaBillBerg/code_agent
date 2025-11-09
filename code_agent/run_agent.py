"""Small wrapper that programmatically uses the code_agent CLI functions.
This is a convenience script you can import or run to invoke
the agent programmatically.
"""

from __future__ import annotations

from code_agent.scaffold import create_project_scaffold


def scaffold(root = ".", name = "project", overwrite = False):
    return create_project_scaffold(root, project_name = name, overwrite = overwrite)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument(
            "--scaffold", nargs = "?", const = ".", help = "Create scaffold at path", )
    p.add_argument("--name", default = "project")
    p.add_argument("--overwrite", action = "store_true")
    args = p.parse_args()
    if args.scaffold:
        print(scaffold(args.scaffold, name = args.name, overwrite = args.overwrite))
    else:
        print("No-op. Use --scaffold")
