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
