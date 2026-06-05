"""
UI smoke testi — ui.py modülü import edilebiliyor mu, gerekli yardımcılar
çalışıyor mu? NiceGUI sunucusunu ayağa kaldırmıyor (HTTP testi yok),
sadece kod yolunun sağlamlığını doğruluyor.

NiceGUI kurulu değilse bu modül atlanır (ui dependency-group opsiyonel).
"""
import importlib.util

import pytest

# NiceGUI yoksa tüm modülü atla — UI deps opsiyonel
nicegui_available = importlib.util.find_spec("nicegui") is not None
if not nicegui_available:
    pytest.skip("NiceGUI kurulu değil (uv sync --group ui)", allow_module_level=True)


def test_ui_module_imports():
    """ui.py import edilebiliyor mu — workspace path setup, tool import çalışıyor mu?"""
    import ui
    assert hasattr(ui, "main_page")
    assert hasattr(ui, "main")
    assert hasattr(ui, "PIPELINE_STEPS")


def test_pipeline_steps_definition_complete():
    """8 step tanımlı, her biri (idx, name, desc, wired) tuple."""
    import ui
    assert len(ui.PIPELINE_STEPS) == 8
    indices = [s[0] for s in ui.PIPELINE_STEPS]
    assert indices == list(range(8))
    for idx, name, desc, wired in ui.PIPELINE_STEPS:
        assert isinstance(name, str) and name
        assert isinstance(desc, str) and desc
        assert isinstance(wired, bool)
    # Tüm 8 adım wired
    wired_indices = [s[0] for s in ui.PIPELINE_STEPS if s[3]]
    assert wired_indices == [0, 1, 2, 3, 4, 5, 6, 7]


def test_scan_dataset_stats_handles_empty_dir(tmp_path):
    """Geçerli ama boş dizin → sıfır sayım, exception fırlatmaz."""
    import ui
    stats = ui.scan_dataset_stats(str(tmp_path))
    assert stats["total"] == 0
    assert stats["by_ext"] == {}
    assert stats["size_bytes"] == 0


def test_scan_dataset_stats_handles_invalid_path():
    """Var olmayan dizin → sıfır, hata yok."""
    import ui
    stats = ui.scan_dataset_stats("/nonexistent/path/xyz")
    assert stats["total"] == 0


def test_scan_dataset_stats_counts_by_extension(tmp_path):
    """Recursive sayım, ext bazlı."""
    import ui
    (tmp_path / "a.jpg").write_bytes(b"\x00")
    (tmp_path / "b.jpg").write_bytes(b"\x00")
    (tmp_path / "c.mp4").write_bytes(b"\x00")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "d.jpg").write_bytes(b"\x00")
    (tmp_path / "ignore.txt").write_bytes(b"hello")  # medya değil

    stats = ui.scan_dataset_stats(str(tmp_path))
    assert stats["total"] == 4
    assert stats["by_ext"][".jpg"] == 3
    assert stats["by_ext"][".mp4"] == 1
    assert stats["subdirs"] == 1


def test_humanize_bytes_progresses_units():
    import ui
    assert "B" in ui.humanize_bytes(500)
    assert "KB" in ui.humanize_bytes(2048)
    assert "MB" in ui.humanize_bytes(5 * 1024 * 1024)


def test_pipeline_state_validity(tmp_path):
    """PipelineState.is_valid_dataset path doğrulaması."""
    import ui
    s = ui.PipelineState(base_path="")
    assert not s.is_valid_dataset()
    s.dataset_path = "/nonexistent"
    assert not s.is_valid_dataset()
    s.dataset_path = str(tmp_path)
    assert s.is_valid_dataset()


# ---------- _reject_dir_for ----------

def test_reject_dir_inside_dataset(tmp_path):
    """Reject klasörü dataset'in İÇİNDE açılır (yanına/kardeşe değil) — recursive
    scan _rejected'ı atladığı için içeride güvenli, dataset self-contained kalır."""
    import ui
    ds = tmp_path / "Pics"
    ds.mkdir()
    ui.STATE.base_path = str(ds)
    reject = ui._reject_dir_for("02-duplicate")
    assert reject == str(ds.resolve() / "_rejected" / "02-duplicate")
    # parent'a (kardeşe) AÇMAMALI
    assert reject != str(ds.resolve().parent / "_rejected" / "02-duplicate")


