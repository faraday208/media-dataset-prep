# Roadmap — Media Dataset Prep

Pipeline'ın 8 adımının tool + meta UI durumu. Tool'lar polyrepo'da bağımsız
sürümlenir; meta UI sadece "wire-up" sorumluluğu taşır (review/orchestrate).

> **Pattern referansı:** Tüm tool'lar [`docs/tool-conventions.md`](tool-conventions.md)'a
> uyar (CLI flag isimleri, sidecar JSON şeması, undo kontratı, README şablonu).
> Yeni tool yazarken / refactor ederken §10 compliance checklist takip edilir.

**Mevcut milestone:** v0.1 — 8/8 step UI'da wired, pipeline output handoff
banner, sample dataset üretici. Sıradaki: v0.2 — state persistence, pipeline
state machine, review akışlarında iyileştirme.

## Durum tablosu (2026-05-16)

| # | Tool | Tool sürümü | Conventions | Meta UI | Notlar |
|---|---|---|---|---|---|
| 00 | media-organizer | **v0.5.1** ✓ | ✓ | **wired** ✓ | CLI parity %100; recursive flat/tree, undo + cleanup |
| 01 | media-validator | **v0.4.0** ✓ | ✓ | wired ✓ | recursive default True (BC) + tree-preserving move, 45 test |
| 02 | media-deduplicator | **v1.2.2** ✓ | ✓ | wired ✓ | exact+similar mode, AI-odaklı BPP eşikleri + tree-preserving move, 65 test |
| 03 | media-quality-checker | **v1.0.1** ✓ | ✓ | wired ✓ | 4 composite check + tree-preserving move, action+undo, 45 test |
| 04 | media-watermark-detector | **v1.0.1** ✓ | ✓ | **wired** ✓ | YOLOv8 detect + tree-preserving move + invalid table, 34 test |
| 05 | media-resizer | **v1.0.1** ✓ | ✓ | **wired** ✓ | Lanczos batch (copy/in-place) + dry-run + undo (copy mode), 20 test |
| 06 | media-captioner | **v1.0.1** ✓ | ✓ | **wired** ✓ | Qwen3-VL 5-pass + JSON→TXT export + undo + caption review editor (görsel + short/medium/long edit + 5-pass structured), 15 test |
| 07 | media-golden-set | **v1.0.1** ✓ | ✓ | **wired** ✓ | Quality+caption-aware cherry-pick (recursive + tree-preserving copy) + selection preview + bucket dağılım, 39 test |

