#!/usr/bin/env bash
set -euo pipefail

# Build docs: default builds Quarto site to docs/markdown_docs
# Set USE_MKDOCS=1 to also run mkdocs build using generated markdown in docs/md_docs

# Ensure Quarto is available
if ! command -v quarto >/dev/null 2>&1; then
  echo "Quarto not found in PATH. Install Quarto or set USE_MKDOCS=1 to use MkDocs." >&2
else
  echo "Building Quarto site to docs/html..."
  quarto render . --to markdown_docs --output-dir docs/markdown_docs || true
  echo "Quarto site built to docs/html"
fi

# If USE_MKDOCS is set, run the previous markdown-generation + mkdocs build flow
if [ "${USE_MKDOCS:-}" = "1" ]; then
  echo "USE_MKDOCS=1 -> generating markdown and building MkDocs site..."
  python -m pip install --upgrade pip
  pip install mkdocs-material mkdocstrings[python]

  # Regenerate markdown from Quarto
  if [ -x "./scripts/generate_docs.sh" ]; then
    ./scripts/generate_docs.sh
  else
    bash ./scripts/generate_docs.sh
  fi

  # Defensive cleanup for md_docs
  MD_DIR="docs/md_docs"
  if [ -d "$MD_DIR" ]; then
    find "$MD_DIR" -type f -name "index.html" -exec rm -f {} \; || true
  fi

  # Ensure package is importable by mkdocstrings: install editable (if not already)
  python -m pip install -e .[dev] || true

  # Build mkdocs site into docs/site using the project's mkdocs.yml
  mkdocs build -f mkdocs.yml -d docs/site
  echo "MkDocs site built to docs/site/"
fi
