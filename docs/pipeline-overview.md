# Pipeline Akışı — Detaylı

Pipeline 7 ardışık aşamadan oluşur. Her aşama bağımsız çalışabilir, ancak çoğu durumda sırayla zincirlenir.

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
│  - Tarih sıralı (oluşturma zamanı)                           │
│  - Dry-run mode                                              │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  [01] media-validator                                        │
│  - Format doğrulama (JPG, PNG, WebP, ...)                   │
│  - Bozuk dosya tespiti (corrupt header, eksik EOF)          │
│  - MIME-type tutarlılık                                      │
│  Çıktı: validation_report.json                               │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  [02] media-deduplicator                                 │
│  - Birebir kopya: MD5 hash                                   │
│  - Benzer kopya: perceptual hash (phash, ahash, dhash)       │
│  - keep_strategy: largest / smallest / first / best          │
│  Çıktı: duplicate_groups.json + silme operasyonu            │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  [03] media-quality-checker                                  │
│  - Blur tespiti (Laplacian variance)                         │
│  - Brightness/contrast histogramı                            │
│  - Çözünürlük / aspect ratio                                 │
│  - BPP (bits per pixel) skoru                                │
│  Çıktı: quality_report.json + filtreleme                    │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  [04] media-watermark-detector                                    │
│  - YOLOv8 ile filigran tespit                                │
│  - Bounding box çıkarımı                                     │
│  - Filigranlı görselleri ayrı klasöre / silme                │
│  Çıktı: watermark_report.json                                │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  [05] media-resizer                                          │
│  - Lanczos algoritmasıyla kaliteli boyutlandırma             │
│  - Aspect ratio koruma                                       │
│  - Hedef çözünürlük (örn. 1024x1024 LoRA için)              │
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
│  Çıktı: image.json (structured) + image.txt (training)      │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  [07] media-golden-set                                   │
│  - Manuel cherry-pick UI                                     │
│  - Filtre + universal selector                               │
│  - Final dataset için "altın küme" seçimi                    │
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
Klasör/repo adlarındaki numaralar pipeline akışını yansıtır. `01` her zaman ilk, `07` son.

Yeni bir adım eklenirse iki numara arasına eklenir:
- `02b-augment/` (02 ile 03 arası, augmentation eklenirse)

### 2. Sade isim
`image-` prefix'i gereksiz tekrar. `media-dataset-prep` zaten görsel bağlamı verir.

### 3. Pipeline dışı araçlar `_` prefix
Pipeline aşaması olmayan yardımcılar (debug tool, geçici script, vb.) `_debug-tools/` gibi alt-çizgili klasörlere — alfabetik sıralamada başta toplanır, görsel olarak ayrı.

### 4. Bağımsızlık şart
Her tool standalone clone'lanıp çalışabilmeli. Pipeline öncesi/sonrası adım bilgisi tool'un içinde değil, media-dataset-prep meta repo'nun rehberlerinde yaşar.

## Skip / Hibrit Akış

Tüm aşamalar zorunlu değil. Use case'e göre:

| Senaryo | Aktif aşamalar |
|---|---|
| LoRA training | 01 → 02 → 03 → 06 → 07 |
| Filigran temizliği | 04 |
| Drive dedupe | 02 |
| Caption-only | 06 |

`make install` hepsini kurar ama runtime'da kullanılmayabilir.
