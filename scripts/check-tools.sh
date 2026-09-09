#!/bin/bash
# media-dataset-prep/scripts/check-tools.sh
# Pipeline tool'larının durumunu kontrol eder

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
META_DIR="$(dirname "$SCRIPT_DIR")"
TOOLS_DIR="$META_DIR/tools"

echo "==============================================="
echo "  media-dataset-prep — Tool Health Check"
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
  ["00-organize"]="media_organizer"
  ["01-validate"]="validator_core"
  ["02-duplicate"]="dedup_core"
  ["03-quality"]="quality_core"
  ["04-watermark"]="watermark_core"
  ["05-resize"]="resize_core"
  ["06-caption"]="caption_core"
  ["07-golden-set"]="goldenset_core"
)

# Associative array sırasız gezilir; pipeline sırası okunabilir çıktı için sabitlenir
ORDER=(00-organize 01-validate 02-duplicate 03-quality 04-watermark 05-resize 06-caption 07-golden-set)

cd "$META_DIR"
for name in "${ORDER[@]}"; do
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
