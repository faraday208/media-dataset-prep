#!/bin/bash
# dataset-prep/scripts/install-tools.sh
# Pipeline tool'larını tools/ altına yerleştirir
#
# Kullanım:
#   ./scripts/install-tools.sh           # default: github (clone)
#   ./scripts/install-tools.sh github    # GitHub'dan clone
#   ./scripts/install-tools.sh local     # Yerel ai-visual-lab/dataset-prep/'tan symlink
#   ./scripts/install-tools.sh hybrid    # Önce GitHub dene, yoksa yerel symlink

set -euo pipefail

MODE="${1:-github}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
META_DIR="$(dirname "$SCRIPT_DIR")"
TOOLS_DIR="$META_DIR/tools"

# Yerel geliştirme modu için tool'ların kardeş klasörleri
# Her tool kendi başına bağımsız repo (gelecekte github.com/<user>/<repo>)
LOCAL_BASE="/home/ai/Workspace"

mkdir -p "$TOOLS_DIR"

# Pipeline aşaması → (yerel klasör adı | GitHub URL) eşleşmesi
declare -A LOCAL_PATHS=(
  ["00-rename"]="$LOCAL_BASE/media-renamer"
  ["01-validate"]="$LOCAL_BASE/image-validator"
  ["02-duplicate"]="$LOCAL_BASE/duplicate-image-finder"
  ["03-quality"]="$LOCAL_BASE/image-quality-checker"
  ["04-watermark"]="$LOCAL_BASE/watermark-detection"
  ["05-resize"]="$LOCAL_BASE/image-resizer"
  ["06-caption"]="$LOCAL_BASE/image-captioner"
  ["07-golden-set"]="$LOCAL_BASE/golden-set-generator"
)

declare -A GITHUB_URLS=(
  ["00-rename"]="https://github.com/faraday208/media-renamer.git"
  ["01-validate"]="https://github.com/faraday208/image-validator.git"
  ["02-duplicate"]="https://github.com/faraday208/duplicate-image-finder.git"
  ["03-quality"]="https://github.com/faraday208/image-quality-checker.git"
  ["04-watermark"]="https://github.com/faraday208/watermark-detection.git"
  ["05-resize"]="https://github.com/faraday208/image-resizer.git"
  ["06-caption"]="https://github.com/faraday208/image-captioner.git"
  ["07-golden-set"]="https://github.com/faraday208/golden-set-generator.git"
)

echo "==============================================="
echo "  dataset-prep — Tool Installation"
echo "  Mode: $MODE"
echo "==============================================="
echo ""

setup_local() {
  local name="$1"
  local source_path="${LOCAL_PATHS[$name]}"
  local target="$TOOLS_DIR/$name"

  if [ ! -d "$source_path" ]; then
    echo "  ⚠ Yerel kaynak yok: $source_path"
    return 1
  fi

  # Eski symlink veya klasör varsa kaldır
  if [ -L "$target" ] || [ -d "$target" ]; then
    rm -rf "$target"
  fi

  ln -s "$source_path" "$target"
  echo "  ✓ $name  →  $source_path  (symlink)"
}

setup_github() {
  local name="$1"
  local url="${GITHUB_URLS[$name]}"
  local target="$TOOLS_DIR/$name"

  if [ -d "$target/.git" ]; then
    echo "  ↻ $name  (clone'lu, güncelleniyor)"
    git -C "$target" pull --ff-only 2>&1 | sed 's/^/      /' || return 1
  elif [ -L "$target" ]; then
    echo "  ⚠ $name  (symlink var, GitHub clone için önce kaldır)"
    return 1
  else
    echo "  ↓ $name  (GitHub clone)"
    if git clone --quiet "$url" "$target" 2>&1; then
      echo "      ✓ clone tamam"
    else
      echo "      ❌ clone başarısız (repo henüz GitHub'da olmayabilir)"
      return 1
    fi
  fi
}

failures=0
order=("00-rename" "01-validate" "02-duplicate" "03-quality" "04-watermark" "05-resize" "06-caption" "07-golden-set")

for name in "${order[@]}"; do
  case "$MODE" in
    local)
      setup_local "$name" || ((failures++)) || true
      ;;
    github)
      setup_github "$name" || ((failures++)) || true
      ;;
    hybrid)
      # Önce GitHub dene, başarısız olursa yerele düş
      if ! setup_github "$name" 2>/dev/null; then
        echo "  → GitHub'dan alınamadı, yerele düşülüyor"
        setup_local "$name" || ((failures++)) || true
      fi
      ;;
    *)
      echo "❌ Bilinmeyen mod: $MODE"
      echo "   Kullan: local | github | hybrid"
      exit 1
      ;;
  esac
done

echo ""
echo "==============================================="
if [ "$failures" -eq 0 ]; then
  echo "  ✅ Tüm tool'lar tools/ altında hazır"
else
  echo "  ⚠ $failures tool için sorun çıktı"
fi
echo "==============================================="
