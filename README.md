# dataset-prep

> Meta-orchestrator for AI image dataset preparation pipeline.
> Ham görselleri AI eğitimi için hazır hale getiren modüler araç ekosistemi.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/badge/built%20with-uv-261230)](https://github.com/astral-sh/uv)

---

## 🎯 Bu Repo Nedir?

**dataset-prep**, AI görsel modelleri (LoRA, fine-tune, vb.) için dataset hazırlama sürecini yöneten **meta-orkestratör** repo'dur. Kendisi kod barındırmaz — pipeline'ın **7 bağımsız tool**'unu tek bir akışta birleştirir.

Her tool ayrı GitHub repo'sunda yaşar. Bu repo:

- 📚 **Pipeline akışını** dökümante eder
- 🔧 **`make install`** ile 7 tool'u tek komutla kurar
- 🔄 **uv workspace** ile tek venv altında çalıştırır
- 🖥️ **Gradio merkezli UI** ile insan-loop dataset review akışı sunar
- 🧪 **Örnek pipeline** ile end-to-end demoyu gösterir

---

## 📊 Pipeline Akışı

```
Ham görseller (raw input)
    ↓
[00] Organize         Toplu rename + opsiyonel relocate (output-dir/move), tip-bazlı sıralı numaralandırma
    ↓
[01] Validate         Format / bozukluk doğrulama
    ↓
[02] Duplicate        Birebir + benzer kopya tespit & silme
    ↓
[03] Quality          Çözünürlük, blur, kontrast filtreleme
    ↓
[04] Watermark        Filigran tespit + temizleme (YOLOv8)
    ↓
[05] Resize           Hedef çözünürlüğe ölçekleme (Lanczos)
    ↓
[06] Caption          Caption üretimi (Qwen3-VL-30B, 5-pass)
    ↓
[07] Golden Set       Cherry-pick / final seçim
    ↓
Eğitime hazır dataset
```

---

## 🧰 Tool'lar (Her Biri Bağımsız Repo)

| # | Tool | Repo | Tip |
|---|---|---|---|
| 00 | **media-organizer** | [github](https://github.com/faraday208/media-organizer) | Library + CLI |
| 01 | **image-validator** | [github](https://github.com/faraday208/image-validator) | Library + CLI |
| 02 | **duplicate-image-finder** | [github](https://github.com/faraday208/duplicate-image-finder) | Library + CLI |
| 03 | **image-quality-checker** | [github](https://github.com/faraday208/image-quality-checker) | Library + CLI |
| 04 | **watermark-detection** | [github](https://github.com/faraday208/watermark-detection) | Library + CLI + YOLOv8 |
| 05 | **image-resizer** | [github](https://github.com/faraday208/image-resizer) | Library + CLI |
| 06 | **image-captioner** | [github](https://github.com/faraday208/image-captioner) | Library + Ollama client |
| 07 | **golden-set-generator** | [github](https://github.com/faraday208/golden-set-generator) | Library + CLI |

> Tüm tool'lar Python kütüphanesi olarak `core/` modülünden import edilir; UI katmanı (Gradio) meta-orchestrator'da merkezi olarak yönetilir. CLI'lar power-user/debug için korunmuştur.

---

## 🚀 Quick Start

### 1. Clone et
```bash
git clone https://github.com/faraday208/dataset-prep
cd dataset-prep
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
make install
```

Bu komut:
- `tools/` klasörüne 7 alt repo'yu clone'lar
- `uv sync` ile tek `.venv/` kurar
- Tüm tool'ların bağımlılıklarını birlikte çözer

### 4. Ortam değişkenlerini ayarla
```bash
cp .env.example .env
# .env'i kendi yollarınla düzenle (DATASET_INPUT_DIR, OLLAMA_HOST, vb.)
```

### 5. Test
```bash
make test                  # Örnek pipeline (examples/sample-dataset/ üzerinde)
make check                 # Tool'ların API health check
```

---

## 🏗️ Mimari Karar — Niçin Polyrepo + Meta?

| Yaklaşım | Sorun |
|---|---|
| **Tek monorepo** | 28 GB clone — sadece 1 tool lazım olana aşırı |
| **Tam polyrepo (meta yok)** | Pipeline bütünü kaybolur, her tool ayrı kurulur |
| **Submodule** | UX karmaşası (recurse-init, detached HEAD, double commit) |
| **Meta + uv workspace** ⭐ | Bağımsız tool'lar + tek kurulum + tek venv |

### Avantajlar
- **Bağımsız tool kullanımı:** Sadece `duplicate-image-finder` lazımsa onu clone'la, kullan
- **Tek venv:** `uv sync` 10 saniyede tüm pipeline'ı çalışır hale getirir
- **Bağımsız sürüm:** Her tool kendi `v1.2.3` etiketiyle ilerler
- **Topluluk dostu:** Issue/PR doğrudan ilgili tool'a açılır, karmaşa yok

---

## 📁 Repo Yapısı

```
dataset-prep/
├── README.md
├── LICENSE
├── pyproject.toml         # uv workspace tanımı
├── Makefile               # make install/update/test/clean
├── .env.example           # ortak env vars şablonu
├── .gitignore             # tools/, .venv/, .env, vb.
│
├── docs/                  # Pipeline rehberleri, mimari kararlar
├── examples/              # End-to-end örnek (sahte data)
│   └── sample-dataset/    # Telif sorunsuz örnek görseller
│
├── scripts/
│   ├── install-tools.sh   # 8 tool'u clone'lar
│   ├── update-tools.sh    # Hepsini günceller
│   └── check-tools.sh     # In-process import sağlık kontrolü
│
└── tools/                 # (gitignored) install-tools.sh ile dolar
    ├── 00-organize/       # → media-organizer
    ├── 01-validate/       # → image-validator
    ├── 02-duplicate/      # → duplicate-image-finder
    └── ...
```

---

## 🛠️ Standalone Kullanım

Sadece bir tool lazımsa onu **bağımsız** kullan:

```bash
git clone https://github.com/faraday208/image-captioner
cd image-captioner
uv sync
# Bu repo'nun pyproject.toml'una göre kendi venv'ini kurar
# dataset-prep'e ihtiyaç yok
```

Her tool tam belgelenmiştir, kendi başına çalışır.

---

## 🎯 Kullanım Senaryoları

### Senaryo 1: AI persona LoRA training dataset hazırlığı
1. Sentetik görseller üret (foundation model + ComfyUI)
2. `make install` ile pipeline kur
3. `tools/02-duplicate/` ile dedupe
4. `tools/03-quality/` ile kalite filtre
5. `tools/06-caption/` ile multi-pass caption
6. `tools/07-golden-set/` ile cherry-pick
7. → Eğitim için hazır dataset

### Senaryo 2: Ürün katalog fotoğraflarını temizleme
1. Drive dump'ından 5000 fotoğraf
2. `media-organizer` ile düzenli isim ver
3. `tools/01-validate/` ile bozukları at
4. `tools/04-watermark/` ile filigranları temizle
5. `tools/05-resize/` ile standartlaştır

### Senaryo 3: Tek tool ihtiyacı
1. `git clone github.com/faraday208/duplicate-image-finder`
2. `cd duplicate-image-finder && uv sync`
3. Çalıştır — dataset-prep meta'ya gerek yok

---

## 🤝 Contributing

- **Bir tool'a katkı:** İlgili repo'da issue/PR aç
- **Pipeline akışı / docs:** Bu repo'da issue/PR aç
- **Yeni tool önerisi:** Bu repo'da issue aç ("New tool: ...")

---

## 📜 Lisans

[MIT](LICENSE) — Özgürce kullan, fork et, dağıt.

---

## 🙏 Teşekkürler

- [Astral](https://astral.sh) — `uv` ekibinin Python paket yönetimini hızlandırması için
- [Hugging Face](https://huggingface.co) — Açık model ekosistemi
- [Gradio](https://gradio.app) — İnsan-loop UI için
- [Qwen Team](https://qwenlm.github.io) — VL captioning için Qwen3-VL model serisi
