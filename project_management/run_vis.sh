#!/usr/bin/env bash

# Graceful mode: show errors but continue through all visualization steps.
# Each command runs independently; failures are collected and reported at the end.
set +e
set -o pipefail

echo "Starting code visualization script..."
# Echo the current working directory
echo "Current working directory: $(pwd)"

# 1. Create necessary directories if they do not exist
echo "Creating output directories..."
mkdir -p docs/visualizations

VISUALIZATION_DIR="./docs/visualizations"

echo "Output directories created: $VISUALIZATION_DIR"

# Common color palette for all diagrams
PALETTE="[lavender,blue,purple,pink,ghostwhite,mediumorchid,coral,orangered,goldenrod,darkorange,lemonchiffon,gold,yellow,palegoldenrod]"
# "[#f3e5f5,#ffb6c1,#db7093,#e0b0ff,#9370db,#f8f0fe,#ba55d3,#ff7f50,#ff4500,#ffcc33,#ff9900,#fffacd,#ffcc00,#ffff99,#ffd700]"

# Track failures across all steps
FAILURES=()

# Helper function to run a step and track failures
run_vis_step() {
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

# 2. Package-level diagrams
run_vis_step "Package all-classes diagram" pyreverse code_agent -d "$VISUALIZATION_DIR" -A -f ALL --colorized -a 10 --color-palette "$PALETTE" -o mmd

# 3. Per-class diagrams
echo ""
echo "▶ Per-class diagrams"
failed_classes=()
successful_classes=()

while IFS= read -r -d '' file; do
  module_name=$(echo "$file" | sed -E 's|^code_agent/||;s|\.py$||;s|/|.|g')

  while IFS= read -r class_name; do
    if [ -z "$class_name" ]; then
      continue
    fi

    full_class_name="code_agent.${module_name}.${class_name}"
    echo "  ▶ $full_class_name"

    if pyreverse code_agent -S -A -f ALL -a 10 -c "$full_class_name" -d "$VISUALIZATION_DIR" --colorized --color-palette "$PALETTE" -o mmd; then
      successful_classes+=("$full_class_name")
      echo "    ✓ $full_class_name passed"
    else
      failed_classes+=("$full_class_name")
      echo "    ✗ $full_class_name failed — continuing..."
    fi

  done < <(grep -oP '^class \K\w+' "$file" || true)

done < <(find code_agent -name "*.py" -not -path "*/.*" -print0)

echo ""
echo "  Per-class results: ${#successful_classes[@]} succeeded, ${#failed_classes[@]} failed"

# Add per-class failures to global tracker
if [ ${#failed_classes[@]} -gt 0 ]; then
    FAILURES+=("Per-class diagrams (${#failed_classes[@]} failures)")
fi

# Format all mermaid and markdown files
find . -name "*.md" -exec mermaidfmt -w {} \;
find . -name "*.mmd" -exec mermaidfmt -w {} \;
find "$VISUALIZATION_DIR" -name "*.mmd" -exec mmdc --input {} -o {}.svg \;



# --- Summary ---
echo ""
echo "=========================================="
echo "Visualization Generation Summary"
echo "=========================================="
if [ ${#FAILURES[@]} -eq 0 ]; then
    echo "All visualization tasks completed successfully!"
else
    echo "⚠  Completed with ${#FAILURES[@]} failure(s):"
    for f in "${FAILURES[@]}"; do
        echo "   ✗ $f"
    done
    echo ""
    echo "You can review errors above and decide which to fix."
fi
echo "=========================================="

# Exit 0 so the caller can proceed if they choose
exit 0
