#!/usr/bin/env bash
set -euo pipefail

# Build docs: default builds Quarto site to docs/markdown_docs

# Ensure Quarto is available
if ! command -v quarto >/dev/null 2>&1; then
  echo "Quarto not found in PATH. Install Quarto." >&2
else
  echo "Building Quarto site to docs/docs_web..."
  quarto render
  echo "Quarto site built to docs/html"
  quarto render --to pdf --output-dir "pdf_docs/"
  echo "Quarto pdf built to pdf_docs/docs"
  quarto render docs/README.qmd --to gfm --output README.md
  echo "README.md generated"
fi
