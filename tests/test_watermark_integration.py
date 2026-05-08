"""
media-watermark-detector'un meta-orchestrator'a integrasyonu için testler.

Tool'un iç davranışını DOĞRULAMAZ — onun için tool'un kendi 33 testi var.
Burada: workspace katmanı + pipeline 04 adımı uçtan uca kontratı.

NOT: Gerçek YOLO inference test'leri model dosyası gerektirdiği için
burada yok. Sadece workspace import + pyproject + path varlığı.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_WATERMARK = REPO_ROOT / "tools" / "04-watermark"


def test_watermark_tool_present():
    assert TOOLS_WATERMARK.exists(), \
        f"{TOOLS_WATERMARK} yok — install-tools.sh çalıştırılmadı mı?"
    assert (TOOLS_WATERMARK / "run.py").is_file()
    assert (TOOLS_WATERMARK / "watermark_core" / "scanner.py").is_file()
    assert (TOOLS_WATERMARK / "watermark_core" / "actions.py").is_file()
    assert (TOOLS_WATERMARK / "watermark_core" / "reporter.py").is_file()


def test_watermark_pyproject_declares_expected_name():
    pyproj = (TOOLS_WATERMARK / "pyproject.toml").read_text()
    assert 'name = "media-watermark-detector"' in pyproj
    import re
    m = re.search(r'version = "(\d+)\.(\d+)\.(\d+)"', pyproj)
    assert m
    assert int(m.group(1)) >= 1


def test_watermark_importable_via_workspace():
    """watermark_core paketi import edilebiliyor (YOLO yüklenmeden)."""
    sys.path.insert(0, str(TOOLS_WATERMARK))
    try:
        from watermark_core import (  # noqa: F401
            find_watermarks,
            apply_action,
            undo_from_report,
            write_report,
            collect_images,
            ScanResult,
            WatermarkResult,
            WatermarkDetection,
            DEFAULT_MODEL_PATH,
            DEFAULT_CONFIDENCE,
        )
        assert callable(find_watermarks)
        assert callable(apply_action)
        assert callable(undo_from_report)
    finally:
        sys.path.pop(0)


def test_watermark_default_model_path_is_user_local():
    """Default model ~/Models altında — repo'ya commit edilmesin."""
    sys.path.insert(0, str(TOOLS_WATERMARK))
    try:
        from watermark_core import DEFAULT_MODEL_PATH
        assert DEFAULT_MODEL_PATH.startswith("/")  # absolute path
        # Default ~/Models — Git LFS gerektirmiyor
        assert "Models" in DEFAULT_MODEL_PATH
    finally:
        sys.path.pop(0)


def test_watermark_collect_images_works(tmp_path):
    """Workspace katmanı sağlıklı: collect_images YOLO yüklemeden çalışır."""
    sys.path.insert(0, str(TOOLS_WATERMARK))
    try:
        from watermark_core import collect_images
        # Sahte birkaç dosya
        (tmp_path / "a.jpg").write_bytes(b"")
        (tmp_path / "b.png").write_bytes(b"")
        (tmp_path / "c.txt").write_bytes(b"")
        files = collect_images(tmp_path, recursive=False)
        names = sorted(p.name for p in files)
        assert names == ["a.jpg", "b.png"]
    finally:
        sys.path.pop(0)


def test_watermark_apply_action_with_synthetic_results(tmp_path):
    """apply_action YOLO çağırmadan çalışır — pipeline kontratını doğrular."""
    sys.path.insert(0, str(TOOLS_WATERMARK))
    try:
        from watermark_core import apply_action
        # Sentetik watermark sonucu — gerçek dosya yarat
        wm_file = tmp_path / "with_wm.jpg"
        wm_file.write_bytes(b"x")
        clean_file = tmp_path / "clean.jpg"
        clean_file.write_bytes(b"y")

        results = [
            {"valid": False, "reason": "watermark_detected (1)",
             "filename": "with_wm.jpg", "path": str(wm_file.resolve()),
             "has_watermark": True, "detection_count": 1, "detections": []},
            {"valid": True, "reason": None,
             "filename": "clean.jpg", "path": str(clean_file.resolve()),
             "has_watermark": False, "detection_count": 0, "detections": []},
        ]
        rejected = tmp_path / "rejected"
        ar = apply_action(results, source_root=tmp_path,
                          action="move", invalid_dir=rejected)
        assert len(ar.entries) == 1
        assert (rejected / "with_wm.jpg").exists()
        assert (tmp_path / "clean.jpg").exists()
    finally:
        sys.path.pop(0)
