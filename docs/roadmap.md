# Roadmap — Media Dataset Prep

Pipeline'ın 8 adımının tool + meta UI durumu. Tool'lar polyrepo'da bağımsız
sürümlenir; meta UI sadece "wire-up" sorumluluğu taşır (review/orchestrate).

> **Pattern referansı:** Tüm tool'lar [`docs/tool-conventions.md`](tool-conventions.md)'a
> uyar (CLI flag isimleri, sidecar JSON şeması, undo kontratı, README şablonu).
> Yeni tool yazarken / refactor ederken §10 compliance checklist takip edilir.

## Durum tablosu (2026-05-08)

| # | Tool | Tool sürümü | Conventions | Meta UI | Notlar |
|---|---|---|---|---|---|
| 00 | media-organizer | **v0.5.1** ✓ | ✓ | **wired** ✓ | CLI parity %100; recursive flat/tree, undo + cleanup |
| 01 | image-validator | **v0.2.1** ✓ | ✓ | stub | move/delete + undo, threshold CLI override, 43 unit test (v0.2.1: path-based dosya çözümleme bug fix) |
| 02 | duplicate-image-finder | — | ? | stub | exact (md5) + perceptual (phash); **manuel review** |
| 03 | image-quality-checker | — | ? | stub | blur/brightness/contrast metrikleri; **gallery filter** |
| 04 | watermark-detection | — | ? | stub | YOLOv8; tool'un kendi Gradio UI'ı var (port 8300) |
| 05 | image-resizer | — | ? | stub | Lanczos batch; review değeri düşük |
| 06 | image-captioner | — | ? | stub | Qwen3-VL multi-pass; **caption review** |
| 07 | golden-set-generator | — | ? | stub | manuel cherry-pick; tool'un kendi Gradio UI'ı var |

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
Final cherry-pick — büyük gallery + star/label. Tool'un kendi Gradio UI'ı
var; meta'da ya **replikasyon** ya da **iframe embed** kararı verilmeli.

### 5. **01 — Validate** (sıradaki adım — pipeline sırası)
Tool tarafı v0.2.0'da hazır (move/delete + undo). UI'da form-only:
threshold sliderları, action seçimi, dry-run preview, invalid table,
undo butonu. ~2 saat. Pipeline disiplini gereği 02'den önce yapılır:
bozuk/hatalı dosyalar dedupe'dan önce filtrelenmeli.

### 6. **05 — Resize** (düşük öncelik)
Batch operation, review değeri düşük. UI'da: hedef çözünürlük seç +
dry-run preview (kaç dosya etkilenecek). 00 organize gibi form-only.

### 7. **04 — Watermark** (karar bekliyor)
Tool'un kendi Gradio UI'ı zaten review için tasarlanmış (annotation,
bounding box). Meta UI'da:
- **A:** Replikasyon — NiceGUI'ye port et (zaman maliyeti yüksek)
- **B:** Iframe embed — meta tab içinde tool'un kendi UI'ını göster
- **C:** Link — meta'da sadece "Aç" butonu, tool ayrı pencerede
B veya C mantıklı; A polyrepo prensibine ters.

## v0.2 milestone'ları

- [x] **Tool conventions doc** (`docs/tool-conventions.md`) — pattern formalizasyonu
- [x] **01 validate** tool refactor (action layer, undo, threshold flag'ler, README, 39 test)
- [ ] **01 validate** UI wire-up (form-only, ~2 saat)
- [ ] **02 duplicate** tool conventions audit (sapmalar varsa düzelt)
- [ ] **02 duplicate** UI wire-up (gallery + pair-wise review)
- [ ] **NiceGUI image gallery** reusable widget (02 + 03 + 06 ortak)
- [ ] **State persistence** (JSON sidecar): UI session bilgisi diske yazılsın
- [ ] **06 caption** wire-up (görsel + caption editor)

## Açık tasarım soruları

- **Tool'a kendi UI'ı varsa (04, 07) ne yapılır?** Replikasyon vs embed vs link.
  Karar v0.2'de verilebilir.
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
- `image-validator/v0.2.1` — kritik bug fix: path-based dosya çözümleme
- `image-validator/v0.2.0` — action layer (move/delete) + undo + recursive + threshold flags
