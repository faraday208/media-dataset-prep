"""
media-validator'un meta-orchestrator'a integrasyonu için testler.

Tool'un iç davranışını DOĞRULAMAZ — onun için tool'un kendi 39 testi var.
Burada sadece 'workspace katmanı çalışıyor mu' ve 'pipeline 1 adımı uçtan uca
elden ele geçiyor mu' sorularını cevaplıyoruz.
"""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_VALIDATE = REPO_ROOT / "tools" / "01-validate"


# ---------- Workspace integrity ----------

def test_validate_tool_is_present_at_workspace_path():
    """tools/01-validate/ var ve içinde run.py + src/scanner.py erişilebilir."""
    assert TOOLS_VALIDATE.exists(), \
        f"{TOOLS_VALIDATE} yok — `scripts/install-tools.sh` çalıştırılmadı mı?"
    assert (TOOLS_VALIDATE / "run.py").is_file()
    assert (TOOLS_VALIDATE / "src" / "scanner.py").is_file()
    assert (TOOLS_VALIDATE / "src" / "validators" / "file_validator.py").is_file()


def test_validate_tool_pyproject_declares_expected_name():
    """Workspace member'ın pyproject'i 'media-validator' adını ilan eder."""
    pyproj = TOOLS_VALIDATE / "pyproject.toml"
    assert pyproj.exists()
    content = pyproj.read_text()
    assert 'name = "media-validator"' in content
    # v0.3.0+ gerekli (paket adı media-validator'a geçiş)
    import re
    m = re.search(r'version = "(\d+)\.(\d+)\.(\d+)"', content)
    assert m, "version field bulunamadı"
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    assert (major, minor, patch) >= (0, 3, 0), f"v0.3.0+ gerekli, bulundu: {m.group(0)}"


def test_validator_importable_via_workspace():
    """uv workspace ile in-process kullanım çalışır."""
    sys.path.insert(0, str(TOOLS_VALIDATE))
    try:
        from src import (  # noqa: F401
            FileValidator,
            collect_images,
            apply_action,
            undo_from_report,
            write_report,
        )
        assert callable(FileValidator)
        assert callable(collect_images)
        assert callable(apply_action)
        assert callable(undo_from_report)
    finally:
        sys.path.pop(0)


# ---------- Pipeline handoff (e2e smoke) ----------

def _run_validator(*args):
    """Validator'ı tools/01-validate konumundan CLI olarak çağır."""
    script = TOOLS_VALIDATE / "run.py"
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, cwd=str(TOOLS_VALIDATE),
    )


def _make_validation_dataset(root: Path) -> dict:
    """Pipeline'ın validate aşamasına gelen tipik karışık dataset."""
    root.mkdir(parents=True, exist_ok=True)
    # Geçerli (organizer'ın output'una benzer)
    Image.new("RGB", (1024, 1024), "red").save(root / "Dataset_1.jpg", quality=85)
    Image.new("RGB", (1024, 768), "green").save(root / "Dataset_2.jpg", quality=85)
    Image.new("RGB", (800, 1200), "blue").save(root / "Dataset_3.jpg", quality=85)
    # Geçersiz: çok küçük
    Image.new("RGB", (200, 200), "white").save(root / "tiny.jpg", quality=85)
    # Geçersiz: aspect
    Image.new("RGB", (4096, 600), "yellow").save(root / "wide.jpg", quality=85)
    # Geçersiz: bozuk
    (root / "broken.jpg").write_bytes(b"not a real jpeg")
    return {"valid": 3, "invalid": 3, "total": 6}


def test_step01_filters_invalid_files_via_move(tmp_path):
    """
    E2E: organizer-output benzeri dataset → 01 validator (move) →
    invalid'ler /rejected'a taşındı, valid'ler kaynakta kaldı.
    """
    dataset = tmp_path / "step00_out"
    expected = _make_validation_dataset(dataset)
    rejected = tmp_path / "rejected"

    result = _run_validator(
        "-i", str(dataset),
        "--invalid-action", "move",
        "--invalid-dir", str(rejected),
        "--min-file-size-kb", "0.5",  # broken.jpg corrupted reason'a düşsün
    )
    assert result.returncode == 0, result.stdout + result.stderr

    # Kaynak: sadece valid dosyalar
    remaining = sorted(p.name for p in dataset.iterdir() if p.is_file() and p.suffix == ".jpg")
    assert remaining == ["Dataset_1.jpg", "Dataset_2.jpg", "Dataset_3.jpg"]

    # Hedef: invalid dosyalar
    moved = sorted(p.name for p in rejected.iterdir() if p.is_file() and p.suffix == ".jpg")
    assert "tiny.jpg" in moved
    assert "wide.jpg" in moved
    assert "broken.jpg" in moved

    # Rapor invalid_dir altında
    report = rejected / "validate_report.json"
    assert report.exists()