def test_report_dir_inside_dataset(tmp_path):
    """Rapor klasörü de dataset'in İÇİNDE (reject ile tutarlı) — base parent'a
    değil base'in içine açılır."""
    import ui
    ds = tmp_path / "Pics"
    ds.mkdir()
    rdir = ui._report_dir_for(str(ds))
    assert rdir == str(ds.resolve() / "report")
    assert rdir != str(ds.resolve().parent / "report")


def test_reject_uses_project_root_not_active_dataset(tmp_path):
    """reject PROJE KÖKÜNÜ (base_path) kullanır, aktif dataset_path'i (organized)
    değil — pipeline ilerleyip dataset_path organize çıktısına kaysa bile reject
    proje kökünde toplanır. (Regresyon: validate organized'da çalışınca _rejected
    organized içine düşüyordu.)"""
    import json
    from pathlib import Path
    import ui
    pics = tmp_path / "Pics"
    organized = pics / "organized"
    organized.mkdir(parents=True)
    ui.STATE.base_path = str(pics)
    ui.STATE.last_report_paths.clear()
    ui.STATE.last_stage_params.clear()
    # organize çıktısını manifest'e yaz → dataset_path artık organized döner
    report = ui._report_path("rename_report.json", str(pics))
    Path(report).write_text(json.dumps({"tool": "x", "renames": []}))
    ui._append_manifest_from_report(
        0, report, output_dir=str(organized),
        params={"output_dir": str(organized)},
    )
    # aktif iş klasörü organized'a kaydı
    assert "organized" in ui.STATE.dataset_path
    # AMA reject proje kökünde (Pics), organized'da DEĞİL
    reject = ui._reject_dir_for("01-validate")
    assert reject == str(pics.resolve() / "_rejected" / "01-validate")
    assert "organized" not in reject


# ---------- _aspect_label ----------

def test_aspect_label_common_ratios():
    import ui
    assert ui._aspect_label(1920, 1080) == "16:9"
    assert ui._aspect_label(1080, 1920) == "9:16"
    assert ui._aspect_label(1024, 768) == "4:3"
    assert ui._aspect_label(768, 1024) == "3:4"
    assert ui._aspect_label(1024, 1024) == "1:1"
    assert ui._aspect_label(1500, 1000) == "3:2"
    assert ui._aspect_label(1000, 1500) == "2:3"


def test_aspect_label_within_tolerance():
    """%2 tolerans ile yaygın oranlar yakalanır."""
    import ui
    # 1918×1080 ≈ 16:9 (1.776 vs 1.778, %0.1 fark)
    assert ui._aspect_label(1918, 1080) == "16:9"
    # 920×1240 ≈ 3:4 (0.7419 vs 0.75, %1.1 fark)
    assert ui._aspect_label(920, 1240) == "3:4"


def test_aspect_label_decimal_fallback():
    """Tolerans dışı oranlar decimal döner."""
    import ui
    # 1234×567 → 2.18:1 (yaygın preset değil)
    assert ui._aspect_label(1234, 567) == "2.18:1"


def test_aspect_label_zero_dimensions():
    import ui
    assert ui._aspect_label(0, 0) == ""
    assert ui._aspect_label(100, 0) == ""
    assert ui._aspect_label(0, 100) == ""


# ---------- _bpp_label ----------

def test_bpp_label_thresholds_ai_aware():
    """AI-odaklı eşikler (FULL_SCORE_BPP=0.5)."""
    import ui
    # ≥ 0.5 → yeşil
    label, color = ui._bpp_label(1024, 1024, 600_000)  # BPP ~0.57
    assert "BPP 0.572" in label
    assert "green" in color
    # 0.05 ≤ BPP < 0.5 → sarı
    label, color = ui._bpp_label(1024, 1024, 200_000)  # BPP ~0.19
    assert "yellow" in color
    assert "⚠" not in label
    # < 0.05 → kırmızı + ⚠
    label, color = ui._bpp_label(1024, 1024, 30_000)  # BPP ~0.029
    assert "red" in color
    assert "⚠" in label


def test_bpp_label_zero_dimensions_returns_none():
    import ui
    assert ui._bpp_label(0, 0, 1000) is None
    assert ui._bpp_label(100, 0, 1000) is None
    assert ui._bpp_label(100, 100, 0) is None


# ---------- _path_to_url ----------

def test_path_to_url_prefixes_fs_mount(tmp_path):
    import ui
    p = tmp_path / "x.jpg"
    p.write_bytes(b"")
    url = ui._path_to_url(str(p))
    assert url.startswith("/fs/")
    assert url.endswith("/x.jpg")


