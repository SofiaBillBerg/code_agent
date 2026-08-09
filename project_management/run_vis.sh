#!/usr/bin/env bash

# Graceful mode: show errors but continue through all visualization steps.
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

echo "Starting code visualization script..."
# Echo the current working directory
echo "Current working directory: $(pwd)"

# 1. Create necessary directories if they do not exist
echo "Creating output directories..."
mkdir -p docs/visualizations
mkdir -p docs/visualizations/svg
RAW_VISUALIZATION_DIR="./docs/visualizations"
SVG_DIR="$RAW_VISUALIZATION_DIR/svg"

echo "Output directories created: $RAW_VISUALIZATION_DIR"

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
        echo "  ✗ $label failed (exit $code) - continuing..."
        FAILURES+=("$label (exit $code)")
    fi
}

# 2. Package-level diagrams
run_vis_step "Package all-classes diagram" pyreverse code_agent -d "$RAW_VISUALIZATION_DIR" -A -f ALL --colorized -a 10 --color-palette "$PALETTE" -o mmd

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

    if pyreverse code_agent -S -A -f ALL -a 10 -c "$full_class_name" -d "$RAW_VISUALIZATION_DIR" --colorized --color-palette "$PALETTE" -o mmd; then
      successful_classes+=("$full_class_name")
      echo "    ✓ $full_class_name passed"
    else
      failed_classes+=("$full_class_name")
      echo "    ✗ $full_class_name failed - continuing..."
    fi


  done < <(grep -oP '^class \K\w+' "$file" || true)

done < <(find code_agent -name "*.py" -not -path "*/.*" -print0)

echo ""
echo "  Per-class results: ${#successful_classes[@]} succeeded, ${#failed_classes[@]} failed"

# format the generated mermaid files in the RAW_VISUALIZATION_DIR and save to SVG_DIR
for mermaid_file in "$RAW_VISUALIZATION_DIR"/*.mmd; do
    if [ -f "$mermaid_file" ]; then
        echo "  ▶ Formatting $mermaid_file"
        if ! mermaidfmt -w "$mermaid_file"; then
            echo "    ✗ Formatting failed for $mermaid_file - continuing..."
            FAILURES+=("Formatting failed for $mermaid_file")
        fi
    fi
done

  # convert the generated mermaid file to SVG av save to SVG_DIR
for mermaid_file in "$RAW_VISUALIZATION_DIR"/*.mmd; do
    if [ -f "$mermaid_file" ]; then
        svg_file="$SVG_DIR/$(basename "$mermaid_file" .mmd).svg"
        echo "  ▶ Converting $mermaid_file to $svg_file"
        if ! mmdc -i "$mermaid_file" -o "$svg_file"; then
            echo "    ✗ Conversion failed for $mermaid_file - continuing..."
            FAILURES+=("Conversion failed for $mermaid_file")
        fi
    fi
done

# Add per-class failures to global tracker
if [ ${#failed_classes[@]} -gt 0 ]; then
    FAILURES+=("Per-class diagrams (${#failed_classes[@]} failures)")
fi


# Format all project-level markdown files with mermaid diagrams
while IFS= read -r -d '' file; do
  find "$file" -type f -name "*.md" -print0 ! -path '*/.git/*' ! -path '*/.*/*' ! -path '*/lib/*' ! -path '*/dist/*' ! -path '*/win/*' ! -path '*/node_modules/*' ! -path '.venv/*' ! -path '*/build/*' | while read -r file; do
    echo "  ▶ Formatting $file"
    if ! mermaidfmt -w "$file"; then
      echo "    ✗ Formatting failed for $file - continuing..."
      FAILURES+=("Formatting failed for $file")
    fi
  done
done < <(find . -type d -name "docs" -print0)

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
