# n8n Workflow Şablonları

dataset-prep pipeline'ı için n8n otomasyon şablonları.

## İçerik

Burası şu an **placeholder** — tool repos açıldıkça gerçek workflow JSON'ları buraya gelecek.

### Planlanan Şablonlar

| Şablon | Tetikleyici | Ne yapar |
|---|---|---|
| `full-pipeline.json` | Form (manual) | 01 → 07 zincirini çalıştırır |
| `dedupe-only.json` | Form / webhook | Sadece 02 (dedupe) |
| `caption-batch.json` | Schedule / webhook | 06 batch caption (RunPod uzak server) |
| `quality-report.json` | Webhook | 03 quality + raporu Slack/email'e gönder |
| `[UTILS] api-health-check.json` | Sub-workflow | Genel API health check + retry pattern |

## Kullanım (şablonlar geldikçe)

```bash
# 1) n8n çalıştır
docker run -it --rm -p 5678:5678 -v ~/.n8n:/home/node/.n8n n8nio/n8n

# 2) UI'da Workflows → Import from file
# 3) İlgili .json dosyasını seç
# 4) Activate
```

## Pattern: Sub-Workflow Reuse

Tüm pipeline workflow'ları **API Health Check & Retry** sub-workflow'unu paylaşır:

```
[Main Workflow] → [Execute Workflow: api-health-check] → [Continue]
```

Sub-workflow parametreleri:
```json
{
  "api_url": "http://localhost:8001",
  "health_endpoint": "/health",
  "start_command": "/path/to/restart.sh",
  "max_retries": 3,
  "wait_seconds": 5
}
```

## Path Konvansiyonu

Workflow'larda hard-coded path **kullanılmaz**. Yerine:
- `.env` üzerinden okunur (`{{ $env.DATASET_INPUT_DIR }}`)
- Form input ile parametrize edilir
- Webhook payload'ında belirtilir

Bu sayede workflow'lar makineler arası taşınabilir.
