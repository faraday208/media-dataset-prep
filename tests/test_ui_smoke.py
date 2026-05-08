"""
UI smoke testi — ui.py modülü import edilebiliyor mu, gerekli yardımcılar
çalışıyor mu? Gradio/NiceGUI sunucusunu ayağa kaldırmıyor (HTTP testi yok),
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
    # 00 organize, 01 validate, 02 duplicate wired
    wired_indices = [s[0] for s in ui.PIPELINE_STEPS if s[3]]
    assert wired_indices == [0, 1, 2]


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
    s = ui.PipelineState(dataset_path="")
    assert not s.is_valid_dataset()
    s.dataset_path = "/nonexistent"
    assert not s.is_valid_dataset()
    s.dataset_path = str(tmp_path)
    assert s.is_valid_dataset()


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
