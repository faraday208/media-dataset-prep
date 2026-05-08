# Tool Conventions

> Pipeline'daki tüm tool'ların uyduğu ortak pattern. Yeni bir tool yazılırken
> veya mevcut bir tool refactor edilirken **bu doc referans alınır**.

**Kapsam:** 8 tool (`media-dataset-prep` workspace member'ları). UI tarafı bu
sözleşmelere güvenerek wire-up yapar.

**Statü:** v1 — organizer (v0.5.1), media-validator (v0.3.0), media-deduplicator
(v1.2.0) ve media-quality-checker (v1.0.0) bu pattern'i kuruyor. Diğer 4 tool
sırayla uyumlandırılacak.

---

## 1. Klasör yapısı

```
<tool-repo>/
├── README.md                   # 8 bölüm (aşağıda şablon)
├── LICENSE                     # MIT
├── .gitignore                  # *_report.json dahil
├── pyproject.toml              # name, version (SemVer), [dependency-groups].dev
├── run.py | <tool>.py          # CLI entry point
├── src/                        # opsiyonel (büyük tool'da)
│   ├── __init__.py             # public API export
│   └── ...                     # iç modüller
├── config/
│   └── settings.yaml           # threshold/parametre kullanan tool'larda
└── tests/
    ├── conftest.py
    └── test_*.py               # >= 30 test (unit + e2e)
```

### Paket adı standardı

| Tool boyutu | Pattern | Örnek |
|---|---|---|
| Tek modül (küçük) | Tool adıyla aynı `.py` | `media_organizer.py` → `import media_organizer` |
| Paket (büyük) | `<tool_short>_core/` | `validator_core/`, `dedup_core/`, `quality_core/` |

**❌ Yasak:** Generic `src/`, `core/` — UI tools/* sys.path'e ekleyince
çakışma yaratır (iki tool aynı `import core` deyince hangisinin
yükleneceği iterdir sırasına bağlı, deterministik değil).

Public API import yolu kararlı olmalı. Örn. `from validator_core import
FileValidator` — alt klasörleri ezberletme.

---

## 2. CLI flag standardı

### Ortak (her tool'da aynı isim ve davranış)

| Flag | Anlam | Hangi tool'da zorunlu |
|---|---|---|
| `-i, --input PATH` | Kaynak dizin | Validation/scan yapan tüm tool'lar |
| `-o, --output PATH` | Rapor JSON yolu | Tüm tool'lar (default: tool-spesifik) |
| `--recursive` | Alt klasörleri tara | Tarama yapan tool'lar |
| `--dry-run` | Simüle et, dosyaya dokunma | Aksiyonu olan tool'lar |
| `--yes` | Onay bypass | Yıkıcı (delete/destructive) aksiyonu olan tool'lar |
| `--undo REPORT_PATH` | Sidecar rapordan geri al | Aksiyonu olan tool'lar |
| `--config PATH` | settings.yaml yolu | Config kullanan tool'lar |
| `--limit N` | Max dosya (0 = limitsiz) | Test/dev için faydalı (öneri) |

### Tool-spesifik

Bu temele eklenir. Adlandırmada **`--<noun>-<verb>`** veya
**`--<verb>`** kuralı. Örnekler:

- `--invalid-action {none,move,delete}` (validator)
- `--invalid-dir PATH` (validator)
- `--recursive {flat,tree}` (organizer — özel iki-modlu varyant)
- `--cleanup-empty-dirs` (organizer)

### Yasak isimlendirme

- ❌ Aynı kavrama farklı tool'larda farklı isim
- ❌ Tek harfli özel flag (sadece `-i`, `-o`, `-h` standart)
- ❌ Pozisyonel zorunlu argüman (her şey named flag)

---

## 3. Aksiyon modeli

**Default = side-effect yok.** Tool çalıştığında dosyalara dokunmadan rapor üretir.

Yıkıcı/dönüştürücü aksiyon **opsiyonel** ve **explicit flag** ile:

| Aksiyon tipi | Flag örneği | Undoable | Onay |
|---|---|---|---|
| Move | `--invalid-action move --invalid-dir D` | ✓ | – |
| Copy / Rename | `--mode {copy,move,in-place}` (organizer) | ✓ | – |
| Delete | `--invalid-action delete` | ✗ irreversible | `--yes` veya stdin |
| Replace (in-place transform) | `--apply` | ✗ undo manuel | `--yes` |

Yıkıcı aksiyonlar **stdin onay sorar** (`--yes` flag'i hariç).

---

## 4. Sidecar JSON şeması

Her tool aksiyonu sonrası **rapor JSON** yazar. UI ve `--undo` bunu okur.

### Zorunlu alanlar (her tool aynı)

```jsonc
{
  "version": "1",
  "tool": "<tool-name>",            // pyproject.toml'daki name
  "source_root": "/abs/path",       // taranan kök
  "summary": { /* tool-spesifik */ },
  "actions": [                      // her item undoable bilgi taşır
    {"original": "/abs/path", ...}
  ]
}
```

### Önerilen alanlar (tool gerekli kılarsa)

- `recursive: bool`
- `config: { ... }` — efektif config snapshot'ı
- `results: [ ... ]` — per-file detay (büyük dataset'te opsiyonel)
- `skipped: int` — atlanan/erişilemeyen sayısı

### `actions[]` minimum kontratı

Undo'nun çalışabilmesi için:

| Aksiyon | Minimum alanlar |
|---|---|
| Move | `original`, `moved_to` |
| Copy | `original`, `copied_to` (undo = copied_to'yu sil) |
| Rename | `from`, `to` |
| Delete | `original`, `deleted: true` (undo imkansız, raporlama için) |

### Rapor dosyası adı

Tool'a özgü: `rename_report.json` (organizer), `validate_report.json` (validator).
**Suffix sabit:** `_report.json`. Bu sayede `.gitignore` pattern'i `*_report.json` ile bütün tool'ların çıktısını yakalar.

---

## 5. Undo kontratı

```python
def undo_from_report(report_path, *, dry_run=False) -> dict:
    """
    Returns: {"restored": N, "skipped": N, "irreversible_deletes": N, ...}
    Raises: ValueError if report.tool != expected tool name
    """
