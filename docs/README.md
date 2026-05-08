# Documentation

dataset-prep meta repo dokümantasyonu.

## İçerik

| Dosya | Ne anlatır |
|---|---|
| [pipeline-overview.md](pipeline-overview.md) | 7 aşamalı pipeline akışı + tasarım prensipleri |
| [architecture.md](architecture.md) | Niçin polyrepo + uv workspace tercih edildi |
| [tool-list.md](tool-list.md) | Her tool'un detay açıklaması (özellikler, port, tip) |

## Tool-Spesifik Dokümantasyon

Her tool'un kendi detaylı dokümantasyonu **kendi repo'sunda** yaşar:

- `tools/01-validate/README.md` — image-validator
- `tools/02-duplicate/README.md` — duplicate-image-finder
- ... vb.

`make install` sonrası bu README'lere erişim:
```bash
cat tools/06-caption/README.md
cat tools/06-caption/WORKFLOW.md  # detaylı workflow
```

## Katkı

Dokümantasyon hatası veya iyileştirme önerisi varsa:
- **Pipeline genel:** Bu repo'da issue/PR
- **Tool-spesifik:** İlgili tool repo'sunda issue/PR
