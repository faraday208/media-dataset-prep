"""
media-resizer'ın meta-orchestrator'a integrasyonu için testler.

Tool'un iç davranışını DOĞRULAMAZ — onun için tool'un kendi 20 testi var.
Burada: workspace + pipeline 05 adımı uçtan uca kontratı.
"""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_RESIZE = REPO_ROOT / "tools" / "05-resize"


# ---------- Workspace integrity ----------

def test_resize_tool_present():
    assert TOOLS_RESIZE.exists(), \
        f"{TOOLS_RESIZE} yok — install-tools.sh çalıştırılmadı mı?"
    assert (TOOLS_RESIZE / "run.py").is_file()
    assert (TOOLS_RESIZE / "resize_core" / "scanner.py").is_file()
    assert (TOOLS_RESIZE / "resize_core" / "reporter.py").is_file()


def test_resize_pyproject_declares_expected_name():
    pyproj = (TOOLS_RESIZE / "pyproject.toml").read_text()
    assert 'name = "media-resizer"' in pyproj
    import re
    m = re.search(r'version = "(\d+)\.(\d+)\.(\d+)"', pyproj)
    assert m
    assert int(m.group(1)) >= 1


def test_resize_importable_via_workspace():
    """resize_core paketi import edilebiliyor."""
    sys.path.insert(0, str(TOOLS_RESIZE))
    try:
        from resize_core import (  # noqa: F401
            resize_dataset,
            resize_one,
            collect_images,
            undo_from_report,
            write_report,
            REPORT_TOOL,
        )
        assert REPORT_TOOL == "media-resizer"
        assert callable(resize_dataset)
        assert callable(undo_from_report)
    finally:
        sys.path.pop(0)


# ---------- Pipeline handoff ----------

def _run_resize(*args):
    return subprocess.run(
        [sys.executable, str(TOOLS_RESIZE / "run.py"), *args],
        capture_output=True, text=True, cwd=str(TOOLS_RESIZE),
    )


def _make_resize_dataset(root: Path) -> dict:
    """Pipeline 04 sonrası 05'e gelen dataset — mix of large + small."""
    root.mkdir(parents=True, exist_ok=True)
    # Büyük (resize edilecek)
    Image.new("RGB", (4000, 3000), (200, 100, 50)).save(root / "big_a.jpg", quality=85)
    Image.new("RGB", (3500, 2500), (50, 200, 100)).save(root / "big_b.jpg", quality=85)
    # Küçük (skip edilecek)
    Image.new("RGB", (800, 600), (100, 100, 200)).save(root / "small.jpg", quality=85)
    return {"total": 3, "expected_resized": 2, "expected_skipped": 1}


def test_step05_copy_mode_writes_resized_to_output(tmp_path):
    dataset = tmp_path / "step04_out"
    _make_resize_dataset(dataset)
    out = tmp_path / "resized"

    result = _run_resize(
        "-i", str(dataset),
        "-o", str(out),
        "--mode", "copy",
        "--max-width", "1024", "--max-height", "1024",
        "--yes",
    )
    assert result.returncode == 0, result.stdout + result.stderr

    # Büyükler output'a düştü, küçükler skip
    assert (out / "big_a.jpg").exists()
    assert (out / "big_b.jpg").exists()
    assert not (out / "small.jpg").exists()  # skip — kopyalanmaz

    # Ölçü gerçekten değişmiş
    with Image.open(out / "big_a.jpg") as im:
        assert max(im.size) <= 1024

    # Orijinal dataset el değmemiş (copy mode)
    with Image.open(dataset / "big_a.jpg") as im:
        assert max(im.size) > 1024


def test_step05_report_provides_undo_contract(tmp_path):
    dataset = tmp_path / "ds"
    _make_resize_dataset(dataset)
    out = tmp_path / "out"
    assert _run_resize(
        "-i", str(dataset), "-o", str(out),
        "--mode", "copy",
        "--max-width", "1024", "--max-height", "1024",
        "--yes",
    ).returncode == 0

    report = json.loads((out / "resize_report.json").read_text())
    assert report["tool"] == "media-resizer"
    assert report["mode"] == "copy"
    assert report["summary"]["total_scanned"] == 3
    # actions undo için yeterli
    for entry in report["actions"]:
        assert Path(entry["original"]).is_absolute()
        assert "output_path" in entry


def test_step05_undo_removes_copy_outputs(tmp_path):
    dataset = tmp_path / "ds"
    _make_resize_dataset(dataset)
    out = tmp_path / "out"
    assert _run_resize(
        "-i", str(dataset), "-o", str(out),
        "--mode", "copy",
        "--max-width", "1024", "--max-height", "1024",
        "--yes",
    ).returncode == 0

    # Output gerçekten doldu
    assert (out / "big_a.jpg").exists()

    # Undo
    assert _run_resize(
        "--undo", str(out / "resize_report.json"),
    ).returncode == 0

    # Output dosyaları silindi, orijinal el değmemiş
    assert not (out / "big_a.jpg").exists()
    assert not (out / "big_b.jpg").exists()
    assert (dataset / "big_a.jpg").exists()


def test_step05_dry_run_no_filesystem_change(tmp_path):
    dataset = tmp_path / "ds"
    _make_resize_dataset(dataset)
    out = tmp_path / "out"
    assert _run_resize(
        "-i", str(dataset), "-o", str(out),
        "--mode", "copy",
        "--max-width", "1024", "--max-height", "1024",
        "--yes",
        "--dry-run",
    ).returncode == 0
    # Hiçbir output dosyası yazılmadı
    assert not (out / "big_a.jpg").exists()
    assert not (out / "big_b.jpg").exists()
    # Ama rapor yazıldı (planlamayı yansıtsın)
    report_path = out / "resize_report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text())
    assert report["dry_run"] is True
    assert report["summary"]["resized"] == 2


def test_step05_run_parser_imports():
    """run.py argparse build edebiliyor — wrapper sağlıklı."""
    sys.modules.pop("run", None)
    sys.path.insert(0, str(TOOLS_RESIZE))
    try:
        from run import _build_parser
        args = _build_parser().parse_args([
            "-i", "/x", "-o", "/y",
            "--mode", "copy",
            "--max-width", "1024", "--max-height", "1024",
        ])
        assert args.input == "/x"
        assert args.output == "/y"
        assert args.mode == "copy"
        assert args.max_width == 1024
    finally:
        sys.path.pop(0)
        sys.modules.pop("run", None)
