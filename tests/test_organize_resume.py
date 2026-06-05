"""Organize resume — manifest params'tan form alanlarının (prefix/recursive/mode/
output_dir/include_ext) gerçekten render'a yansıdığını NiceGUI User ile doğrular.

İki yol: (1) build-time (sayfa açılırken params zaten var), (2) notify_change
(sayfa açıkken dataset seçilince) — kullanıcının gerçek akışı bu ikincisi."""


def _recipe(ds):
    return {
        "prefix": "kitty",
        "recursive": "tree",
        "mode": "copy",
        "include_ext": True,
        "output_dir": str(ds / "organized"),
    }


async def test_resume_build_time(user, tmp_path) -> None:
    """Sayfa açılmadan ÖNCE params set → build sırasında restore."""
    import ui

    ds = tmp_path / "cats"
    ds.mkdir()
    ui.STATE.base_path = str(ds)
    ui.STATE.last_report_paths.clear()
    ui.STATE.last_stage_params.clear()
    ui.STATE.last_stage_params[0] = _recipe(ds)

    await user.open("/?tab=0")

    await user.should_see("kitty")                    # prefix (input)
    await user.should_see(str(ds / "organized"))      # output_dir (input)
    await user.should_see("Copy to output-dir")       # mode (select seçili label)


async def test_resume_on_change(user, tmp_path) -> None:
    """Sayfa AÇIKKEN dataset seçilince (notify_change) restore — kullanıcı akışı."""
    import ui

    ds = tmp_path / "cats"
    ds.mkdir()
    ui.STATE.base_path = str(ds)
    ui.STATE.last_report_paths.clear()
    ui.STATE.last_stage_params.clear()

    await user.open("/?tab=0")
    # başlangıçta params yok → form default
    await user.should_not_see(str(ds / "organized"))

    # dataset seçimi simülasyonu: _load_project_memory params'ı doldurur + notify
    ui.STATE.last_stage_params[0] = _recipe(ds)
    ui.STATE.notify_change()

    await user.should_see("kitty")
    await user.should_see(str(ds / "organized"))
    await user.should_see("Copy to output-dir")


async def test_resume_real_manifest_end_to_end(user, tmp_path) -> None:
    """GERÇEK manifest yazımı → _load_project_memory bulur → restore render.
    Manifest konumu (_report_dir_for) ile _find_manifest aramasının uyuştuğunu
    ve params'ın (output_dir dahil) gerçekten yüklenip forma yansıdığını sınar."""
    import json
    from pathlib import Path

    import ui

    ds = tmp_path / "cats"
    ds.mkdir()
    out = ds / "organized"  # _suggest_output_dir'ın önerdiği yer (dataset içi)

    # organize'ın yazdığı gibi: rapor + manifest (copy modu, output_dir=out)
    report = ui._report_path("rename_report.json", str(out))
    Path(report).parent.mkdir(parents=True, exist_ok=True)
    Path(report).write_text(json.dumps({
        "tool": "media-organizer", "total_files": 2,
        "timestamp": "2026-06-05T16:00:00",
        "renames": [{"extension": ".jpg", "old_filename": "a.jpg",
                     "new_filename": "kitty_1.jpg", "time_source": "exif"}],
    }))
    ui._append_manifest_from_report(
        0, report, output_dir=str(out),
        params={"prefix": "kitty", "recursive": "tree", "mode": "copy",
                "include_ext": True, "output_dir": str(out),
                "success": 2, "error": 0},
    )

    # dataset seçimi: _load_project_memory manifest'i BULMALI + params yüklemeli
    ui.STATE.base_path = str(ds)
    ui.STATE.last_report_paths.clear()
    ui.STATE.last_stage_params.clear()
    mem = ui._load_project_memory(str(ds))
    assert mem is not None, "manifest bulunamadı (_find_manifest vs _report_dir_for uyumsuz)"
    assert ui.STATE.last_stage_params.get(0, {}).get("output_dir") == str(out)

    await user.open("/?tab=0")
    await user.should_see("kitty")
    await user.should_see(str(out))
    await user.should_see("Copy to output-dir")