```

**Davranış:**
- Tool field validation (yanlış tool'un raporunu kabul etme)
- `dry_run=True` → sadece sayım, dosyaya dokunma
- Hedef konumda farklı dosya varsa **üzerine yazma**, skipped say
- Delete aksiyonları → `irreversible_deletes` sayılır, restore edilmez

---

## 6. In-process API

UI **subprocess kullanmaz**. Her tool kendi public API'sini export eder.

```python
# Tek dosya pattern'i (organizer)
import media_organizer
media_organizer.scan_directory(...)
media_organizer.generate_rename_plan(...)
media_organizer.execute_rename(...)
media_organizer.undo_from_report(...)

# src/ paket pattern'i (validator)
from src import FileValidator, collect_images, apply_action, undo_from_report
```

**Public API minimum yüzeyi:**
- `scan_*` veya `collect_*` — kaynak tarama
- `plan_*` (opsiyonel) — aksiyon planı (preview için)
- `execute_*` veya `apply_*` — aksiyonu uygula
- `undo_from_report` — geri al
- Bir `Validator` / `Processor` sınıfı (config alıp tek dosya işler)

---

## 7. Test seviyeleri

| Seviye | Yer | Sayı | Kapsam |
|---|---|---|---|
| **Unit** | tool repo `tests/` | ≥ 30 | Iç fonksiyonlar, edge case |
| **CLI e2e** | tool repo `tests/test_cli.py` | ≥ 5 | argparse + main() + tmp fixture |
| **Meta integration** | meta repo `tests/test_<tool>_integration.py` | 5-8 | Workspace integrity + pipeline handoff + undo cycle |

**Meta integration test'in yapması gerekenler:**
1. `tools/<NN>-<name>/` workspace member'ı var
2. `pyproject.toml` doğru name + minimum version ilan ediyor
3. Public API in-process import çalışıyor
4. E2E: önceki tool'un output'u → bu tool → sonraki tool'un input formatı
5. Undo cycle pipeline'ı eski haline getiriyor
6. Dry-run dosyalara dokunmuyor

---

## 8. README şablonu (8 bölüm sabit)

Her tool README'si şu sırayla:

1. **Başlık + tagline** — ne yapıyor, hangi pipeline adımı
2. **Quick start** — `uv sync`, ilk komut
3. **Kullanım örnekleri** — her mod için bir kod bloğu
4. **Operation modes tablosu** — mod / komut / etki / undo
5. **Tüm CLI flag'leri tablosu** — Flag / Tip / Default / Açıklama
6. **Config + in-process API** — settings.yaml örneği + Python kullanımı
7. **Rapor formatı** — sidecar JSON şeması (jsonc)
8. **Limitations + sürüm + lisans**

Reason/output kodları varsa **1. bölümün altında tablo**.

---

## 9. Versiyonlama

- **SemVer**: `vMAJOR.MINOR.PATCH`
  - MAJOR: rapor şeması veya CLI breaking change
  - MINOR: yeni feature (geriye uyumlu)
  - PATCH: bugfix
- Tool repo'da `git tag -a vX.Y.Z` annotated tag
- Meta `docs/roadmap.md` "Tool sürümü" kolonunda izlenir
- `pyproject.toml` `version = "X.Y.Z"` ile sync

---

## 10. Compliance checklist (yeni/refactor tool için)

Yeni tool çıkarken veya mevcut tool refactor edilirken:

- [ ] CLI flag'leri ortak isimlendirmeye uyuyor (§2)
- [ ] Default = side-effect yok (§3)
- [ ] Yıkıcı aksiyon `--yes` ile bypass edilebilir
- [ ] Sidecar JSON minimum alanları içeriyor (§4)
- [ ] Rapor adı `*_report.json` suffix'iyle bitiyor
- [ ] `--undo REPORT` çalışıyor; tool field validation var
- [ ] Public API in-process import edilebiliyor (§6)
- [ ] ≥ 30 unit/CLI test (tool repo)
- [ ] 5-8 meta integration test (meta repo)
- [ ] README 8 bölüm + reason/output tablosu
- [ ] LICENSE (MIT) + .gitignore (`*_report.json` dahil)
- [ ] Config kullanıyorsa: API/cross-tool kalıntısı yok (§3 settings.yaml temizliği)
- [ ] `pyproject.toml` SemVer + dev group + pytest config

---

## 11. Pipeline kontratı

Tool'lar arası **input/output uyumu**:

| Adım | Input | Output |
|---|---|---|
| 00 organize | Ham klasör (alt klasörlü olabilir) | Düz dataset (normalized names) |
| 01 validate | 00 output | Filtrelenmiş dataset + invalid'ler ayrı |
| 02 duplicate | 01 output | Tek-kopya dataset |
| 03 quality | 02 output | Quality-filtered |
| 04 watermark | 03 output | Watermark-clean |
| 05 resize | 04 output | Standart çözünürlük |
| 06 caption | 05 output | + .txt sidecar |
| 07 golden-set | 06 output | Final eğitim seti |

**Her tool için meta integration testi bu kontratı doğrular.**

---

## Sapmalar / istisnalar

Mevcut tool'ların doc'tan sapmaları:

| Tool | Sapma | Karar |
|---|---|---|
| organizer | `--recursive` iki modlu (`flat`/`tree`) | OK — tool-spesifik genişletme |
| organizer | Rapor field'ları (`mode`, `total_files`, `renames` vs `tool`, `actions`) | v1.0'a kadar tolerans; v1.0'da §4'e uyum |
| organizer | argparse yerine manuel `sys.argv` parsing | v1.0 refactor'da argparse'a geçiş |
| validator | `path` field'ı `FileValidationResult`'ta opt (back-compat) | Kalıcı — eski raporlar için fallback gerekli |
| validator | Paket içinde `validators/` alt klasörü | OK — file_validator + ileride başka validator'lar (örn. video) için yer |

Yeni sapma eklenmeden önce **bu doc'a not düşülür**.

---

**Son güncelleme:** 2026-05-08 (organizer v0.5.0 + validator v0.2.0 reference impl)
