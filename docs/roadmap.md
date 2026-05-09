# Roadmap — Media Dataset Prep

Pipeline'ın 8 adımının tool + meta UI durumu. Tool'lar polyrepo'da bağımsız
sürümlenir; meta UI sadece "wire-up" sorumluluğu taşır (review/orchestrate).

> **Pattern referansı:** Tüm tool'lar [`docs/tool-conventions.md`](tool-conventions.md)'a
> uyar (CLI flag isimleri, sidecar JSON şeması, undo kontratı, README şablonu).
> Yeni tool yazarken / refactor ederken §10 compliance checklist takip edilir.

## Durum tablosu (2026-05-09)

| # | Tool | Tool sürümü | Conventions | Meta UI | Notlar |
|---|---|---|---|---|---|
| 00 | media-organizer | **v0.5.1** ✓ | ✓ | **wired** ✓ | CLI parity %100; recursive flat/tree, undo + cleanup |
| 01 | media-validator | **v0.4.0** ✓ | ✓ | stub | recursive default True (BC) + tree-preserving move (00 organize tree çıktısıyla cross-tool tutarlı), 45 test |
| 02 | media-deduplicator | **v1.2.2** ✓ | ✓ | wired ✓ | exact+similar mode, AI-odaklı BPP eşikleri + tree-preserving move (cross-tool tutarlılık), 65 test |
| 03 | media-quality-checker | **v1.0.1** ✓ | ✓ | stub | clean release + tree-preserving move (cross-tool tutarlılık), 4 composite check (blur/brightness/contrast/bpp), action+undo, 45 test |
| 04 | media-watermark-detector | **v1.0.1** ✓ | ✓ | stub | clean release + tree-preserving move (cross-tool tutarlılık), YOLOv8 detect, 34 test |
| 05 | media-resizer | **v1.0.1** ✓ | ✓ | stub | clean release + dry-run wire fix: Lanczos batch (copy/in-place mode), dry-run, action+undo, 20 test |
| 06 | media-captioner | **v1.0.1** ✓ | ✓ | stub | clean release + undo veri kaybı bug fix: Qwen3-VL 5-pass + json→txt export + undo (snapshot-diff: yabancı dosya koruması), 15 test |
| 07 | media-golden-set | **v1.0.1** ✓ | ✓ | stub | clean release + recursive scan + tree-preserving copy + undo conflict guard, 39 test |

✓ = bitti  ·  ? = denetlenmedi  ·  stub = "coming soon" placeholder  ·  — = bu projede sürüm bilgisi tutulmuyor (tool repo'sundan oku)

## Sıradaki iş — değer/maliyet sıralaması

UI'ın asıl varlık nedeni "AI etiketli veriyi insan onayından geçirmek".
Tool'ların CLI'ları zaten control için yeter — UI **review işine** odaklanmalı.
Bu mantığa göre öncelik:

### 1. **02 — Duplicate review** ⭐ (önerilen sıradaki adım)
Pair-wise UI: yan yana iki görsel + "hangisi kalsın?" butonları. Bulk select.
CLI ile yapılması zor olan tipik review işi. Tool zaten exact + similar
hash'leri çıkarıyor; UI sadece kararı topluyor.

**Wire-up gereksinimleri:**
- 02 tool'unun output formatını oku (json'da hash gruplanmış pair'ler)
- Gallery widget (NiceGUI `ui.image` + grid)
- Karar log'u → state veya sidecar JSON

### 2. **06 — Caption review** ⭐
Görsel + AI üretmiş caption (short/medium/long) yan yana. Kullanıcı
edit + onay. Tool 5-pass JSON üretiyor; UI structured + caption
tutarlılığını kullanıcıya gösterir.

### 3. **03 — Quality filter**
Gallery view + metric slider'ları (blur < X, brightness > Y).
Filter sonucunda kalan görseller. Manuel "drop / keep" toggle'ları.

### 4. **07 — Golden set**
Final cherry-pick — büyük gallery + star/label. Tool tarafı v1.0.0'da
hazır (CLI + library + sidecar JSON + undo); UI form-only olabilir
(distribution slider + face-target + character + dry-run preview +
seçim önizleme gallery'si).

### 5. **01 — Validate** (sıradaki adım — pipeline sırası)
Tool tarafı v0.2.0'da hazır (move/delete + undo). UI'da form-only:
threshold sliderları, action seçimi, dry-run preview, invalid table,
undo butonu. ~2 saat. Pipeline disiplini gereği 02'den önce yapılır:
bozuk/hatalı dosyalar dedupe'dan önce filtrelenmeli.

### 6. **05 — Resize** (düşük öncelik)
Batch operation, review değeri düşük. UI'da: hedef çözünürlük seç +
dry-run preview (kaç dosya etkilenecek). 00 organize gibi form-only.

### 7. **04 — Watermark** (form-only)
Tool v1.0.0 clean release; eski Gradio UI'sı silindi. Meta UI'da
form-only: model dropdown + confidence slider + action seçimi +
dry-run preview + invalid table + undo butonu.

## v0.2 milestone'ları

- [x] **Tool conventions doc** (`docs/tool-conventions.md`) — pattern formalizasyonu
- [x] **01 validate** tool refactor (action layer, undo, threshold flag'ler, 43 test)
- [x] **01 validate** UI wire-up (form-only + progress + subdir + auto-suggest)
- [x] **02 duplicate** clean refactor — `media-deduplicator` v1.2.0 (65 test, AI BPP eşikleri)
- [x] **02 duplicate** UI wire-up — gallery + lightbox (carousel + zoom + BPP göstergesi)
- [x] **NiceGUI image gallery** reusable pattern (02'de kuruldu, 03/06'da yeniden kullanılacak)
- [ ] **State persistence** (JSON sidecar): UI session bilgisi diske yazılsın
- [ ] **06 caption** wire-up (görsel + caption editor)

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