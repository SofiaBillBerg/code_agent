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

echo "Starting code quality script..."
echo "Current working directory: $(pwd)"

# --- 2. Create Output Directories ---
echo "Creating output directories..."
CODE_QUALITY_DIR=".code_quality_outputs"
mkdir -p "$CODE_QUALITY_DIR" stubs
echo "Output directories created: $CODE_QUALITY_DIR, stubs"

# --- 3. Code Formatting and Testing ---
# Note: Using 'uv run' instead of 'uv tool run' so tools can see your project's local dependencies.
run_step "uv format" uv format
run_step "isort" uv run isort . --float-to-top --sp pyproject.toml --gitignore
run_step "ruff format" uv run ruff format

# --- 4. Type Checking and Static Analysis ---
run_step "pyrefly check" uv run pyrefly check --remove-unused-ignores --check-unannotated-defs=true --infer-return-types=checked --use-ignore-files=true --summary=full --dependency-graph="$CODE_QUALITY_DIR/pyrefly_deps_graph.json" --color=always --python-interpreter-path .venv/bin/python3 --output="$CODE_QUALITY_DIR/pyrefly_report.txt"
run_step "pyrefly stubgen" uv run pyrefly stubgen --output-dir ./stubs --include-docstrings --include-private --check-unannotated-defs=true --infer-return-types=checked --use-ignore-files=true --color=always --config pyproject.toml --permissive-ignores=true
#run_step "pyanalyze" pyanalyze --config-file pyproject.toml --find-unused --find-unused-attributes --markdown-output="$CODE_QUALITY_DIR/pyanalyze_reports_0.md"
run_step "pytype" uv run pytype code_agent --config pyproject.toml -v 2 --use-fiddle-overlay --precise-return --protocols --overriding-renamed-parameter-count-checks --unresolved

# --- 5. Style and Architecture Analysis (Linting) ---
run_step "flake8" uv run flake8 code_agent --show-source --verbose --extend-exclude "_build,.venv,*cache*,_extensions,.*/,node_modules,dist,build,.ipynb_checkpoints,*support-libs" --enable-extensions pycodestyle --format=pylint --max-line-length 100 --extend-ignore=E501,W505 --output-file "$CODE_QUALITY_DIR/flake_report.txt" --max-doc-length 100 --statistics --tee --color always --count --doctests

# --- 6. Documentation Generation ---
run_step "pydoctor" uv run pydoctor -c pydoctor.ini

run_step "pytest" uv run pytest --color=yes --tb=short --junitxml="$CODE_QUALITY_DIR/pytest_report.xml"

# --- 7. Dependency Management ---
echo ""
#echo "▶ Locking and exporting dependencies..."
#run_step "uv lock" uv lock
#run_step "uv export" uv export --format requirements.txt --output-file requirements.txt -q
run_step "pip install -e ." uv pip install -e .

# --- Sammanfattning / Summary ---
echo ""
echo "============================================"
if [ ${#FAILURES[@]} -eq 0 ]; then
	echo "All tasks completed successfully!"
	exit 0
else
	echo "⚠ Completed with ${#FAILURES[@]} failure(s):"
	for f in "${FAILURES[@]}"; do
		echo "   ✗ $f"
	done
	echo ""
	echo "You can review errors above and decide which to fix."
	echo "============================================"
	exit 0
fi
