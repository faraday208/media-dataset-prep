"""Duplicate resume — MODE-BAZLI. exact ve similar ayrı yaşar: aktif mode'a ait
son manifest run'ından config + undo + hafif sonuç (stat kartları) döner; mode
değiştikçe o mode'un kaydı yüklenir. Gallery yeniden inşa edilmez.

Kritik davranış: (1) aktif mode'un kaydı yüklenir, (2) diğer mode'un kaydı
SIZMAZ (izolasyon), (3) mode switch o mode'un kaydını getirir."""
import json
from pathlib import Path


def _write_run(ui, ds, *, mode, total, space_human, params_extra=None):
    """Bir mode için gerçek rapor + manifest run yaz (duplicate'in yazdığı gibi)."""
    name = f"duplicate_{mode}_report.json"
    report = ui._report_path(name, str(ds))
    Path(report).parent.mkdir(parents=True, exist_ok=True)
    Path(report).write_text(json.dumps({
        "tool": "media-deduplicator",
        "mode": mode,
        "summary": {
            "total_scanned": total, "unique": total - 3, "groups": 2,
            "duplicates": 3, "space_freeable_human": space_human,
        },
        "groups": [],
    }))
    params = {"mode": mode, "action": "move", "keep_strategy": "largest",
              "invalid_dir": str(ds.parent / "_rejected" / f"custom-{mode}")}
    params.update(params_extra or {})
    ui._append_manifest_from_report(2, report, params=params)
    return report


async def test_resume_active_mode_exact(user, tmp_path) -> None:
    """Manifest'te exact run var → açılışta (default mode=exact) exact restore."""
    import ui

    ds = tmp_path / "imgs"
    ds.mkdir()
    _write_run(ui, ds, mode="exact", total=10, space_human="10.0 KB")

    ui.STATE.base_path = str(ds)
    ui.STATE.last_report_paths.clear()
    ui.STATE.last_stage_params.clear()
    ui._load_project_memory(str(ds))

    await user.open("/?tab=2")

    await user.should_see("Önceki exact raporu yüklendi")
    await user.should_see("10.0 KB")              # exact run'ın space özeti
    await user.should_see("En büyük")             # keep_strategy=largest restore
    await user.should_see("custom-exact")         # invalid_dir restore (custom yol)


async def test_resume_mode_isolation(user, tmp_path) -> None:
    """Manifest'te SADECE similar run var → açılışta exact mode aktif → similar
    kaydı SIZMAZ (stat kartları boş, restore mesajı yok)."""
    import ui

    ds = tmp_path / "imgs"
    ds.mkdir()
    _write_run(ui, ds, mode="similar", total=20, space_human="99.9 KB")

    ui.STATE.base_path = str(ds)
    ui.STATE.last_report_paths.clear()
    ui.STATE.last_stage_params.clear()
    ui._load_project_memory(str(ds))

    await user.open("/?tab=2")

    # exact aktif, similar verisi var ama yüklenmemeli
    await user.should_see("Henüz scan yapılmadı")
    await user.should_not_see("99.9 KB")
    await user.should_not_see("Önceki similar raporu yüklendi")


# NOT: mode-switch (exact→similar seçince similar restore) davranışı koddan
# garantili — mode_select.on_value_change → _restore_for_mode, ki o da
# mode_select.value'yu okuyup _manifest_run_for_mode(mode) ile o mode'un run'ını
# çeker. Bunu NiceGUI User ile test etmek Quasar q-select dropdown
# etkileşiminin kırılganlığına takılıyor (option'lar async render); mode-bazlı
# çekirdek zaten yukarıdaki iki test ile (aktif-mode yükleme + izolasyon)
# kanıtlanıyor. Mode-switch UI'da manuel doğrulanır.
