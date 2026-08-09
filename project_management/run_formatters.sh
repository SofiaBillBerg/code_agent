#!/usr/bin/env bash

# Graceful mode: show errors but continue through all formatters.
# Each command runs independently; failures are collected and reported at the end.
set +e
set -o pipefail
# ensure venv is activated by activating, first check os - if windos: .venv/Scripts/activate
if [ "$(uname)" == "Darwin" ]; then
    source .venv/bin/activate
elif [ "$(expr substr $(uname -s) 1 5)" == "Linux" ]; then
    source .venv/bin/activate
elif [ "$(expr substr $(uname -s) 1 10)" == "MINGW32_NT" ]; then
    source .venv/Scripts/activated
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

echo "Starting code quality script..."
echo "Current working directory: $(pwd)"

# 1. Create necessary directories if they do not exist
echo "Creating output directories..."
mkdir -p .code_quality_outputs
mkdir -p stubs

CODE_QUALITY_DIR=".code_quality_outputs"

echo "Output directories created: $CODE_QUALITY_DIR, stubs"

# 2. Code formatting and import sorting
run_step "uv format" uv format --preview-features format-command
run_step "isort" uv tool run isort . --float-to-top --sp pyproject.toml --gitignore
run_step "ruff format" uv tool run ruff format

run_step "pytest" uv tool run pytest --color=yes --tb=short --junitxml="$CODE_QUALITY_DIR"/pytest_report.xml --html="$CODE_QUALITY_DIR"/pytest_report.html --self-contained-html
# 3. Type checking and static analysis
run_step "pyrefly check" uv tool run pyrefly check --remove-unused-ignores --check-unannotated-defs=true --infer-return-types=checked --use-ignore-files=true --summary=full --dependency-graph="$CODE_QUALITY_DIR"/pyrefly_deps_graph.json --color=always --python-interpreter-path .venv/bin/python3 --verbose --output=.code_quality_outputs/pyrefly_report.txt

run_step "pyrefly stubgen" uv tool run pyrefly stubgen --output-dir ./stubs --include-docstrings --include-private --check-unannotated-defs=true --infer-return-types=checked --use-ignore-files=true --verbose --color=always --config pyproject.toml --permissive-ignores=true

run_step "pyanalyze" uv tool run pyanalyze --config-file pyproject.toml --find-unused --find-unused-attributes --markdown-output="$CODE_QUALITY_DIR"/pyanalyze_reports_0.md --verbose --enable-all

run_step "pytype" uv tool run pytype code_agent --config pyproject.toml -v 2 --use-fiddle-overlay --precise-return --protocols --overriding-renamed-parameter-count-checks --unresolved

# 4. Style and architecture analysis (Linting & AI)
run_step "flake8" uv tool run flake8 code_agent --show-source --verbose --extend-exclude "_build, .venv, *cache*, node_modules, dist, build, .ipynb_checkpoints, *support-libs" --enable-extensions pycodestyle --format=pylint --max-line-length 80 --output-file "$CODE_QUALITY_DIR"/flake_report.txt --max-doc-length 100 --statistics --tee --color always --count --doctests

# 5. Documentation generation
run_step "pydoctor" uv tool run pydoctor -c pydoctor.ini

# 6. Dependency management
echo ""
echo "▶ Locking and exporting dependencies..."
run_step "uv lock" uv lock
run_step "uv export" uv export --format requirements.txt --output-file requirements.txt -q
run_step "pip install -e ." uv pip install -e .

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
