"""
media-quality-checker'ın meta-orchestrator'a integrasyonu için testler.

Tool'un iç davranışını DOĞRULAMAZ — onun için tool'un kendi 44 testi var.
Burada: workspace + pipeline 03 adımı uçtan uca kontratı.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_QUALITY = REPO_ROOT / "tools" / "03-quality"


# ---------- Workspace integrity ----------

def test_quality_tool_present():
    assert TOOLS_QUALITY.exists()
    assert (TOOLS_QUALITY / "run.py").is_file()
    assert (TOOLS_QUALITY / "quality_core" / "scanner.py").is_file()
    assert (TOOLS_QUALITY / "quality_core" / "actions.py").is_file()
    assert (TOOLS_QUALITY / "quality_core" / "reporter.py").is_file()
    assert (TOOLS_QUALITY / "quality_core" / "checkers" / "blur_checker.py").is_file()


def test_quality_pyproject_declares_expected_name():
    pyproj = (TOOLS_QUALITY / "pyproject.toml").read_text()
    assert 'name = "media-quality-checker"' in pyproj
    import re
    m = re.search(r'version = "(\d+)\.(\d+)\.(\d+)"', pyproj)
    assert m
    major = int(m.group(1))
    assert major >= 1


def test_quality_importable_via_workspace():
    """Workspace'de quality_core paket adıyla — `core` çakışmasından kaçınmak
    için (media-deduplicator zaten `core` kullanıyor)."""
    sys.path.insert(0, str(TOOLS_QUALITY))
    try:
        from quality_core import (  # noqa: F401
            find_quality_issues,
            apply_action,
            undo_from_report,
            write_report,
            BlurChecker,
            BPPChecker,
            BrightnessChecker,
            ContrastChecker,
            QualityResult,
            ScanResult,
        )
        assert callable(find_quality_issues)
        assert callable(apply_action)
    finally:
        sys.path.pop(0)


# ---------- Pipeline handoff ----------

def _run_quality(*args):
    return subprocess.run(
        [sys.executable, str(TOOLS_QUALITY / "run.py"), *args],
        capture_output=True, text=True, cwd=str(TOOLS_QUALITY),
    )


def _make_quality_dataset(root: Path) -> dict:
    """Pipeline 02 sonrası 03'e gelen dataset — karışık quality."""
    root.mkdir(parents=True, exist_ok=True)
    # Normal görseller (sharp, makul brightness)
    for i in range(3):
        arr = np.random.randint(0, 256, (512, 512, 3), dtype=np.uint8)
        Image.fromarray(arr).save(root / f"normal_{i}.jpg", "JPEG", quality=90)
    # Blurry
    arr = np.random.randint(0, 256, (512, 512, 3), dtype=np.uint8)
    Image.fromarray(arr).filter(ImageFilter.GaussianBlur(radius=10))\
        .save(root / "blurry.jpg", "JPEG", quality=90)
    # Dark
    Image.new("RGB", (512, 512), (10, 10, 10))\
        .save(root / "dark.jpg", "JPEG", quality=90)
    return {"total": 5, "expected_invalid": 2}


def test_step03_filters_low_quality_via_move(tmp_path):
    dataset = tmp_path / "step02_out"
    _make_quality_dataset(dataset)
    rejected = tmp_path / "rejected"

    result = _run_quality(
        "-i", str(dataset),
        "--invalid-action", "move",
        "--invalid-dir", str(rejected),
    )
    assert result.returncode == 0, result.stdout + result.stderr

    # blurry + dark → rejected
    moved = sorted(p.name for p in rejected.glob("*.jpg"))
    assert "blurry.jpg" in moved or "dark.jpg" in moved

    # Rapor invalid_dir altında
    assert (rejected / "quality_report.json").exists()


def test_step03_report_provides_undo_contract(tmp_path):
    dataset = tmp_path / "ds"
    _make_quality_dataset(dataset)
    rejected = tmp_path / "rej"

    assert _run_quality(
        "-i", str(dataset),
        "--invalid-action", "move",
        "--invalid-dir", str(rejected),
    ).returncode == 0

    report = json.loads((rejected / "quality_report.json").read_text())
    assert report["tool"] == "media-quality-checker"
    assert "enabled_checks" in report
    assert report["summary"]["total_scanned"] >= 5
    # actions undo için yeterli
    for entry in report["actions"]:
        assert Path(entry["original"]).is_absolute()
        assert "moved_to" in entry
        assert entry["reason"]


def test_step03_undo_restores_pipeline_state(tmp_path):
    dataset = tmp_path / "ds"
    _make_quality_dataset(dataset)
    rejected = tmp_path / "rej"

    files_before = sorted(p.name for p in dataset.glob("*.jpg"))
    assert _run_quality(
        "-i", str(dataset),
        "--invalid-action", "move",
        "--invalid-dir", str(rejected),
    ).returncode == 0
    assert _run_quality(
        "--undo", str(rejected / "quality_report.json"),
    ).returncode == 0

    files_after = sorted(p.name for p in dataset.glob("*.jpg"))
    assert files_after == files_before


def test_step03_check_filter(tmp_path):
    """--check blur sadece blur metric'i set eder, diğerleri None."""
    dataset = tmp_path / "ds"
    _make_quality_dataset(dataset)
    assert _run_quality(
        "-i", str(dataset),
        "--check", "blur",
    ).returncode == 0
    report = json.loads((dataset / "quality_report.json").read_text())
    assert report["enabled_checks"] == ["blur"]
    for r in report["results"]:
        assert r["blur_score"] is not None
        assert r["brightness_score"] is None


def test_step03_dry_run_no_filesystem_change(tmp_path):
    dataset = tmp_path / "ds"
    _make_quality_dataset(dataset)
    rejected = tmp_path / "rej"
    assert _run_quality(
        "-i", str(dataset),
        "--invalid-action", "move",
        "--invalid-dir", str(rejected),
        "--dry-run",
    ).returncode == 0
    # Dataset yerinde
    assert len(list(dataset.glob("*.jpg"))) == 5
    # Rejected'a taşınmadı
    assert not list(rejected.glob("*.jpg"))
    # Ama rapor yazıldı
    assert (rejected / "quality_report.json").exists()


def test_step03_output_consumable_as_resize_input(tmp_path):
    """03 sonrası output → 05 media-resizer girdisi."""
    dataset = tmp_path / "ds"
    _make_quality_dataset(dataset)
    rejected = tmp_path / "rej"
    assert _run_quality(
        "-i", str(dataset),
        "--invalid-action", "move",
        "--invalid-dir", str(rejected),
    ).returncode == 0
    survivors = list(dataset.glob("*.jpg"))
    # En az "normal_*" valid olmalı
    assert any("normal" in p.name for p in survivors)
    for img in survivors:
        with Image.open(img) as im:
            im.load()