def test_step01_report_provides_undo_contract(tmp_path):
    """
    validate_report.json downstream / kullanıcının pipeline'ı geri alabilmesi için
    yeterli bilgiyi içerir: tool, action, actions[].original/moved_to.
    """
    dataset = tmp_path / "ds"
    _make_validation_dataset(dataset)
    rejected = tmp_path / "rejected"

    result = _run_validator(
        "-i", str(dataset),
        "--invalid-action", "move",
        "--invalid-dir", str(rejected),
        "--min-file-size-kb", "0.5",
    )
    assert result.returncode == 0

    report = json.loads((rejected / "validate_report.json").read_text())
    assert report["tool"] == "media-validator"
    assert report["action"] == "move"
    assert report["summary"]["invalid"] >= 3
    assert report["summary"]["valid"] >= 3
    for entry in report["actions"]:
        assert Path(entry["original"]).is_absolute()
        assert "moved_to" in entry
        assert Path(entry["moved_to"]).is_absolute()
        assert entry["reason"]  # boş değil


def test_step01_undo_restores_pipeline_to_pre_run_state(tmp_path):
    """Pipeline'ın "01'i geri al" workflow'u: move → undo → orijinal dataset."""
    dataset = tmp_path / "ds"
    _make_validation_dataset(dataset)
    rejected = tmp_path / "rejected"

    files_before = sorted(p.name for p in dataset.iterdir() if p.is_file())

    # 1) Forward
    result = _run_validator(
        "-i", str(dataset),
        "--invalid-action", "move",
        "--invalid-dir", str(rejected),
        "--min-file-size-kb", "0.5",
    )
    assert result.returncode == 0

    # 2) Undo
    result = _run_validator("--undo", str(rejected / "validate_report.json"))
    assert result.returncode == 0

    # Dataset eski haline döndü
    files_after = sorted(p.name for p in dataset.iterdir() if p.is_file())
    # validate_report.json forward run'da source'a yazılabilirdi — biz burada
    # invalid_dir'e yazdığımız için kaynak kirlenmedi
    assert set(files_before).issubset(set(files_after))


def test_step01_dry_run_writes_report_without_moving(tmp_path):
    """
    Dry-run: rapor üretilir, dosyalar yerinde kalır.
    UI 'önizleme' modunda bunu kullanacak.
    """
    dataset = tmp_path / "ds"
    _make_validation_dataset(dataset)
    rejected = tmp_path / "rejected"

    result = _run_validator(
        "-i", str(dataset),
        "--invalid-action", "move",
        "--invalid-dir", str(rejected),
        "--min-file-size-kb", "0.5",
        "--dry-run",
    )
    assert result.returncode == 0

    # Dosyalar yerinde
    assert (dataset / "tiny.jpg").exists()
    assert (dataset / "broken.jpg").exists()
    # Rejected'a taşınmadı
    assert not (rejected / "tiny.jpg").exists()
    # Ama rapor yazıldı
    assert (rejected / "validate_report.json").exists()
    report = json.loads((rejected / "validate_report.json").read_text())
    assert report["summary"]["invalid"] >= 3


def test_step01_output_consumable_as_duplicate_input(tmp_path):
    """
    Pipeline kontratı: 01'in (move sonrası) output'u 02 duplicate-finder'ın
    girdisidir. Yani: temizlenmiş dataset, sadece geçerli .jpg/.png/.webp.
    """
    dataset = tmp_path / "ds"
    _make_validation_dataset(dataset)
    rejected = tmp_path / "rejected"

    result = _run_validator(
        "-i", str(dataset),
        "--invalid-action", "move",
        "--invalid-dir", str(rejected),
        "--min-file-size-kb", "0.5",
    )
    assert result.returncode == 0

    # Downstream (02 duplicate) bu dataset'i input alacak
    survivors = list(dataset.glob("*.jpg"))
    assert len(survivors) == 3
    for img in survivors:
        # Pillow ile decode edilebiliyor mu?
        with Image.open(img) as im:
            im.load()
            assert im.size[0] >= 512 and im.size[1] >= 512  # min_short_edge default
