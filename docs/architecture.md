# Mimari Karar — Niçin Bu Yapı?

## Karşılaştırılan Yaklaşımlar

### Tek Monorepo (reddedildi)
```
ai-image-toolkit/
├── duplicate-finder/
├── image-captioner/
├── ...
```
**Sorun:** Sadece 1 tool lazım olan kişi 28 GB clone yapar. Topluluk fork'lamaktan kaçınır.

### Saf Polyrepo (reddedildi)
```
github.com/user/duplicate-finder
github.com/user/image-captioner
... (10+ ayrı repo)
```
**Sorun:** Pipeline bütünlüğü kaybolur. Yeni gelen "bu tool'lar nasıl bir araya geliyor?" sorusunu cevaplayamaz.

### Git Submodules (reddedildi)
**Sorun:**
- `git submodule update --init --recursive` UX yorgunluğu
- Detached HEAD sorunu — geliştiriciler şikayet eder
- Çift commit (alt repo + ana repo pointer)
- Tek developer için bakım borcu

### Meta + uv workspace ✅ (seçildi)
**Çözüm:**
- Tools bağımsız repolar (kullanıcı isteğine göre)
- Meta repo `make install` ile hepsini birlikte getirir
- `uv workspace` tek venv altında her tool'u editable paket olarak kullanır
- `.gitignore` ile `tools/` ana repo'da kaynak değil, sadece runtime klasörü

## Niçin uv?

### Hız
`pip install -r requirements.txt` 7 tool için 5-10 dakika sürerken `uv sync` 10 saniye.

### Determinizm
`uv.lock` ile her makinede aynı versiyonlar — "benim makinede çalışıyordu" sorunu sıfır.

### Workspace mode
Birden fazla bağımsız `pyproject.toml` tek venv altında çalışır. Tool'lar arası `import` mümkün.

### Topluluk benimsemesi
2024+ Python ekosisteminde Astral (`uv`, `ruff`) en hızlı büyüyen paket yöneticisi; Hugging Face, Polars gibi büyük projeler tarafından benimseniyor.

## Neden Tools Ana Repo'da Yok?

`tools/` `.gitignore`'da çünkü:

1. **Kaynak tek yerde olmalı (DRY):** Bir tool'da değişiklik = ilgili repo'da commit, meta'ya bulaşmaz
2. **Bakım atomik:** Tool'un sürümü kendi tag'i ile ilerler, meta repo bunu pin'lemez
3. **Standalone garantisi:** Kullanıcı tek tool'u clone'larsa kullanabilir, meta'ya bağımlı değil

## Dezavantajlar (Açık Olalım)

### Kullanıcı için
- `make install` öncesi `uv` kurulu olmalı (tek defalık ekstra adım)
- Tool repos henüz GitHub'da değilse `make install` başarısız olur

### Bakım için
- 7 ayrı repo'da issue/PR ayrı ayrı yönetilir (ama her tool maintainer'ı farklı olabileceği için bu zaten iyi)
- "Pipeline'ın tamamı broken" senaryosunda hangi tool'da olduğunu kullanıcı bulmalı

### Versiyon çakışması
- İki tool farklı `transformers` versiyonu isterse `uv` en uyumlu olanı seçer (`>=4.46`)
- Çoğu zaman uyumlu ama nadiren manuel müdahale gerekebilir

## Üçüncü Yol Açık

İleride istenirse:
- **Submodule modeli'ne geçiş:** `tools/` `.gitignore`'dan çıkar, `git submodule add` ile pin'lenir
- **Tek monorepo'ya dönüş:** Tool repolari arşivlenir, kod meta'ya geri taşınır

Şu anki yapı en pragmatik orta yol, geri dönüşler kapalı değil.
