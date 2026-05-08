# Tool Listesi — Detay

Pipeline'ın 8 modülü (00-07).

## Pipeline Tools

### 00 — media-organizer
**GitHub:** https://github.com/faraday208/media-organizer
**Tip:** CLI + Python kütüphanesi (tek dosya: `media_organizer.py`)
**Konum:** `tools/00-organize/`

Pipeline'ın 0. adımı — dağınık dosya isimlerini düzenli numaralandırır. Ham veri pipeline'a girmeden önce bu adımdan geçer.

**Özellikler:**
- Tip-bazlı sayma (jpg ayrı sequence, mp4 ayrı, mp3 ayrı)
- Tarih sıralı (oluşturma zamanına göre — EXIF DateTimeOriginal veya mtime)
- Dry-run modu (`--dry-run`)
- JSON rapor (`rename_report.json`)
- Sıfır bağımlılık (Python stdlib only)

**Kullanım:**
```bash
python tools/00-organize/media_organizer.py /path/to/folder --prefix "MyDataset" --dry-run
```

**Niçin pipeline'ın 0. adımı?**
Validate (01), duplicate (02), caption (06) gibi adımlar düzenli isimlendirme bekler. `IMG_3847.jpg`, `DSC_0291.jpg`, `Screenshot 2024-01-15.png` gibi karışık isimler caption eşleştirmesi (`image_001.jpg` ↔ `image_001.txt`) zorlaştırır.

---

### 01 — image-validator
**GitHub:** https://github.com/faraday208/image-validator
**Tip:** Python kütüphanesi + CLI

Format ve dosya bütünlüğü kontrolü. Pipeline'ın ilk savunması — bozuk veya yanlış format dosyalar buradan geri döner.

**Özellikler:**
- MIME-type doğrulama
- Header / EOF kontrolü (corrupt image detection)
- Format whitelist (jpg, png, webp, tiff, vb.)
- Batch / async tarama

---

### 02 — duplicate-image-finder
**GitHub:** https://github.com/faraday208/duplicate-image-finder
**Tip:** Python kütüphanesi + CLI

İki tip kopya tespiti:
- **Birebir (exact):** MD5 hash — saniyeler içinde binlerce dosya
- **Benzer (similar):** Perceptual hash (phash, ahash, dhash, whash)

**Özellikler:**
- Konfigüre edilebilir benzerlik eşiği (0-64)
- keep_strategy: largest / smallest / first / best
- Multi-threaded (ThreadPoolExecutor)
- Manuel review meta'nın Gradio UI'ında yapılır

---

### 03 — image-quality-checker
**GitHub:** https://github.com/faraday208/image-quality-checker
**Tip:** Python kütüphanesi + CLI

Görsel kalite metriklerini ölçer.

**Özellikler:**
- **Blur:** Laplacian variance
- **Brightness:** Histogram analizi
- **Contrast:** Standart sapma
- **BPP:** Bits per pixel skoru
- **Metadata:** EXIF + PIL meta
- 4-pass JSON sistemi
- Rapor görüntüleyici meta'nın Gradio UI'ında

---

### 04 — watermark-detection
**GitHub:** https://github.com/faraday208/watermark-detection
**Tip:** CLI + Gradio UI + YOLOv8 model
**Port:** 8300 (UI için)

YOLOv8 ile filigran tespit ve temizleme.

**Özellikler:**
- 3 farklı YOLOv8 model (s, v2, v3)
- Annotated training datasets
- Bounding box çıkarımı
- Toplu cleaning (filigranlı görselleri ayrı klasör)
- Gradio UI ile manuel review + annotation

**Not:** Model dosyaları `~/Models/watermarks_yolov8/` altında bekleniyor.

---

### 05 — image-resizer
**GitHub:** https://github.com/faraday208/image-resizer
**Tip:** CLI (tek script)

Pillow + Lanczos algoritması ile yüksek kaliteli boyutlandırma.

**Özellikler:**
- Aspect ratio koruma
- Toplu işlem
- Otomatik output dizin oluşturma
- Optimize edilmiş çıktı

**Bağımlılık:** Sadece Pillow.

---

### 06 — image-captioner
**GitHub:** https://github.com/faraday208/image-captioner
**Tip:** Client + Server (Ollama)

Qwen3-VL-30B ile multi-pass captioning. LoRA / fine-tune training için.

**Özellikler — v6:**
- 5-pass sistemi:
  - Pass 1: Saç + yüz ifadesi
  - Pass 2: Vücut + poz
  - Pass 3: Kıyafet + aksesuar
  - Pass 4: Sahne + teknik (lighting, kompozisyon)
  - Pass 5: Doğal dil caption (short/medium/long)
- JSON-aware (structured + caption tutarlı)
- `--character` parametresi: caption'da karakter ismi yer alır
- Local (Ollama) veya remote (RunPod) backend
- 3 caption uzunluğu (training için seçilir)

**Çıktı:**
```json
{
  "structured": { /* 5-pass JSON */ },
  "captions": {
    "short": "...",
    "medium": "...",
    "long": "..."
  }
}
```

---

### 07 — golden-set-generator
**GitHub:** https://github.com/faraday208/golden-set-generator
**Tip:** src + Gradio UI

Pipeline'ın son aşaması — manuel cherry-pick.

**Özellikler:**
- Filtre + universal selector (`universal_selector.py`)
- Gradio UI ile dataset review
- Batch label / star
- Final dataset için "altın küme" seçimi (cherry-pick)

**Use case:**
- LoRA training öncesi ~100 mükemmel görsel seçimi
- Yarı-otomatik filtre + manuel onay

---

