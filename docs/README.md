# Documentation

media-dataset-prep meta repo dokümantasyonu.

## İçerik

| Dosya | Ne anlatır |
|---|---|
| [pipeline-overview.md](pipeline-overview.md) | 8 adımlık pipeline akışı + tasarım prensipleri |
| [architecture.md](architecture.md) | Niçin polyrepo + uv workspace tercih edildi |
| [tool-list.md](tool-list.md) | 8 tool'un meta seviyede açıklaması (sürüm, paket, UI rolü) |
| [tool-conventions.md](tool-conventions.md) | CLI / sidecar JSON / undo / paket adı sözleşmesi — yeni tool veya refactor için referans |
| [roadmap.md](roadmap.md) | Durum tablosu, sürüm pin'leri, sıradaki iş, v0.2 hedefleri |

## Tool-Spesifik Dokümantasyon

Her tool'un kendi detaylı dokümantasyonu **kendi repo'sunda** yaşar
([`tool-conventions.md` §8](tool-conventions.md) — README 8 bölüm şablonu).
`make install` sonrası bu README'lere erişim:

```bash
cat tools/00-organize/README.md
cat tools/06-caption/README.md
```

## Katkı

Dokümantasyon hatası veya iyileştirme önerisi varsa:
- **Pipeline genel / meta UI:** Bu repo'da issue/PR
- **Tool-spesifik:** İlgili tool repo'sunda issue/PR
- **Sözleşme değişikliği:** Bu repo'da issue + `tool-conventions.md`'de PR
