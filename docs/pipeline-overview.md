# Pipeline Akışı — Detaylı

Pipeline 8 ardışık aşamadan oluşur (00 → 07). Her aşama bağımsız çalışabilir,
ancak çoğu durumda sırayla zincirlenir. Meta UI 8/8 step için **wired**
(in-process import + dry-run + execute + undo).

## Akış Diyagramı

```
┌─────────────────────────────────────────────────────────────┐
│  Ham görseller (raw input)                                   │
│  - Telegram dump, Drive, kamera, web scrape, vb.             │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  [00] media-organizer                                        │
│  Dağınık isimleri düzenli, sıralı numaralandır              │
│  IMG_3847.jpg → MyDataset_001.jpg                           │
│  - Tip-bazlı sequence (jpg/mp4/mp3 ayrı sayar)               │
│  - Recursive flat/tree mode                                  │
│  - copy/move/in-place; copy/move → yeni output_dir öner      │
│  - Dry-run + sidecar JSON + undo                             │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  [01] media-validator                                        │
│  - Format doğrulama (JPG, PNG, WebP, ...)                    │
│  - Bozuk dosya tespiti (corrupt header, eksik EOF)           │
│  - MIME-type tutarlılık                                      │
│  - Recursive **default True**; --no-recursive ile opt-out    │
│  - Action: move (tree-preserving) / delete; undo destekli    │
│  Çıktı: validate_report.json                                 │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  [02] media-deduplicator                                     │
│  - Birebir kopya: MD5 hash                                   │
│  - Benzer kopya: perceptual hash (phash/ahash/dhash/whash)   │
│  - keep_strategy: largest / smallest / first / best          │
│  - best = BPP-aware composite (artifact diskalifiye)         │
│  - AI-odaklı BPP eşikleri (FULL_SCORE 0.5)                   │
│  - Tree-preserving move; undo destekli                       │
│  Çıktı: dedup_report.json (pair grupları + actions)          │
│  Meta UI: pair gallery + lightbox + zoom + BPP göstergesi    │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  [03] media-quality-checker                                  │
│  - Blur tespiti (Laplacian variance)                         │
│  - Brightness/contrast histogramı                            │
│  - Çözünürlük / aspect ratio                                 │
│  - BPP (bits per pixel) skoru                                │
│  - 4 composite quality check                                 │
│  - Action: move (tree-preserving) / delete; undo destekli    │
│  Çıktı: quality_report.json                                  │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  [04] media-watermark-detector                               │
│  - YOLOv8 ile filigran tespit                                │
│  - Bounding box + confidence skoru                           │
│  - Action: move (tree-preserving) / delete                   │
│  - Model: ~/Models/watermarks_yolov8/ (yapılandırılabilir)   │
│  Çıktı: watermark_report.json                                │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  [05] media-resizer                                          │
│  - Lanczos algoritmasıyla kaliteli boyutlandırma             │
│  - Aspect ratio koruma                                       │
│  - Mode: copy (yeni output_dir) / in-place                   │
│  - Dry-run + undo (copy mode'da)                             │
│  Çıktı: resize_report.json                                   │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  [06] media-captioner                                        │
│  - Qwen3-VL-30B ile multi-pass caption                       │
│  - Pass 1: Saç + yüz ifadesi                                 │
│  - Pass 2: Vücut + poz                                       │
│  - Pass 3: Kıyafet + aksesuar                                │
│  - Pass 4: Sahne + teknik                                    │
│  - Pass 5: Doğal dil caption (short/medium/long)             │
│  - Ollama backend (local veya remote/RunPod)                 │
│  - JSON→TXT export; undo snapshot-diff (yabancı dosya safe)  │
│  Çıktı: image.json (structured) + image.txt (training)       │
│  Meta UI: caption review editor (görsel + edit + Save&Approve)│
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  [07] media-golden-set                                       │
│  - Quality + caption-aware cherry-pick                       │
│  - Bucket dağılım (face-target / character / aspect)         │
│  - Recursive scan + tree-preserving copy (opt-in)            │
│  - Final dataset için "altın küme" seçimi                    │
│  Çıktı: golden_report.json + seçilmiş klasör                 │
│  Meta UI: form + selection preview gallery + bucket dağılım  │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  ✅ Eğitime hazır dataset                                     │
│  - LoRA training (Diffusers, AI-Toolkit, Kohya)              │
│  - Fine-tune                                                 │
│  - Embedding training                                        │
└─────────────────────────────────────────────────────────────┘
```

## Pipeline Tasarım Prensipleri

### 1. Numara = sıra
Klasör/repo adlarındaki numaralar pipeline akışını yansıtır. `00` her zaman ilk,
`07` son. Yeni bir adım eklenirse iki numara arasına eklenir:
- `02b-augment/` (02 ile 03 arası, augmentation eklenirse)

### 2. Sade isim
`image-` prefix'i gereksiz tekrar — `media-dataset-prep` zaten görsel bağlamı
verir. Eski isimler (image-validator, duplicate-image-finder, …) **`media-*`
serisine** rebrand edildi (v1.0 clean release'lerinde).

### 3. Pipeline dışı araçlar `_` prefix
Pipeline aşaması olmayan yardımcılar (debug tool, geçici script, vb.)
`_debug-tools/` gibi alt-çizgili klasörlere — alfabetik sıralamada başta toplanır,
görsel olarak ayrı.

### 4. Bağımsızlık şart
Her tool standalone clone'lanıp çalışabilmeli. Pipeline öncesi/sonrası adım
bilgisi tool'un içinde değil, **meta repo'nun rehberlerinde** yaşar.

### 5. Default = side-effect yok
Tool çalıştığında dosyalara dokunmadan rapor üretir. Yıkıcı/dönüştürücü aksiyon
**opsiyonel + explicit flag** ile. Tüm aksiyonlar (delete hariç) **undo'lanabilir**
(`*_report.json` sidecar üzerinden). Sözleşme: [`tool-conventions.md`](tool-conventions.md).

### 6. Tree-preserving move
Subdir hiyerarşisini koruyan move pattern'i tüm tool'larda standart
(`source_root` + `relative_to`). Flat collision rename yerine orijinal yapı
mirror edilir (validate v0.4.0, dedup v1.2.2, quality v1.0.1, watermark v1.0.1,
golden-set v1.0.1).

### 7. Pipeline output handoff
Yeni klasör üreten adımlar (Organize copy/move, Resize copy, Golden-set)
UI'a output dizinini "register" eder. UI üstte banner ile kullanıcıya
*"yeni output hazır — pipeline'ı oraya çevir?"* teklif eder; kabul edilirse
`dataset_path` yeni klasöre geçer (sonraki step'ler oradan okur).

## Skip / Hibrit Akış

Tüm aşamalar zorunlu değil. Use case'e göre:

| Senaryo | Aktif aşamalar |
|---|---|
| LoRA training | 00 → 02 → 03 → 06 → 07 |
| Filigran temizliği | 04 |
| Drive dedupe | 02 |
| Caption-only | 06 |
| Ürün katalog | 00 → 01 → 04 → 05 |

`make install` hepsini kurar ama runtime'da kullanılmayabilir.
