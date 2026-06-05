"""Validate resume — manifest params'tan config formunun (recursive/action/
allowed_formats/threshold'lar) ve önceki rapordan sonuç panelinin gerçekten
render'a yansıdığını NiceGUI User ile doğrular. Organize resume ile simetrik.

İki yol: (1) build-time (sayfa açılırken params zaten var), (2) notify_change
(sayfa açıkken dataset seçilince) — kullanıcının gerçek akışı bu ikincisi."""


def _recipe():
    """Default'tan farklı bir validate reçetesi — restore'un görünür kanıtı."""
    return {
        "recursive": False,
        "action": "delete",
        "invalid_dir": "/tmp/custom-validate-reject",
        "allowed_formats": "bmp,gif",
        "min_short_edge": 256,
        "max_short_edge": 4096,
        "min_aspect": 0.75,
        "max_aspect": 1.5,
        "min_size_kb": 50,
        "max_size_mb": 25,
    }


async def test_resume_build_time(user, tmp_path) -> None:
    """Sayfa açılmadan ÖNCE params set → build sırasında restore."""
    import ui

    ds = tmp_path / "shots"
    ds.mkdir()
    ui.STATE.base_path = str(ds)
    ui.STATE.last_report_paths.clear()
    ui.STATE.last_stage_params.clear()
    ui.STATE.last_stage_params[1] = _recipe()

    await user.open("/?tab=1")

    await user.should_see("Sil (irreversible)")   # action=delete (select seçili label)
    await user.should_see("bmp,gif")             # allowed_formats (input value)
    await user.should_see("/tmp/custom-validate-reject")   # invalid_dir restore


async def test_resume_on_change(user, tmp_path) -> None:
    """Sayfa AÇIKKEN dataset seçilince (notify_change) restore — kullanıcı akışı."""
    import ui

    ds = tmp_path / "shots"
    ds.mkdir()
    ui.STATE.base_path = str(ds)
    ui.STATE.last_report_paths.clear()
    ui.STATE.last_stage_params.clear()

    await user.open("/?tab=1")
    # başlangıçta params yok → form default (delete label seçili değil)
    await user.should_not_see("bmp,gif")

    # dataset seçimi simülasyonu: _load_project_memory params'ı doldurur + notify
    ui.STATE.last_stage_params[1] = _recipe()
    ui.STATE.notify_change()

    await user.should_see("Sil (irreversible)")
    await user.should_see("bmp,gif")


async def test_resume_real_manifest_end_to_end(user, tmp_path) -> None:
    """GERÇEK rapor + manifest yazımı → _load_project_memory bulur → config restore
    + önceki rapordan SONUÇ paneli (stat kartları + invalid tablo) render olur."""
    import json
    from pathlib import Path

    import ui

    ds = tmp_path / "shots"
    ds.mkdir()

    # validate'in yazdığı gibi: summary + results içeren rapor
    report = ui._report_path("validate_report.json", str(ds))
    Path(report).parent.mkdir(parents=True, exist_ok=True)
    Path(report).write_text(json.dumps({
        "tool": "media-validator",
        "summary": {
            "total": 3, "valid": 2, "invalid": 1,
            "reasons": {"too_small": 1},
        },
        "results": [
            {"filename": "ok1.jpg", "path": str(ds / "ok1.jpg"), "valid": True},
            {"filename": "ok2.jpg", "path": str(ds / "ok2.jpg"), "valid": True},
            {"filename": "tiny.jpg", "path": str(ds / "tiny.jpg"), "valid": False,
             "reason": "too_small", "width": 100, "height": 100,
             "file_size_kb": 4.0},
        ],
    }))
    ui._append_manifest_from_report(1, report, params=_recipe())

    # dataset seçimi: _load_project_memory manifest'i BULMALI + params yüklemeli
    ui.STATE.base_path = str(ds)
    ui.STATE.last_report_paths.clear()
    ui.STATE.last_stage_params.clear()
    mem = ui._load_project_memory(str(ds))
    assert mem is not None, "manifest bulunamadı (_find_manifest vs _report_dir_for uyumsuz)"
    assert ui.STATE.last_stage_params.get(1, {}).get("action") == "delete"

    await user.open("/?tab=1")

    # config restore
    await user.should_see("bmp,gif")
    # sonuç restore: önceki rapordan özet + reason kırılımı (yeniden tarama yok).
    # invalid tablo satırı (tiny.jpg) Quasar table'da client-side render olur,
    # User render-tree'sinde görünmez — reason label + özet metni kanıt olarak yeter.
    await user.should_see("Önceki validate raporu yüklendi")
    await user.should_see("too_small")            # reason kırılımı (ui.label)
