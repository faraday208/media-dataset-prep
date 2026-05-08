#!/bin/bash
# media-dataset-prep/examples/run-pipeline.sh
# End-to-end pipeline örneği (sample-dataset/ üzerinde)
#
# Bu script tool'ları manuel çalıştırma örneği. İnteraktif review için Gradio UI kullanın.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
META_DIR="$(dirname "$SCRIPT_DIR")"
TOOLS_DIR="$META_DIR/tools"
SAMPLE_DIR="$SCRIPT_DIR/sample-dataset"
OUTPUT_DIR="$SCRIPT_DIR/output"

mkdir -p "$OUTPUT_DIR"

echo "==============================================="
echo "  media-dataset-prep — Pipeline Örneği"
echo "==============================================="
echo ""
echo "Giriş : $SAMPLE_DIR"
echo "Çıkış : $OUTPUT_DIR"
echo ""

# Pre-check
if [ ! -d "$TOOLS_DIR/01-validate" ]; then
  echo "❌ tools/ boş. Önce 'make install' çalıştırın."
  exit 1
fi

if [ ! -d "$SAMPLE_DIR" ] || [ -z "$(ls -A "$SAMPLE_DIR" 2>/dev/null)" ]; then
  echo "⚠️  $SAMPLE_DIR boş. Örnek görseller yok."
  echo "    Kendi resminizi koyabilirsiniz veya bu adımı atlayın."
  echo ""
fi

# (Tool'lar henüz açılmadığı için bu örnek şablon)
echo "Adım 1/7: image-validator"
echo "  cd $TOOLS_DIR/01-validate && python run.py --input $SAMPLE_DIR --output $OUTPUT_DIR/01-validated"
echo ""

echo "Adım 2/7: duplicate-image-finder"
echo "  cd $TOOLS_DIR/02-duplicate && python run.py ..."
echo ""

echo "Adım 3/7: image-quality-checker"
echo "  cd $TOOLS_DIR/03-quality && python run.py ..."
echo ""

echo "Adım 4/7: watermark-detection"
echo "  cd $TOOLS_DIR/04-watermark && python cli/detect_watermarks.py ..."
echo ""

echo "Adım 5/7: image-resizer"
echo "  cd $TOOLS_DIR/05-resize && python image_resizer.py ..."
echo ""

echo "Adım 6/7: media-captioner"
echo "  cd $TOOLS_DIR/06-caption && python client/batch_client.py ..."
echo ""

echo "Adım 7/7: golden-set-generator"
echo "  cd $TOOLS_DIR/07-golden-set && python src/universal_selector.py ..."
echo ""

echo "==============================================="
echo "  ⚠️  Bu şu anda placeholder script."
echo "  Gerçek pipeline tool'lar GitHub'a yayınlandıkça burada"
echo "  somut komutlarla doldurulacak."
echo "==============================================="
