"""
media-organizer'ın meta-orchestrator'a integrasyonu için testler.

Bu testler tool'un iç davranışını DOĞRULAMAZ — onun için tool repo'sunun kendi
testleri var. Burada sadece 'workspace katmanı çalışıyor mu' ve 'pipeline 0
adımı uçtan uca elden ele geçiyor mu' sorularını cevaplıyoruz.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_ORGANIZE = REPO_ROOT / "tools" / "00-organize"


# ---------- Workspace integrity ----------

def test_organize_tool_is_present_at_workspace_path():
    """tools/00-organize/ var ve içinde media_organizer.py erişilebilir."""
    assert TOOLS_ORGANIZE.exists(), \
        f"{TOOLS_ORGANIZE} yok — `scripts/install-tools.sh` çalıştırılmadı mı?"
    assert (TOOLS_ORGANIZE / "media_organizer.py").is_file()


def test_organize_tool_pyproject_declares_expected_name():
    """Workspace member'ın pyproject'i 'media-organizer' adını ilan eder."""
    pyproj = TOOLS_ORGANIZE / "pyproject.toml"
    assert pyproj.exists()
    content = pyproj.read_text()
    assert 'name = "media-organizer"' in content


def test_media_organizer_importable_via_workspace():
    """uv workspace ile `import media_organizer` çalışır (in-process kullanım)."""
    # Tool'un dizinini sys.path'e ekle (workspace .venv'de paket olarak değil
    # script-mode kurulu — meta in-process import için path injection yapar).
    sys.path.insert(0, str(TOOLS_ORGANIZE))
    try:
        import media_organizer  # noqa: F401
        # Public API erişilebilir mi?
        assert callable(media_organizer.scan_directory)
        assert callable(media_organizer.generate_rename_plan)
        assert callable(media_organizer.generate_tree_rename_plan)
        assert callable(media_organizer.undo_from_report)
    finally:
        sys.path.pop(0)


# ---------- Pipeline handoff (e2e smoke) ----------

def _run_organizer(*args):
    """Organizer'ı tools/00-organize konumundan CLI olarak çağır."""
    script = TOOLS_ORGANIZE / "media_organizer.py"
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True,
    )


def test_step00_outputs_flat_dataset_with_normalized_names(mini_dataset, tmp_path):
    """
    E2E: ham veri → 00 organizer (recursive flat) → düz, kronolojik isimli output.
    Pipeline'ın downstream'ine (validate/duplicate/caption) sunulan kontratı temsil eder.
    """
    out = tmp_path / "step00_out"
    result = _run_organizer(
        str(mini_dataset),
        "--recursive", "flat",
        "--output-dir", str(out),
        "--prefix", "Dataset",
    )
    assert result.returncode == 0, result.stdout + result.stderr

    # Output kontratı: tek seviye (flat), prefix-numbered, type-segmented
    files = sorted(p.name for p in out.iterdir() if p.is_file())
    jpgs = [n for n in files if n.endswith('.jpg')]
    mp4s = [n for n in files if n.endswith('.mp4')]
    mp3s = [n for n in files if n.endswith('.mp3')]

    # 5 jpg + 1 mp4 + 1 mp3 = 7 medya (mini_dataset'in toplamı)
    assert len(jpgs) == 5
    assert len(mp4s) == 1
    assert len(mp3s) == 1

    # Her tip kendi 1..N sequence'ında
    assert jpgs == [f"Dataset_{i}.jpg" for i in range(1, 6)]
    assert mp4s == ["Dataset_1.mp4"]
    assert mp3s == ["Dataset_1.mp3"]

    # Caption tool'un eşleştirme kontratı: img.jpg ↔ img.txt mümkün olmalı
    # (filename'de boşluk/özel karakter yok)
    for name in jpgs:
        assert ' ' not in name
        assert all(c.isascii() for c in name)


def test_step00_report_provides_undo_contract(mini_dataset, tmp_path):
    """
    rename_report.json downstream'in pipeline'ı geri alabilmesi için
    yeterli bilgiyi içerir: mode, old_path, new_path, total_files.
    """
    out = tmp_path / "step00_out"
    result = _run_organizer(
        str(mini_dataset),
        "--recursive", "flat",
        "--output-dir", str(out),
    )
    assert result.returncode == 0

    report = json.loads((out / "rename_report.json").read_text())
    assert report['mode'] == 'copy'
    assert report['total_files'] == 7
    for entry in report['renames']:
        assert os.path.isabs(entry['old_path'])
        assert os.path.isabs(entry['new_path'])
        assert entry['extension'] in ('.jpg', '.mp4', '.mp3')


def test_step00_undo_restores_pipeline_to_pre_run_state(mini_dataset, tmp_path):
    """
    Pipeline'ın "00'ı geri al" workflow'u: undo + cleanup mirror dirleri sileyim.
    Kaynak veri tek değiştirilmemiş kalmalı (copy modu).
    """
    out = tmp_path / "step00_out"

    # 1) İleri çalıştır (tree mod, mirror oluşur)
    result = _run_organizer(
        str(mini_dataset),
        "--recursive", "tree",
        "--output-dir", str(out),
    )
    assert result.returncode == 0
    assert (out / "camera").is_dir()
    assert (out / "misc").is_dir()

    src_count_before = sum(1 for _ in mini_dataset.rglob('*') if _.is_file())

    # 2) Undo + cleanup
    result = _run_organizer(
        "--undo", str(out / "rename_report.json"),
        "--cleanup-empty-dirs",
    )
    assert result.returncode == 0

    # Kaynak veri dokunulmadı
    src_count_after = sum(1 for _ in mini_dataset.rglob('*') if _.is_file())
    assert src_count_before == src_count_after

    # Mirror alt klasörleri temizlendi
    assert not (out / "camera").exists()
    assert not (out / "misc").exists()


def test_step00_output_consumable_as_caption_input(mini_dataset, tmp_path):
    """
    Pipeline kontratı: 00'ın output'u 06 (caption) tool'un input formatına
    uygun olmalı. Yani: düz klasör, normalize edilmiş .jpg dosyaları,
    yan yana .txt caption dosyası eklenebilir.
    """
    out = tmp_path / "step00_out"
    result = _run_organizer(
        str(mini_dataset),
        "--recursive", "flat",
        "--output-dir", str(out),
        "--prefix", "img",
    )
    assert result.returncode == 0

    # Caption pipeline'ının yapacağı: her image için yan yana .txt yaz
    for img in out.glob("*.jpg"):
        caption_path = img.with_suffix('.txt')
        caption_path.write_text("test caption")
        assert caption_path.exists()
        # img + caption stem aynı (caption tool'un eşleştirme kontratı)
        assert img.stem == caption_path.stem