✓ = bitti  ·  ? = denetlenmedi  ·  stub = "coming soon" placeholder  ·  — = bu projede sürüm bilgisi tutulmuyor (tool repo'sundan oku)

## Sıradaki iş

v0.1'de 8/8 step **wired**. Şimdi v0.2 hedefleri:

### 1. **State persistence** ⭐ (önerilen sıradaki adım)
Per-dataset JSON sidecar (`<dataset>/.media-prep-state.json`):
- `dataset_path`, `last_report_paths`, `available_outputs`
- UI mount edildiğinde dataset path girilince otomatik yüklensin
- Browser refresh / restart kayıp olmasın

**Açık karar:** Per-dataset (taşınabilir, multi-machine) vs global
(`~/.config/media-dataset-prep/`, tek makine). Şu an birinciye yatkın.

### 2. **Pipeline state machine** (disiplin opsiyonu)
00 yapılmadıkça 01'i kilitle, 01 yapılmadıkça 02 kilitle vb. Şu an
serbest navigasyon — bazı use-case'lerde (skip akışı) gerekli, bazılarında
karışıklığa neden olur. Toggle'lanabilir "strict mode" düşünülebilir.

### 3. **Caption review akışı zenginleştir**
- Pass-bazlı edit (sadece pass 5 değil, structured field düzenleme)
- Toplu re-caption (seçili görseller için)
- Caption vs görsel tutarsızlık flag'i (heuristic veya VL çapraz kontrol)

### 4. **Duplicate review batch action**
- Multi-select + bulk "keep largest" / "keep first"
- Karar log'u sidecar JSON'a yazılsın (re-run güvenli)

### 5. **Quality filter — interaktif slider**
Şu an form-based; slider'lar değişince live count önizlemesi (kaç dosya
etkilenir, dry-run'sız).

### 6. **Tool repo'larında pyproject sync**
Workspace member'larının versiyonları meta `docs/roadmap.md`'deki sürüm
pin listesiyle script ile karşılaştırılsın (CI yardımcısı).

## v0.1 milestone'ları (tamamlandı — 2026-05-16)

- [x] **Tool conventions doc** (`docs/tool-conventions.md`) — pattern formalizasyonu
- [x] **00 organize** UI wire-up + copy/move modunda output_dir otomatik öner
- [x] **01 validate** tool refactor (action layer, undo, threshold flag'ler, 45 test)
- [x] **01 validate** UI wire-up (form-only + progress + subdir + auto-suggest)
- [x] **02 duplicate** clean refactor — `media-deduplicator` v1.2.x (65 test, AI BPP eşikleri)
- [x] **02 duplicate** UI wire-up — gallery + lightbox (carousel + zoom + BPP göstergesi)
- [x] **03 quality** wire-up — rapor görüntüleyici + filter slider + action+undo
- [x] **04 watermark** wire-up — form + invalid table + tree-preserving move
- [x] **05 resize** wire-up — form + copy/in-place mode + dry-run + undo
- [x] **06 caption** wire-up — gallery + 5-pass JSON editor (short/medium/long edit + Save&Approve)
- [x] **07 golden-set** wire-up — form + selection preview gallery + bucket dağılım
- [x] **Pipeline output handoff banner** (Step 00/05/07 → switch teklif)
- [x] **NiceGUI image gallery** reusable pattern (02/06/07'de paylaşıldı)
- [x] **Tüm tool isimleri rebrand** (`image-*` → `media-*`) — v1.0 clean release'ler
- [x] **Tüm step'lerde dataset_path implicit STATE'ten** — header tek truth source
- [x] **Sample dataset üretici** — `scripts/fetch-sample-images.sh` (loremflickr, 100 görsel)

## v0.2 milestone'ları (planlama)

- [ ] **State persistence** (JSON sidecar): UI session bilgisi diske yazılsın
  > Not: `PipelineState.available_outputs` v0.1'de eklendi. Persistence PR'ında
  > `to_dict`/`from_dict` ile `dataset_path` + `last_report_paths` +
  > `available_outputs` birlikte serialize edilecek.
- [ ] **Pipeline state machine** (opsiyonel strict mode)
- [ ] **Caption review** — pass-bazlı edit + bulk re-caption
- [ ] **Duplicate review** — batch action + karar log persistence
- [ ] **Quality filter** — interaktif slider live count
- [ ] **Workspace sürüm sync** — pyproject ↔ roadmap karşılaştırma scripti

## Açık tasarım soruları

- **State persistence nasıl?** Per-dataset JSON (`/dataset/.media-prep-state.json`)
  vs global config (`~/.config/media-dataset-prep/`). İlki taşınabilir,
  ikincisi tek-makine.
- **Pipeline state machine?** 00 yapılmadıkça 01'i kilitle, vs. Şu an
  serbest navigasyon. Disiplin gerekirse step gating eklenebilir.

## Tool sürüm pin'leri

Polyrepo modelinde meta repo tool sürümlerini pin'lemiyor — `uv workspace`
member'ları lokal symlink veya clone üzerinden geliyor. Production deploy'ta
git tag'leri (`media-organizer@v0.5.0` gibi) referans alınır.

Mevcut tag'ler:
- `media-organizer/v0.5.1` — tool field + .gitignore conventions fix
- `media-organizer/v0.5.0` — recursive scan + cleanup
- `media-validator/v0.3.1` — paket adı validator_core (sys.path collision fix)
- `media-validator/v0.3.0` — paket adı `image-validator` → `media-validator`
- `media-validator/v0.2.1` — kritik bug fix: path-based dosya çözümleme
- `media-validator/v0.2.0` — action layer (move/delete) + undo + threshold flags
- `media-deduplicator/v1.2.1` — paket adı dedup_core (sys.path collision fix)
- `media-deduplicator/v1.2.0` — AI training BPP eşikleri (FULL_SCORE 0.15→0.5); 65 test
- `media-deduplicator/v1.1.0` — keep_strategy='best' BPP-aware (artifact diskalifiye + composite skor); 57 test
- `media-deduplicator/v1.0.0` — clean release: tek run.py, exact+similar mode, action layer, undo, 41 test (eski `duplicate-image-finder` paketinin yerine)
- `media-quality-checker/v1.0.0` — clean release: 4 composite quality check (blur/brightness/contrast/bpp), action+undo, 44 test (eski `image-quality-checker` paketinin yerine)
- `media-watermark-detector/v1.0.0` — clean release: YOLOv8 detection + cleanup, scope daraltıldı (inpainting+training silindi), 33 test (eski `watermark-detection` paketinin yerine)
- `media-resizer/v1.0.1` — `--dry-run` flag wire fix: library tarafında zaten desteklenen dry-run resize_dataset+resize_one signature'ına eklendi, run.py wrapper'ı bağladı, rapora `dry_run` alanı eklendi; +1 unit test (20 toplam)
- `media-resizer/v1.0.0` — clean release: tek run.py, Lanczos batch (copy/in-place), action+undo, 19 test (eski `image-resizer` paketinin yerine)
- `media-deduplicator/v1.2.2` — tree-preserving move (apply_action `scan_result.source_root` ile `relative_to` mirror); +1 regression test (65 toplam)
- `media-validator/v0.4.0` — pipeline cross-tool tutarlılığı: recursive default True (BC change; opt-out `--no-recursive`), tree-preserving move (`relative_to(source_root)` mirror); +2 regression test (45 toplam)
- `media-quality-checker/v1.0.1` — tree-preserving move: subdir hiyerarşisi `_unique_target` flat collision yerine korunur; +1 regression test (45 toplam)
- `media-watermark-detector/v1.0.1` — tree-preserving move (aynı pattern); +1 regression test (34 toplam)
- `media-golden-set/v1.0.1` — recursive scan (`--recursive`/`--no-recursive`), tree-preserving copy (`source_root` parametresi, opt-in), `--undo` çakışma guard'ı; +4 regression test (39 toplam)
- `media-captioner/v1.0.1` — kritik undo veri kaybı bug'ı düzeltmesi: pre-existing yabancı .json/.txt dosyaları (önceki pipeline adımlarından `quality_report.json`, kullanıcı `README.txt` vb.) artık undo listesine girmiyor — snapshot-diff ile sadece bu run'da yaratılanlar saklanır; +1 regression test (15 toplam)
- `media-captioner/v1.0.0` — clean release: 5-pass multi-pass captioning (Qwen3-VL via Ollama), JSON→TXT export, undo, scope daraltıldı (Gradio json-debugger + server scripts + archive silindi), 14 test (eski `image-captioner` paketinin yerine)
- `media-golden-set/v1.0.0` — clean release: quality+caption-aware cherry-pick (bucket + face-target + character filter), action+undo, scope daraltıldı (Gradio UI silindi), 35 test (eski `golden-set-generator` paketinin yerine)