#!/bin/bash
# media-dataset-prep/scripts/fetch-sample-images.sh
# loremflickr.com'dan SFW, telif-sorunsuz (Flickr CC) insan fotoğrafları indirir.
# Kadınlı/erkekli, portre/full-body/oturan çeşitli görseller — pipeline test seti için.
#
# Kullanım:  ./scripts/fetch-sample-images.sh [adet]   (varsayılan 100)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="$(dirname "$SCRIPT_DIR")/examples/sample-dataset"
COUNT="${1:-100}"

mkdir -p "$OUT_DIR"

# keyword kombinasyonları — çeşitlilik için
KEYWORDS=(
  "portrait,woman" "portrait,man" "person,sitting" "people"
  "model,fashion" "man,street" "woman,outdoor" "person,standing"
  "portrait" "person,smile" "woman,cafe" "man,portrait"
  "people,group" "person,park" "woman,fashion" "man,sitting"
)
# boyut presetleri — resize testi için farklı çözünürlükler
DIMS=("800/600" "640/800" "1024/768" "600/600" "1200/800" "480/640")

echo "loremflickr → $OUT_DIR  ($COUNT görsel)"

fetch_one() {
  local i="$1"
  local kw="${KEYWORDS[$((i % ${#KEYWORDS[@]}))]}"
  local dim="${DIMS[$((i % ${#DIMS[@]}))]}"
  local out
  out="$(printf '%s/img_%03d.jpg' "$OUT_DIR" "$i")"
  # ?lock=i → her görsel deterministik biçimde farklı
  curl -sL --max-time 30 "https://loremflickr.com/${dim}/${kw}?lock=${i}" -o "$out"
  if [ -s "$out" ] && file -b --mime-type "$out" | grep -q '^image/'; then
    echo "  ok  img_$(printf '%03d' "$i").jpg  [$kw  $dim]"
  else
    rm -f "$out"
    echo "  FAIL img_$(printf '%03d' "$i").jpg  [$kw]"
  fi
}
export -f fetch_one
export OUT_DIR
export KEYWORDS_STR="${KEYWORDS[*]}"
# arrays export edilemez → alt-shell'de yeniden kur
fetch_wrap() {
  IFS=' ' read -r -a KEYWORDS <<< "$KEYWORDS_STR"
  DIMS=("800/600" "640/800" "1024/768" "600/600" "1200/800" "480/640")
  fetch_one "$1"
}
export -f fetch_wrap

seq 1 "$COUNT" | xargs -P 8 -I {} bash -c 'fetch_wrap "$@"' _ {}

DOWNLOADED="$(find "$OUT_DIR" -name 'img_*.jpg' -type f | wc -l)"
echo ""
echo "Tamamlandı: $DOWNLOADED / $COUNT görsel  →  $OUT_DIR"
