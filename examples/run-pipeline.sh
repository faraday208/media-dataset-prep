#!/bin/bash
# media-dataset-prep/examples/run-pipeline.sh
# End-to-end CLI pipeline örneği (sample-dataset/ üzerinde).
#
# Bu script tool'ları sırayla, dry-run modunda manuel çalıştırma örneği —
# CI veya headless senaryolar için. İnteraktif review (duplicate pair'leri,
# caption düzeltme, golden-set cherry-pick) için UI'ı kullanın:
#     uv run --group ui python ui.py
#
# Çalıştırmadan önce:  make install  (tools/ doldurulur)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
META_DIR="$(dirname "$SCRIPT_DIR")"
TOOLS_DIR="$META_DIR/tools"
SAMPLE_DIR="$SCRIPT_DIR/sample-dataset"
OUTPUT_DIR="$SCRIPT_DIR/output"
REPORTS_DIR="$SCRIPT_DIR/reports"

# Tüm tool'lar uv workspace venv'inden çalıştırılır
RUN="uv run --project $META_DIR"

mkdir -p "$OUTPUT_DIR" "$REPORTS_DIR"

echo "==============================================="
echo "  media-dataset-prep — Pipeline (dry-run)"
echo "==============================================="
echo "Giriş   : $SAMPLE_DIR"
echo "Çıkış   : $OUTPUT_DIR"
echo "Rapor   : $REPORTS_DIR"
echo ""

# Pre-check
if [ ! -d "$TOOLS_DIR/00-organize" ]; then
  echo "❌ tools/ boş. Önce 'make install' çalıştırın."
  exit 1
fi

if [ ! -d "$SAMPLE_DIR" ] || [ -z "$(ls -A "$SAMPLE_DIR" 2>/dev/null)" ]; then
  echo "⚠️  $SAMPLE_DIR boş."
  echo "    ./scripts/fetch-sample-images.sh 100  →  100 örnek görsel indir"
  echo ""
  exit 1
fi

# Hepsi --dry-run; gerçek çalıştırmada --dry-run kaldırın ve gerekli aksiyon
# flag'lerini ekleyin (--invalid-action move --invalid-dir ...).

echo "▶ Adım 00/07: media-organizer (dry-run)"
$RUN python "$TOOLS_DIR/00-organize/media_organizer.py" \
  "$SAMPLE_DIR" --prefix "sample" --dry-run
echo ""

echo "▶ Adım 01/07: media-validator (dry-run)"
$RUN python "$TOOLS_DIR/01-validate/run.py" \
  -i "$SAMPLE_DIR" \
  -o "$REPORTS_DIR/validate_report.json" \
  --invalid-action none --dry-run
echo ""

echo "▶ Adım 02/07: media-deduplicator (exact, dry-run)"
$RUN python "$TOOLS_DIR/02-duplicate/run.py" \
  -i "$SAMPLE_DIR" \
  -o "$REPORTS_DIR/duplicate_report.json" \
  --mode exact --keep-strategy largest --dry-run
echo ""

echo "▶ Adım 03/07: media-quality-checker (rapor üret)"
$RUN python "$TOOLS_DIR/03-quality/run.py" \
  -i "$SAMPLE_DIR" \
  -o "$REPORTS_DIR/quality_report.json" \
  --invalid-action none --dry-run
echo ""

echo "▶ Adım 04/07: media-watermark-detector (dry-run)"
$RUN python "$TOOLS_DIR/04-watermark/run.py" \
  -i "$SAMPLE_DIR" \
  -o "$REPORTS_DIR/watermark_report.json" \
  --invalid-action none --dry-run
echo ""

echo "▶ Adım 05/07: media-resizer (copy → output/resized, dry-run)"
$RUN python "$TOOLS_DIR/05-resize/run.py" \
  -i "$SAMPLE_DIR" \
  -o "$OUTPUT_DIR/resized" \
  --mode copy --max-width 1024 --max-height 1024 \
  --report "$REPORTS_DIR/resize_report.json" --dry-run
echo ""

echo "▶ Adım 06/07: media-captioner (Ollama gerekli — atla)"
echo "  Gerçek çalıştırma için Ollama lokal/uzaktan açık olmalı:"
echo "  $RUN python $TOOLS_DIR/06-caption/run.py \\"
echo "      -i $OUTPUT_DIR/resized \\"
echo "      --model qwen2.5-vl:7b \\"
echo "      --server localhost:11434 \\"
echo "      --report $REPORTS_DIR/caption_report.json"
echo ""

echo "▶ Adım 07/07: media-golden-set (cherry-pick, dry-run)"
echo "  Quality raporu girdi olarak verilir:"
echo "  $RUN python $TOOLS_DIR/07-golden-set/run.py \\"
echo "      -i $SAMPLE_DIR \\"
echo "      -o $OUTPUT_DIR/golden \\"
echo "      --report $REPORTS_DIR/quality_report.json \\"
echo "      --count 30 --distribution 'close-up:40,full-body:60' --dry-run"
echo ""

echo "==============================================="
echo "  ✅ Dry-run tamamlandı. Raporlar: $REPORTS_DIR"
echo ""
echo "  Gerçek çalıştırma için bu scripti baz alıp"
echo "  --dry-run flag'lerini kaldırın ve aksiyon flag'lerini ekleyin."
echo "  İnteraktif review için:  uv run --group ui python ui.py"
echo "==============================================="
