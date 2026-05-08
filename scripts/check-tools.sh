#!/bin/bash
# dataset-prep/scripts/check-tools.sh
# Pipeline tool'larının durumunu kontrol eder

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
META_DIR="$(dirname "$SCRIPT_DIR")"
TOOLS_DIR="$META_DIR/tools"

echo "==============================================="
echo "  dataset-prep — Tool Health Check"
echo "==============================================="
echo ""

# Klasör + git durumu
echo "--- Klasör durumu (tools/) ---"
for dir in "$TOOLS_DIR"/*/; do
  if [ -d "$dir" ]; then
    name=$(basename "$dir")
    size=$(du -sh "$dir" 2>/dev/null | cut -f1)
    if [ -d "${dir}.git" ]; then
      echo "  ✓ $name  ($size)"
    else
      echo "  ⚠ $name  ($size, .git yok)"
    fi
  fi
done
echo ""

# Import edilebilirlik kontrolü
echo "--- Python import kontrolü ---"
declare -A MODULES=(
  ["00-rename"]="media_renamer"
  ["01-validate"]="src.validators.file_validator"
  ["02-duplicate"]="core"
  ["03-quality"]="src.checkers"
  ["05-resize"]="image_resizer"
)

cd "$META_DIR"
for name in "${!MODULES[@]}"; do
  module="${MODULES[$name]}"
  tool_path="$TOOLS_DIR/$name"
  if [ ! -d "$tool_path" ]; then
    echo "  ⚠ $name  (klasör yok)"
    continue
  fi
  if (cd "$tool_path" && uv run --quiet python -c "import $module" 2>/dev/null); then
    echo "  ✓ $name  ($module import OK)"
  else
    echo "  ✗ $name  ($module import başarısız)"
  fi
done

echo ""
echo "==============================================="
