# media-dataset-prep

> Meta-orchestrator for AI image dataset preparation pipeline.
> Ham görselleri AI eğitimi için hazır hale getiren modüler araç ekosistemi —
> tek venv, tek UI, bağımsız tool'lar.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/badge/built%20with-uv-261230)](https://github.com/astral-sh/uv)
[![UI: NiceGUI](https://img.shields.io/badge/UI-NiceGUI-2cb392)](https://nicegui.io)

---

## 🎯 Bu Repo Nedir?

**media-dataset-prep**, AI görsel modelleri (LoRA, fine-tune, vb.) için dataset
hazırlama sürecini yöneten **meta-orkestratör** repo'dur. Kendisi pipeline kodu
barındırmaz — 8 bağımsız tool'u tek bir akışta birleştirir ve **NiceGUI tabanlı
human-in-the-loop arayüz** sunar.

Her tool ayrı GitHub repo'sunda yaşar. Bu repo:

- 📚 **Pipeline akışını** dökümante eder ([`docs/`](docs/))
- 🔧 **`make install`** ile 8 tool'u tek komutla kurar
- 🔄 **uv workspace** ile tek venv altında çalıştırır
- 🖥️ **NiceGUI tek UI** (port 8200) — 8 step sekmeli, in-process import
- 🪝 **Pipeline output handoff** — Organize/Resize/Golden-set yeni klasör
  ürettiğinde banner ile "switch" teklif eder
- 🧪 **Örnek dataset üretici** ([`scripts/fetch-sample-images.sh`](scripts/fetch-sample-images.sh))
  — loremflickr'dan 100 CC fotoğraf, pipeline test seti

---

## 📊 Pipeline Akışı

```
Ham görseller (raw input)
    ↓
[00] Organize         Tip-bazlı sıralı isimlendirme (jpg/mp4 ayrı), copy/move/in-place
    ↓
[01] Validate         Format + bütünlük; recursive default, tree-preserving move
    ↓
[02] Duplicate        Exact (MD5) + similar (phash/dhash/whash), AI-odaklı BPP eşikleri
    ↓
[03] Quality          Blur (Laplacian), brightness, contrast, BPP — 4 composite skor
    ↓
[04] Watermark        YOLOv8 detect + filtreleme, tree-preserving move
    ↓
[05] Resize           Lanczos batch (copy / in-place), dry-run + undo
    ↓
[06] Caption          Qwen3-VL 5-pass + caption review editor (short/medium/long)
    ↓
[07] Golden Set       Quality+caption-aware cherry-pick, bucket dağılım, recursive copy
    ↓
Eğitime hazır dataset
```

8/8 step **meta UI'da wired** — her step in-process tool API'sini import eder,
dry-run preview + execute + undo akışı sunar.

---

## 🧰 Tool'lar (Her Biri Bağımsız Repo)

| # | Tool | Repo | Sürüm | Tip |
|---|---|---|---|---|
| 00 | **media-organizer** | [github](https://github.com/faraday208/media-organizer) | v0.5.1 | Library + CLI |
| 01 | **media-validator** | [github](https://github.com/faraday208/media-validator) | v0.4.0 | Library + CLI |
| 02 | **media-deduplicator** | [github](https://github.com/faraday208/media-deduplicator) | v1.2.2 | Library + CLI |
| 03 | **media-quality-checker** | [github](https://github.com/faraday208/media-quality-checker) | v1.0.1 | Library + CLI |
| 04 | **media-watermark-detector** | [github](https://github.com/faraday208/media-watermark-detector) | v1.0.1 | Library + CLI + YOLOv8 |
| 05 | **media-resizer** | [github](https://github.com/faraday208/media-resizer) | v1.0.1 | Library + CLI |
| 06 | **media-captioner** | [github](https://github.com/faraday208/media-captioner) | v1.0.1 | Library + Ollama client |
| 07 | **media-golden-set** | [github](https://github.com/faraday208/media-golden-set) | v1.0.1 | Library + CLI |

> Tüm tool'lar Python kütüphanesi olarak `<tool>_core/` paketinden import edilir;
> UI katmanı (NiceGUI) meta-orchestrator'da merkezi olarak yönetilir. CLI'lar
> power-user/debug için korunmuştur. Sözleşmeler için
> [`docs/tool-conventions.md`](docs/tool-conventions.md).

---

## 🚀 Quick Start

### 1. Clone et
```bash
git clone https://github.com/faraday208/media-dataset-prep
cd media-dataset-prep
```

### 2. uv kur (yoksa)
```bash
# Linux / macOS:
curl -LsSf https://astral.sh/uv/install.sh | sh

# Veya pip ile:
pip install uv
```

### 3. Tool'ları indir + venv hazırla
```bash
make install          # PRODUCTION: 8 tool'u GitHub'dan clone'la
# veya
make install-local    # DEVELOPMENT: /home/ai/Workspace/<tool>'tan symlink
# veya
make install-hybrid   # Önce GitHub dene, yoksa yerele düş
```

Bu komut:
- `tools/00-organize` … `tools/07-golden-set` altına 8 alt repo'yu yerleştirir
- `uv sync` ile tek `.venv/` kurar (workspace mode — her tool editable)

### 4. Ortam değişkenlerini ayarla
```bash
cp .env.example .env
# .env'i kendi yollarınla düzenle (DATASET_INPUT_DIR, OLLAMA_HOST, vb.)
```

### 5. Sağlık kontrolü + test
```bash
make check                 # 8 tool'un in-process API import sağlığı
make test                  # examples/run-pipeline.sh placeholder
uv run pytest -q           # 9 integration test (tools + pipeline tree)
```

### 6. UI — human-in-the-loop review
```bash
uv sync --group ui                    # NiceGUI bağımlılığı
uv run --group ui python ui.py        # http://localhost:8200
# Farklı port:  UI_PORT=9000 uv run --group ui python ui.py
```

UI 8 sekme + Overview + sürekli görünen **dataset path header** içerir:
- **Overview**: pipeline durumu, son rapor listesi, output handoff banner
- **00 Organize / 01 Validate / … / 07 Golden Set**: her biri dry-run preview
  + execute + undo + (gerektiğinde) gallery / review editor

Pipeline'ın bazı adımları (00 copy/move, 05 copy, 07 cherry-pick) **yeni bir
output klasörü** üretir. UI üstte banner ile "yeni output hazır — pipeline'ı
oraya çevir?" teklif eder; kabul edersen `dataset_path` o klasöre geçer.

### 7. Örnek dataset (opsiyonel — boş repo'da pipeline test etmek için)
```bash
./scripts/fetch-sample-images.sh 100         # loremflickr'dan 100 görsel
# → examples/sample-dataset/img_001.jpg … img_100.jpg
```

Görseller CC lisanslı Flickr fotoğrafları; portre/full-body karışık, 6 farklı
çözünürlük (resize testi için), public repo'ya commit edilebilir.

---

## 🏗️ Mimari Karar — Niçin Polyrepo + Meta?

| Yaklaşım | Sorun |
|---|---|
| **Tek monorepo** | 28 GB clone — sadece 1 tool lazım olana aşırı |
| **Tam polyrepo (meta yok)** | Pipeline bütünü kaybolur, her tool ayrı kurulur |
| **Submodule** | UX karmaşası (recurse-init, detached HEAD, double commit) |
| **Meta + uv workspace** ⭐ | Bağımsız tool'lar + tek kurulum + tek venv |

### Avantajlar
- **Bağımsız tool kullanımı:** Sadece `media-deduplicator` lazımsa onu clone'la, kullan
- **Tek venv:** `uv sync` 10 saniyede tüm pipeline'ı çalışır hale getirir
- **Bağımsız sürüm:** Her tool kendi `v1.2.3` etiketiyle ilerler
- **Topluluk dostu:** Issue/PR doğrudan ilgili tool'a açılır, karmaşa yok

Detay: [`docs/architecture.md`](docs/architecture.md).

---

## 📁 Repo Yapısı

```
media-dataset-prep/
├── README.md
├── LICENSE
├── pyproject.toml         # uv workspace tanımı + dev/ui dependency group
├── Makefile               # make install / install-local / install-hybrid / check / test
├── .env.example           # ortak env vars şablonu
├── .gitignore             # tools/, .venv/, .env, *_report.json
│
├── ui.py                  # NiceGUI tek-dosya orchestrator (8 step + Overview)
│
├── docs/                  # Pipeline rehberleri + sözleşmeler
│   ├── README.md
│   ├── pipeline-overview.md   # 8 adımlık akış + tasarım prensipleri
│   ├── architecture.md        # Niçin polyrepo + uv workspace
│   ├── tool-list.md           # 8 tool meta seviyede özet
│   ├── tool-conventions.md    # CLI/JSON/undo/README ortak sözleşme
│   └── roadmap.md             # Sıradaki iş, durum tablosu, sürüm pin'leri
│
├── examples/
│   ├── README.md
│   ├── sample-dataset/        # fetch-sample-images.sh çıktısı (100 görsel)
│   └── run-pipeline.sh        # CLI ile end-to-end şablon
│
├── scripts/
│   ├── install-tools.sh       # 8 tool'u clone/symlink eder
│   ├── update-tools.sh        # Hepsini günceller
│   ├── check-tools.sh         # In-process import sağlık kontrolü
│   └── fetch-sample-images.sh # loremflickr örnek dataset üretici
│
├── tests/                     # 9 integration test (pipeline cross-tool)
│   ├── test_organizer_integration.py
│   ├── test_validator_integration.py
│   ├── test_duplicate_integration.py
│   ├── test_quality_integration.py
│   ├── test_watermark_integration.py
│   ├── test_resize_integration.py
│   ├── test_caption_integration.py
│   ├── test_golden_set_integration.py
│   ├── test_pipeline_tree_integration.py
│   └── test_ui_smoke.py
│
└── tools/                     # (gitignored) install-tools.sh ile dolar
    ├── 00-organize/           # → media-organizer
    ├── 01-validate/           # → media-validator
    ├── 02-duplicate/          # → media-deduplicator
    └── ...
```

---

## 🛠️ Standalone Kullanım

Sadece bir tool lazımsa onu **bağımsız** kullan:

```bash
git clone https://github.com/faraday208/media-captioner
cd media-captioner
uv sync
# Bu repo'nun pyproject.toml'una göre kendi venv'ini kurar
# media-dataset-prep'e ihtiyaç yok
```

Her tool tam belgelenmiştir, kendi başına çalışır.

---

## 🎯 Kullanım Senaryoları

### Senaryo 1: LoRA training dataset hazırlığı
1. `./scripts/fetch-sample-images.sh 200` veya kendi ham klasörün
2. `make install` + `uv sync --group ui`
3. `uv run --group ui python ui.py` → http://localhost:8200
4. UI sekmelerinden sırayla: **00 → 02 → 03 → 06 → 07**
5. Her step dry-run + execute + (yanlış gittiyse) undo
6. **07 Golden Set** çıkışı → eğitim için hazır dataset

### Senaryo 2: Ürün katalog fotoğraflarını temizleme
1. Drive dump'ından 5000 fotoğraf
2. **00 Organize**: düzenli isim ver (`Product_001.jpg`)
3. **01 Validate**: bozukları at
4. **04 Watermark**: filigranları temizle
5. **05 Resize**: standartlaştır (1024×1024)

### Senaryo 3: Tek tool ihtiyacı
1. `git clone github.com/faraday208/media-deduplicator`
2. `cd media-deduplicator && uv sync`
3. Çalıştır — media-dataset-prep meta'ya gerek yok

---

## 🧪 Test

```bash
uv run pytest -q                      # 9 integration test (~30 sn)
uv run pytest tests/test_ui_smoke.py  # UI smoke test (NiceGUI mount)
make check                            # In-process import sağlığı
```

Tool-içi unit testler her tool repo'sunda kendi `tests/` altında (~300+ test).

---

## 🤝 Contributing

- **Bir tool'a katkı:** İlgili repo'da issue/PR aç
- **Pipeline akışı / docs / UI:** Bu repo'da issue/PR aç
- **Yeni tool önerisi:** Bu repo'da issue aç ("New tool: ...")
- **Sözleşmelere uy:** Yeni tool veya refactor öncesi
  [`docs/tool-conventions.md`](docs/tool-conventions.md) §10 checklist'i

---

## 📜 Lisans

[MIT](LICENSE) — Özgürce kullan, fork et, dağıt.

---

## 🙏 Teşekkürler

- [Astral](https://astral.sh) — `uv` ile Python paket yönetimini hızlandırdığı için
- [NiceGUI](https://nicegui.io) — tek-dosya Python UI için
- [Hugging Face](https://huggingface.co) — açık model ekosistemi
- [Qwen Team](https://qwenlm.github.io) — VL captioning için Qwen3-VL serisi
- [Ultralytics](https://ultralytics.com) — YOLOv8 (watermark detection)
- [loremflickr.com](https://loremflickr.com) — örnek dataset için CC fotoğraflar
