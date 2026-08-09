#!/usr/bin/env bash

# Graceful mode: show errors but continue through all formatters.
# Each command runs independently; failures are collected and reported at the end.
set +e
set -o pipefail
# ensure venv is activated by activating, first check os - if windows: .venv/Scripts/activate
if [ "$(uname)" == "Darwin" ]; then
    source .venv/bin/activate
elif [ "$(expr substr $(uname -s) 1 5)" == "Linux" ]; then
    source .venv/bin/activate
elif [ "$(expr substr $(uname -s) 1 10)" == "MINGW32_NT" ]; then
    source .venv/Scripts/activate
fi


FAILURES=()

run_step() {
    local label="$1"
    shift
    echo ""
    echo "▶ $label"
    if "$@"; then
        echo "  ✓ $label passed"
    else
        local code=$?
        echo "  ✗ $label failed (exit $code) — continuing..."
        FAILURES+=("$label (exit $code)")
    fi
}

echo "Starting code quality and visualization script..."
echo "Current working directory: $(pwd)"

# 1. Create necessary directories if they do not exist
echo "Creating output directories..."
mkdir -p .code_quality_outputs


CODE_QUALITY_DIR=".code_quality_outputs"

echo "Output directories created: $CODE_QUALITY_DIR"

# 2. Code formatting and import sorting
run_step "uv format" uv format --preview-features format-command
run_step "isort" uv tool run isort . --float-to-top --sp pyproject.toml --gitignore
run_step "ruff format" uv tool run ruff format
run_step "ruff check" uv tool run ruff check --fix --exit-non-zero-on-fix --output-file "$CODE_QUALITY_DIR"/ruff_report.txt 

# 3. Type checking and static analysis
run_step "pyrefly check" uv tool run pyrefly check --remove-unused-ignores --check-unannotated-defs=true --infer-return-types=checked --use-ignore-files=true --summary=full --color=always --python-interpreter-path .venv/bin/python3 --output=.code_quality_outputs/pyrefly_report.txt

# 4. Install the package
run_step "uv pip install -e ." uv pip install -e .

# --- Summary ---
echo ""
echo "============================================"
if [ ${#FAILURES[@]} -eq 0 ]; then
    echo "All tasks completed successfully!"
    exit 0
else
    echo "⚠  Completed with ${#FAILURES[@]} failure(s):"
    for f in "${FAILURES[@]}"; do
        echo "   ✗ $f"
    done
    echo ""
    echo "You can review errors above and decide which to fix."
    echo "============================================"
    # Exit 0 so the caller can proceed if they choose
    exit 0
fi
