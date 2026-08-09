#!/usr/bin/env bash
# Graceful mode: show errors but continue through all formatters.
# Each command runs independently; failures are collected and reported at the end.
set +e
set -o pipefail

# --- 1. Activate Virtual Environment (Robust OS detection) ---
echo "Activating virtual environment..."

if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" || "$OSTYPE" == "cygwin" ]]; then
	if [ -f ".venv/Scripts/activate" ]; then
		source .venv/Scripts/activate
	else
		echo "✗ Could not find .venv/Scripts/activate"
	fi
else
	if [ -f ".venv/bin/activate" ]; then
		source .venv/bin/activate
	else
		echo "✗ Could not find .venv/bin/activate"
	fi
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
		echo "  ✗ $label failed (exit $code) - continuing..."
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
run_step "isort" uv run isort . --float-to-top --sp pyproject.toml --gitignore
run_step "ruff format" uv run ruff format
# ruff check is non-critical: autofix what it can, never block on lint findings
# run_step "ruff check (autofix, non-blocking)" uv run ruff check code_agent --fix --extend-ignore E501 --output-file "$CODE_QUALITY_DIR"/ruff_report.txt || true

# 3. Type checking and static analysis
run_step "pyrefly check" uv run pyrefly check --remove-unused-ignores --check-unannotated-defs=true --infer-return-types=checked --use-ignore-files=true --summary=full --color=always --python-interpreter-path .venv/bin/python3 --output=.code_quality_outputs/pyrefly_report.txt || true

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
