#!/bin/bash
# media-dataset-prep/scripts/update-tools.sh
# tools/'taki tüm clone'lanmış repos'ları günceller (git pull)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
META_DIR="$(dirname "$SCRIPT_DIR")"
TOOLS_DIR="$META_DIR/tools"

if [ ! -d "$TOOLS_DIR" ]; then
  echo "tools/ klasörü bulunamadı. Önce 'make install' çalıştırın."
  exit 1
fi

echo "tools/'taki repolari güncelliyor..."
echo ""

for tool_dir in "$TOOLS_DIR"/*/; do
  if [ -d "${tool_dir}.git" ]; then
    name=$(basename "$tool_dir")
    echo "↻ $name"
    git -C "$tool_dir" pull --ff-only 2>&1 | sed 's/^/    /'
    echo ""
  fi
done

echo "✓ Güncelleme tamam"
