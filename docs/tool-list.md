# Tool Listesi — Detay

Pipeline'ın 8 modülü (00-07).

> Her tool kendi GitHub repo'sunda yaşıyor (polyrepo). Aşağıda meta seviyede
> ne işe yaradıkları ve pipeline'daki rolleri özetlenir; **özellikler, kullanım,
> flag'ler, sürüm notları** için linklenmiş GitHub README'lerine bakın — meta
> doc her sürümde tekrar güncellenmek zorunda kalmasın.

## Pipeline Tools

### 00 — media-organizer
**GitHub:** https://github.com/faraday208/media-organizer
**Tip:** CLI + Python kütüphanesi (tek dosya: `media_organizer.py`)
**Konum:** `tools/00-organize/`

Pipeline'ın 0. adımı — dağınık dosya isimlerini düzenli numaralandırır. Tip-bazlı sequence (jpg/mp4/mp3 ayrı), EXIF/mtime'a göre kronolojik sıralama, opsiyonel recursive scan (flat/tree). Ham veri pipeline'a girmeden önce bu adımdan geçer.

**Niçin pipeline'ın 0. adımı?**
Validate (01), duplicate (02), caption (06) gibi adımlar düzenli isimlendirme bekler. `IMG_3847.jpg`, `DSC_0291.jpg`, `Screenshot 2024-01-15.png` gibi karışık isimler caption eşleştirmesi (`image_001.jpg` ↔ `image_001.txt`) zorlaştırır.

---

### 01 — media-validator
**GitHub:** https://github.com/faraday208/media-validator
**Tip:** Python kütüphanesi + CLI

Format ve dosya bütünlüğü kontrolü (MIME-type, header/EOF, format whitelist). Pipeline'ın ilk savunması — bozuk veya yanlış format dosyalar buradan geri döner.

---

### 02 — media-deduplicator
**GitHub:** https://github.com/faraday208/media-deduplicator
**Tip:** Python kütüphanesi + CLI

İki tip kopya tespiti:
- **Birebir (exact):** MD5 hash — saniyeler içinde binlerce dosya
- **Benzer (similar):** Perceptual hash (phash/ahash/dhash/whash), eşik konfigüre edilebilir

Manuel review meta'nın Gradio UI'ında yapılır.

---

### 03 — media-quality-checker
**GitHub:** https://github.com/faraday208/media-quality-checker
**Tip:** Python kütüphanesi + CLI

Görsel kalite metrikleri (blur, brightness, contrast, BPP, EXIF). 4-pass JSON sistemi. Rapor görüntüleyici meta'nın Gradio UI'ında.

---

### 04 — watermark-detection
**GitHub:** https://github.com/faraday208/watermark-detection
**Tip:** CLI + Gradio UI + YOLOv8 model
**Port:** 8300 (UI için)

YOLOv8 ile filigran tespit ve temizleme; manuel review + annotation Gradio UI üzerinden.

**Not:** Model dosyaları `~/Models/watermarks_yolov8/` altında bekleniyor.

---

### 05 — image-resizer
**GitHub:** https://github.com/faraday208/image-resizer
**Tip:** CLI (tek script)

Pillow + Lanczos algoritması ile yüksek kaliteli boyutlandırma; aspect ratio korunur.

**Bağımlılık:** Sadece Pillow.

---

### 06 — image-captioner
**GitHub:** https://github.com/faraday208/image-captioner
**Tip:** Client + Server (Ollama veya remote)

Qwen3-VL-30B ile multi-pass captioning (5-pass: saç/yüz, vücut/poz, kıyafet, sahne/teknik, doğal dil caption — 3 uzunlukta: short/medium/long). LoRA / fine-tune training için. JSON structured + caption tutarlılığı.

---

### 07 — golden-set-generator
**GitHub:** https://github.com/faraday208/golden-set-generator
**Tip:** src + Gradio UI

Pipeline'ın son aşaması — yarı-otomatik filtre + manuel cherry-pick. LoRA training öncesi ~100 mükemmel görsel seçimi için Gradio UI ile dataset review, batch label/star.

---
