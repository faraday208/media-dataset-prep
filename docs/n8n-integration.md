# n8n Entegrasyon Rehberi

Pipeline'ı manuel komutlar yerine [n8n](https://n8n.io) ile otomatize etmek için.

## Niçin n8n?

- **Görsel workflow:** Pipeline akışını drag-drop ile tasarla
- **Web hook trigger:** Yeni görsel klasörü gelince otomatik çalıştır
- **Hata yönetimi:** API down olursa retry / alert
- **Dashboard:** Çalışma geçmişi + log + metric

## n8n Kurulumu

```bash
docker run -it --rm -p 5678:5678 -v ~/.n8n:/home/node/.n8n n8nio/n8n
# UI: http://localhost:5678
```

veya npm ile:
```bash
npm install -g n8n
n8n start
```

## Workflow Şablonları

`n8n-workflows/` klasöründe hazır şablonlar:

| Şablon | Ne yapar |
|---|---|
| `full-pipeline.json` | 01 → 07 zincirini çalıştırır |
| `dedupe-only.json` | Sadece 02 (dedupe) workflow'u |
| `caption-batch.json` | 06 caption batch çalıştırması |

## Şablonu n8n'e import etme

1. n8n UI'sına git: http://localhost:5678
2. Workflows → "Import from file"
3. `n8n-workflows/full-pipeline.json` seç
4. Activate

## Pattern: API Health Check + Retry

Her tool API'si runtime'da çalışmaya başlar. n8n workflow'lar **API health check** sub-workflow'u kullanır:

```
[Workflow Trigger] → [Check API] → [API OK?]
                                       ↓
                      ┌── HAYIR ──→ [Restart API] → [Retry]
                      ↓ EVET
                  [Asıl iş — örn. Scan Duplicates]
```

`scripts/check-tools.sh` benzer bir CLI versiyonu sağlar.

## Pipeline Sırasını Korumak

Workflow'lar tool sırasını **AKMA-BAĞIMLI** olarak çalıştırır:
- 01 bitti → 02 başlar (01'in çıktısı 02'nin girdisi)
- Hata varsa pipeline durdurulur veya alternatif path'e geçer

## Cross-Tool Veri Aktarımı

Her tool JSON çıktı üretir. n8n bu JSON'u sonraki tool'a aktarır:

```
01-validate çıktı: validation_report.json
    ↓
02-duplicate girişi: filtered file list
    ↓
02-duplicate çıktı: duplicate_groups.json
    ↓
03-quality girişi: representative files
```

## Üretim Önerileri

- **Ayrı n8n instance:** Production'da Docker compose ile dedicated n8n
- **PostgreSQL backend:** SQLite default'u küçük dataset için, PostgreSQL büyük volume için
- **Queue mode:** Yüksek hacim için `n8n-worker` ile paralel
- **Webhook auth:** Public webhook'larda HMAC veya basic auth

## İlerleme

- [ ] `full-pipeline.json` örneği (tool repos açıldıkça)
- [ ] `dedupe-only.json`
- [ ] `caption-batch.json` (RunPod uzaktan server senaryosu)
- [ ] HMAC-secured webhook örneği
