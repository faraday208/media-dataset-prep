# Tool Listesi — Detay

Pipeline'ın 8 modülü (00-07).

> Her tool kendi GitHub repo'sunda yaşıyor (polyrepo). Aşağıda meta seviyede
> ne işe yaradıkları ve pipeline'daki rolleri özetlenir; **özellikler, kullanım,
> flag'ler, sürüm notları** için linklenmiş GitHub README'lerine bakın — meta
> doc her sürümde tekrar güncellenmek zorunda kalmasın.

> UI tarafı: tüm tool'lar `media-dataset-prep/ui.py` (NiceGUI, port 8200)
> içinde in-process import edilir; tool-spesifik bağımsız Gradio UI'lar v1.0
> clean release'lerinde **silindi** (tek-UI yaklaşımı için).

## Pipeline Tools

### 00 — media-organizer
**GitHub:** https://github.com/faraday208/media-organizer
**Sürüm:** v0.5.1
**Tip:** CLI + Python kütüphanesi (tek dosya: `media_organizer.py`)
**Konum:** `tools/00-organize/`

Pipeline'ın 0. adımı — dağınık dosya isimlerini düzenli numaralandırır.
Tip-bazlı sequence (jpg/mp4/mp3 ayrı), EXIF/mtime'a göre kronolojik sıralama,
opsiyonel recursive scan (flat/tree). Mode: copy/move/in-place; copy/move
sonrası meta UI yeni output_dir'i otomatik öner. Ham veri pipeline'a girmeden
önce bu adımdan geçer.

**Niçin pipeline'ın 0. adımı?**
Validate (01), duplicate (02), caption (06) gibi adımlar düzenli isimlendirme
bekler. `IMG_3847.jpg`, `DSC_0291.jpg`, `Screenshot 2024-01-15.png` gibi karışık
isimler caption eşleştirmesi (`image_001.jpg` ↔ `image_001.txt`) zorlaştırır.

---

### 01 — media-validator
**GitHub:** https://github.com/faraday208/media-validator
**Sürüm:** v0.4.0
**Tip:** Python kütüphanesi + CLI
**Konum:** `tools/01-validate/`
**Paket:** `validator_core/`

Format ve dosya bütünlüğü kontrolü (MIME-type, header/EOF, format whitelist).
Pipeline'ın ilk savunması — bozuk veya yanlış format dosyalar buradan geri
döner. **Recursive default True** (BC change v0.4.0); tree-preserving move
(source_root mirror). 45 test.

---

### 02 — media-deduplicator
**GitHub:** https://github.com/faraday208/media-deduplicator
**Sürüm:** v1.2.2
**Tip:** Python kütüphanesi + CLI
**Konum:** `tools/02-duplicate/`
**Paket:** `dedup_core/`

İki tip kopya tespiti:
- **Birebir (exact):** MD5 hash — saniyeler içinde binlerce dosya
- **Benzer (similar):** Perceptual hash (phash/ahash/dhash/whash), eşik
  yapılandırılabilir

AI-odaklı BPP eşikleri (v1.2.0 — FULL_SCORE 0.5), `keep_strategy=best` ile
BPP-aware composite skor (artifact diskalifiye), tree-preserving move. 65 test.

**Meta UI:** Pair-wise gallery + lightbox (carousel + zoom + BPP göstergesi) —
"hangisi kalsın?" review akışı.

---

### 03 — media-quality-checker
**GitHub:** https://github.com/faraday208/media-quality-checker
**Sürüm:** v1.0.1
**Tip:** Python kütüphanesi + CLI
**Konum:** `tools/03-quality/`
**Paket:** `quality_core/`

4 composite quality check (blur / brightness / contrast / BPP). Tree-preserving
move (v1.0.1 fix). 45 test.

**Meta UI:** Rapor görüntüleyici + filter sliders + per-file detay.

---

### 04 — media-watermark-detector
**GitHub:** https://github.com/faraday208/media-watermark-detector
**Sürüm:** v1.0.1
**Tip:** Python kütüphanesi + CLI + YOLOv8 model
**Konum:** `tools/04-watermark/`
**Paket:** `watermark_core/`

YOLOv8 ile filigran tespit; bounding box + confidence. Tree-preserving move,
action layer (move/delete), undo. 34 test.

**Model konumu:** `~/Models/watermarks_yolov8/` (yapılandırılabilir — meta UI
form'unda model dropdown).

**Not:** v1.0.0 clean release'inde scope daraltıldı — inpainting + training kod
silindi, sadece detect + filter. Eski tool-içi Gradio UI silindi; meta UI'da
form-only + invalid table.

---

### 05 — media-resizer
**GitHub:** https://github.com/faraday208/media-resizer
**Sürüm:** v1.0.1
**Tip:** Python kütüphanesi + CLI
**Konum:** `tools/05-resize/`
**Paket:** `resize_core/`

Pillow + Lanczos algoritması ile yüksek kaliteli boyutlandırma; aspect ratio
korunur. Mode: copy (yeni output_dir) / in-place. Dry-run (v1.0.1 fix), undo
(copy mode'da). 20 test.

**Meta UI:** Form + dry-run preview + execute + undo. Copy mode'da yeni
output_dir handoff banner.

---

### 06 — media-captioner
**GitHub:** https://github.com/faraday208/media-captioner
**Sürüm:** v1.0.1
**Tip:** Client + Server (Ollama veya remote)
**Konum:** `tools/06-caption/`
**Paket:** `caption_core/`

Qwen3-VL-30B ile multi-pass captioning (5-pass: saç/yüz, vücut/poz, kıyafet,
sahne/teknik, doğal dil caption — 3 uzunlukta: short/medium/long). LoRA /
fine-tune training için. JSON structured + caption tutarlılığı. JSON→TXT export.
Undo: snapshot-diff (önceki pipeline'dan kalmış yabancı `.json`/`.txt`
korunur — v1.0.1 fix). 15 test.

**Meta UI:** Caption review editor — görsel + short/medium/long edit alanları +
5-pass structured veri + Save & Approve butonu. Asıl human-loop değer burada.

**Backend:** Ollama (lokal `localhost:11434` veya remote/RunPod
`OLLAMA_HOST` env ile).

---

### 07 — media-golden-set
**GitHub:** https://github.com/faraday208/media-golden-set
**Sürüm:** v1.0.1
**Tip:** Python kütüphanesi + CLI
**Konum:** `tools/07-golden-set/`
**Paket:** `goldenset_core/`

Pipeline'ın son aşaması — quality + caption-aware cherry-pick. Bucket dağılım
(face-target / character filter), recursive scan + tree-preserving copy (opt-in
`source_root`), undo çakışma guard'ı. 39 test.

**Meta UI:** Form (distribution slider + face-target + character + dry-run
preview) + selection preview gallery + bucket dağılım. Copy mode handoff banner
ile final dataset klasörüne köprü.

**Not:** v1.0.0 clean release'de tool-içi Gradio UI silindi; meta UI'da
form-only review.

---
