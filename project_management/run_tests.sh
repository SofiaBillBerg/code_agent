set +e
set -o pipefail
echo "Activating virtual environment..."
if [[ $OSTYPE == "msys" || $OSTYPE == "win32" || $OSTYPE == "cygwin" ]]; then
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
echo "Creating output directories..."
CODE_QUALITY_DIR=".code_quality_outputs"
mkdir -p "$CODE_QUALITY_DIR" stubs
echo "Output directories created: $CODE_QUALITY_DIR"
run_step "pytest" uv run pytest --color=yes --tb=short --junitxml="$CODE_QUALITY_DIR/pytest_report.xml"
echo ""
echo "============================================"
if [ ${#FAILURES[@]} -eq 0 ]; then
	echo "Test completed"
	exit 0
else
	echo "Completed with ${#FAILURES[@]} failure(s):"
	for f in "${FAILURES[@]}"; do
		echo "   ✗ $f"
	done
	echo ""
	echo "You can review errors above and decide which to fix, saved to $CODE_QUALITY_DIR/pytest_report.xml."
	echo "============================================"
	exit 0
fi