# ---------- step_status ----------

def test_step_status_pending_when_no_report(tmp_path):
    import ui
    ui.STATE.reset_callbacks()
    ui.STATE.last_report_paths = {}
    assert ui.step_status(0) == "○"  # pending


def test_step_status_done_when_report_exists(tmp_path):
    import ui
    report = tmp_path / "rename_report.json"
    report.write_text("{}")
    ui.STATE.last_report_paths = {0: str(report)}
    assert ui.step_status(0) == "✓"
    # Cleanup
    ui.STATE.last_report_paths = {}


def test_all_wired_builders_callable():
    """8 step için 8 builder fonksiyonu var ve callable."""
    import ui
    expected = [
        "build_organize_tab",
        "build_validate_tab",
        "build_duplicate_tab",
        "build_quality_tab",
        "build_watermark_tab",
        "build_resize_tab",
        "build_caption_tab",
        "build_golden_set_tab",
    ]
    for name in expected:
        fn = getattr(ui, name, None)
        assert callable(fn), f"{name} eksik veya callable değil"


# ---------- PipelineState.available_outputs ----------

def test_register_output_noop_when_same_as_dataset_path(tmp_path):
    """Output dataset_path ile aynı → register edilmez (no-op)."""
    import ui
    s = ui.PipelineState(base_path=str(tmp_path))
    s.register_output(0, str(tmp_path))
    assert s.available_outputs == {}


def test_register_output_noop_on_empty_output(tmp_path):
    """Boş string output → register edilmez."""
    import ui
    s = ui.PipelineState(base_path=str(tmp_path))
    s.register_output(0, "")
    assert s.available_outputs == {}


def test_register_output_normalizes_path(tmp_path):
    """Output path resolve edilerek saklanır (relative/symlink fark eder)."""
    import ui
    s = ui.PipelineState(base_path=str(tmp_path))
    out = tmp_path / "other_out"
    out.mkdir()
    s.register_output(0, str(out))
    assert s.available_outputs[0] == str(out.resolve())


def test_latest_output_returns_none_when_empty(tmp_path):
    import ui
    s = ui.PipelineState(base_path=str(tmp_path))
    assert s.latest_output() is None


def test_latest_output_picks_max_step_skipping_dismissed(tmp_path):
    """En yüksek step idx kazanır; dismiss edilmiş atlanır."""
    import ui
    s = ui.PipelineState(base_path=str(tmp_path))
    a = tmp_path / "a"
    a.mkdir()
    b = tmp_path / "b"
    b.mkdir()
    s.register_output(0, str(a))
    s.register_output(5, str(b))
    assert s.latest_output()[0] == 5
    s.dismiss_output(5)
    assert s.latest_output()[0] == 0
    s.dismiss_output(0)
    assert s.latest_output() is None


def test_register_clears_dismiss_on_reregister(tmp_path):
    """Dismiss edilmiş bir step yeniden register edilirse dismiss temizlenir."""
    import ui
    s = ui.PipelineState(base_path=str(tmp_path))
    a = tmp_path / "a"
    a.mkdir()
    s.register_output(0, str(a))
    s.dismiss_output(0)
    assert s.latest_output() is None  # dismissed
    b = tmp_path / "b"
    b.mkdir()
    s.register_output(0, str(b))
    assert s.latest_output() == (0, str(b.resolve()))  # re-register clears dismiss


def test_clear_output_removes_and_undismisses(tmp_path):
    """clear_output() undo sonrası çağrılır — output + dismiss temizlenir."""
    import ui
    s = ui.PipelineState(base_path=str(tmp_path))
    a = tmp_path / "a"
    a.mkdir()
    s.register_output(0, str(a))
    s.dismiss_output(0)
    s.clear_output(0)
    assert s.available_outputs == {}
    assert 0 not in s._dismissed_outputs


def test_switch_to_changes_dataset_path_and_notifies(tmp_path):
    """switch_to() banner Switch butonu için: dataset_path değişir, callback tetiklenir."""
    import ui
    s = ui.PipelineState(base_path=str(tmp_path))
    new = tmp_path / "new_root"
    new.mkdir()
    calls = []
    s.on_change(lambda: calls.append(1))
    s.switch_to(str(new))
    assert s.dataset_path == str(new)
    assert calls, "on_change callback tetiklenmedi"
