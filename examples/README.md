# Pipeline Örnekleri

End-to-end demolar — sahte data ile pipeline'ın nasıl çalıştığını gösterir.

## İçerik

| Dosya / Klasör | Ne yapar |
|---|---|
| `sample-dataset/` | Telif sorunsuz örnek görseller (fetch script çıktısı) |
| `run-pipeline.sh` | CLI ile end-to-end pipeline şablonu (power-user / CI) |

## Hızlı başlangıç

```bash
# 1. Tek seferlik kurulum
make install            # tools/ altına 8 repo
cp .env.example .env    # .env'i düzenle (OLLAMA_HOST vb.)

# 2. Örnek dataset üret (~30 sn)
./scripts/fetch-sample-images.sh 100
# → examples/sample-dataset/img_001.jpg … img_100.jpg

# 3a. UI ile review (önerilen)
uv sync --group ui
uv run --group ui python ui.py        # http://localhost:8200
# dataset path olarak: examples/sample-dataset/

# 3b. veya CLI şablonu
./examples/run-pipeline.sh
```

## sample-dataset/

`scripts/fetch-sample-images.sh` ile **loremflickr.com**'dan indirilen
CC lisanslı Flickr fotoğrafları (`portrait,woman` / `person,sitting` /
`man,street` gibi 16 keyword × 6 farklı boyut). Pipeline test için ideal:

- Çeşitli içerik (kadınlı/erkekli, portre/full-body, sokak/cafe)
- 6 farklı çözünürlük (resize testi için)
- Bazı görseller blur'lu / düşük BPP (quality testi için)
- 100 görsel → dedupe + caption pipeline'ı için yeterli

**Telif notu:** Tüm görseller Flickr CC üzerinden gelir. Public repo'ya commit
edilebilir, eğitim modeli için kullanılabilir (lisansa uygun atıfla).

### Kendi datasetinizle

```bash
# fetch script yerine kendi klasörünüzü kullanın:
uv run --group ui python ui.py
# UI'da dataset path olarak kendi yolunuzu girin
```

## run-pipeline.sh

CLI tabanlı pipeline şablonu (UI gerektirmez — CI veya headless senaryolar için).
Her tool'un `run.py` entry'sini sırayla çağırır, `*_report.json` sidecar'lara
yazar. Detay için scripti inceleyin: [`run-pipeline.sh`](run-pipeline.sh).

> İnteraktif review akışları (duplicate pair'leri, caption düzeltme,
> golden-set cherry-pick) **UI'da** yapılır — CLI sadece otomatik adımlar için.
