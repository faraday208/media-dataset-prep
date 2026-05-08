"""
media-deduplicator'un meta-orchestrator'a integrasyonu için testler.

Tool'un iç davranışını DOĞRULAMAZ — onun için tool'un kendi 41 testi var.
Burada: workspace katmanı + pipeline 02 adımı uçtan uca kontratı.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DUPLICATE = REPO_ROOT / "tools" / "02-duplicate"


# ---------- Workspace integrity ----------

def test_duplicate_tool_present():
    assert TOOLS_DUPLICATE.exists()
    assert (TOOLS_DUPLICATE / "run.py").is_file()
    assert (TOOLS_DUPLICATE / "core" / "scanner.py").is_file()
    assert (TOOLS_DUPLICATE / "core" / "actions.py").is_file()
    assert (TOOLS_DUPLICATE / "core" / "reporter.py").is_file()


def test_duplicate_tool_pyproject_declares_expected_name():
    pyproj = (TOOLS_DUPLICATE / "pyproject.toml").read_text()
    assert 'name = "media-deduplicator"' in pyproj
    # v1.0.0+ — yeni clean release
    import re
    m = re.search(r'version = "(\d+)\.(\d+)\.(\d+)"', pyproj)
    assert m
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    assert (major, minor, patch) >= (1, 0, 0)


def test_duplicate_tool_importable_via_workspace():
    sys.path.insert(0, str(TOOLS_DUPLICATE))
    try:
        from core import (  # noqa: F401
            find_exact_duplicates,
            find_similar_images,
            apply_action,
            undo_from_report,
            write_report,
            collect_images,
        )
        assert callable(find_exact_duplicates)
        assert callable(apply_action)
    finally:
        sys.path.pop(0)


# ---------- Pipeline handoff ----------

def _run_dedup(*args):
    return subprocess.run(
        [sys.executable, str(TOOLS_DUPLICATE / "run.py"), *args],
        capture_output=True, text=True, cwd=str(TOOLS_DUPLICATE),
    )


def _make_dataset_with_duplicates(root: Path) -> dict:
    """Pipeline'ın 01 validate sonrası 02 duplicate'a gelen tipik dataset."""
    root.mkdir(parents=True, exist_ok=True)
    # 3 birebir aynı dosya (md5 grubu)
    img = Image.new("RGB", (512, 512), "red")
    img.save(root / "Dataset_1.jpg", quality=85)
    shutil.copy(root / "Dataset_1.jpg", root / "Dataset_2.jpg")
    shutil.copy(root / "Dataset_1.jpg", root / "Dataset_3.jpg")
    # 2 unique dosya
    Image.new("RGB", (512, 512), "blue").save(root / "Dataset_4.jpg", quality=85)
    Image.new("RGB", (512, 512), "green").save(root / "Dataset_5.jpg", quality=85)
    return {"total": 5, "duplicates": 2, "unique": 3}


def test_step02_finds_exact_duplicates_via_move(tmp_path):
    """E2E: 01 validate output → 02 dedup (move) → unique kaynakta, dup'lar /rejected'da."""
    dataset = tmp_path / "step01_out"
    _make_dataset_with_duplicates(dataset)
    rejected = tmp_path / "dup_rejected"

    result = _run_dedup(
        "-i", str(dataset),
        "--invalid-action", "move",
        "--invalid-dir", str(rejected),
        "--keep-strategy", "first",
    )
    assert result.returncode == 0, result.stdout + result.stderr

    # Kaynak: 3 dosya (1 keeper a-grubundan + 2 unique)
    survivors = sorted(p.name for p in dataset.glob("*.jpg"))
    assert len(survivors) == 3
    # Hedef: 2 dosya (a2 + a3)
    moved = sorted(p.name for p in rejected.glob("*.jpg"))
    assert len(moved) == 2

    # Rapor invalid_dir altında
    assert (rejected / "duplicate_report.json").exists()


def test_step02_report_provides_undo_contract(tmp_path):
    """duplicate_report.json undo + downstream review için kontratı sağlıyor."""
    dataset = tmp_path / "ds"
    _make_dataset_with_duplicates(dataset)
    rejected = tmp_path / "rej"

    result = _run_dedup(
        "-i", str(dataset),
        "--invalid-action", "move",
        "--invalid-dir", str(rejected),
    )
    assert result.returncode == 0

    report = json.loads((rejected / "duplicate_report.json").read_text())
    assert report["tool"] == "media-deduplicator"
    assert report["mode"] == "exact"
    assert report["summary"]["groups"] >= 1
    # actions[]: undo için minimum alan
    for entry in report["actions"]:
        assert Path(entry["original"]).is_absolute()
        assert "moved_to" in entry
        assert entry["algorithm"] == "md5"
    # groups[]: review için minimum alan (UI gallery için kritik)
    for g in report["groups"]:
        assert "files" in g
        assert all("path" in f for f in g["files"])
        assert "kept" in g  # apply_action keeper'ı işaretledi


def test_step02_undo_restores_pipeline_state(tmp_path):
    dataset = tmp_path / "ds"
    _make_dataset_with_duplicates(dataset)
    rejected = tmp_path / "rej"

    files_before = sorted(p.name for p in dataset.glob("*.jpg"))

    # Forward
    assert _run_dedup(
        "-i", str(dataset),
        "--invalid-action", "move",
        "--invalid-dir", str(rejected),
    ).returncode == 0

    # Undo
    assert _run_dedup("--undo", str(rejected / "duplicate_report.json")).returncode == 0

    files_after = sorted(p.name for p in dataset.glob("*.jpg"))
    assert files_after == files_before


def test_step02_dry_run_writes_report_no_filesystem_change(tmp_path):
    dataset = tmp_path / "ds"
    _make_dataset_with_duplicates(dataset)
    rejected = tmp_path / "rej"

    result = _run_dedup(
        "-i", str(dataset),
        "--invalid-action", "move",
        "--invalid-dir", str(rejected),
        "--dry-run",
    )
    assert result.returncode == 0
    # Dosyalar yerinde
    assert len(list(dataset.glob("*.jpg"))) == 5
    # Rejected'a taşınmadı
    assert not list(rejected.glob("*.jpg"))
    # Ama rapor yazıldı
    assert (rejected / "duplicate_report.json").exists()


def test_step02_output_consumable_as_quality_input(tmp_path):
    """02 sonrası output 03 media-quality-checker'ın girdisi olur:
    temizlenmiş, unique görsel seti."""
    dataset = tmp_path / "ds"
    _make_dataset_with_duplicates(dataset)
    rejected = tmp_path / "rej"

    assert _run_dedup(
        "-i", str(dataset),
        "--invalid-action", "move",
        "--invalid-dir", str(rejected),
    ).returncode == 0

    survivors = list(dataset.glob("*.jpg"))
    assert len(survivors) == 3
    for img in survivors:
        with Image.open(img) as im:
            im.load()
