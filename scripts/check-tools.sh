#!/bin/bash
# dataset-prep/scripts/check-tools.sh
# Pipeline tool'larının durumunu kontrol eder

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
META_DIR="$(dirname "$SCRIPT_DIR")"
TOOLS_DIR="$META_DIR/tools"

# .env varsa yükle
if [ -f "$META_DIR/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  . "$META_DIR/.env"
  set +a
fi

echo "==============================================="
echo "  dataset-prep — Tool Health Check"
echo "==============================================="
echo ""

# Klasör kontrolleri
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

# API health check (eğer .env'de URL varsa)
echo "--- API health check ---"
declare -A APIS=(
  ["01-validate"]="${VALIDATOR_API_URL:-}"
  ["02-duplicate"]="${DUPLICATE_API_URL:-}"
  ["03-quality"]="${QUALITY_API_URL:-}"
  ["04-watermark"]="${WATERMARK_API_URL:-}"
)

for name in "${!APIS[@]}"; do
  url="${APIS[$name]}"
  if [ -z "$url" ]; then
    echo "  - $name  (URL .env'de tanımlanmamış)"
    continue
  fi
  if curl -sf --max-time 2 "$url/health" > /dev/null 2>&1; then
    echo "  ✓ $name  $url"
  else
    echo "  ✗ $name  $url  (cevap yok)"
  fi
done

echo ""
echo "==============================================="
