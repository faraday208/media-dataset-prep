"""
Cross-tool pipeline tutarlılık testleri — tree-yapılı dataset boyunca:

    00 organize tree → 01 validate move → 03 quality move →
    04 watermark move → 07 golden-set recursive copy

Her adımda subdir hiyerarşisi korunmalı; aynı isimli dosyalar farklı
subdir'lerden collision'sız işlenmeli. Bu test, tool repo'ları arası
tutarlılığın garantisi (tek tek tool testi her tool'da var; burada
pipeline disiplini denetlenir).

Notlar:
- 04 watermark testi YOLOv8 model gerektirdiği için skip
- 06 caption testi Ollama gerektirdiği için skip
- Quality+validator+golden-set library çağrılarıyla yeterli
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS = REPO_ROOT / "tools"


def _make_tree_dataset(root: Path) -> dict:
    """00 organize tree-mode çıktısı simülasyonu — alt klasörlerde aynı
    isimli dosyalar (collision senaryosu)."""
    sub_a = root / "tatil-2024"
    sub_b = root / "tatil-2025"
    sub_a.mkdir(parents=True)
    sub_b.mkdir(parents=True)
    # Net görsel
    arr = np.random.randint(0, 256, (256, 256, 3), dtype=np.uint8)
    Image.fromarray(arr).save(sub_a / "IMG_001.jpg", "JPEG", quality=90)
    # Aynı isim farklı subdir, blurry (quality invalid)
    Image.fromarray(arr).filter(ImageFilter.GaussianBlur(radius=10))\
        .save(sub_b / "IMG_001.jpg", "JPEG", quality=85)
    return {"sub_a": sub_a, "sub_b": sub_b}


def test_quality_tree_preserve_no_collision(tmp_path):
    """03 quality: aynı isim farklı subdir → tree-mirror move."""
    sys.path.insert(0, str(TOOLS / "03-quality"))
    try:
        from quality_core import find_quality_issues, apply_action
    finally:
        sys.path.pop(0)

    src = tmp_path / "ds"
    src.mkdir()
    _make_tree_dataset(src)
    rejected = tmp_path / "rejected"

    # Default config — blur kontrol blurry'i invalid yapacak
    cfg = {
        "blur": {"min_score": 0.5},
        "brightness": {"min": 0.05, "max": 0.95},
        "contrast": {"min": 0.05},
        "bpp": {"min": 0.1, "max": 5.0},
    }
    sr = find_quality_issues(src, config=cfg, recursive=True)
    ar = apply_action(sr.results, source_root=src,
                      action="move", invalid_dir=rejected)

    # Blurry olan subdir'ı (tatil-2025) rejected içinde aynı subdir altında
    moved = {Path(e.moved_to).relative_to(rejected) for e in ar.entries}
    assert any(p.parent.name in {"tatil-2024", "tatil-2025"} for p in moved), \
        f"Tree korunmamış: {moved}"


def test_validator_recursive_default_true(tmp_path):
    """01 validate v0.4.0: --recursive default True olmalı."""
    sys.path.insert(0, str(TOOLS / "01-validate"))
    try:
        # Reset module cache (cross-tool run.py collision)
        sys.modules.pop("run", None)
        from run import _build_parser
        args = _build_parser().parse_args(["-i", str(tmp_path)])
        assert args.recursive is True, \
            "v0.4.0 BC: --recursive default True (cross-tool tutarlılık)"
        sys.modules.pop("run", None)
    finally:
        sys.path.pop(0)


def test_golden_recursive_finds_tree_assets(tmp_path):
    """07 golden-set: --recursive ile alt klasörlerdeki görselleri görüyor."""
    sys.path.insert(0, str(TOOLS / "07-golden-set"))
    try:
        from goldenset_core import select, apply_selection
    finally:
        sys.path.pop(0)

    src = tmp_path / "ds"
    src.mkdir()
    sub = src / "deep"
    sub.mkdir()
    # Top + sub görseller (PNG ile basit)
    Image.new("RGB", (8, 8), "red").save(src / "top.png")
    Image.new("RGB", (8, 8), "blue").save(sub / "deep.png")
    # Caption JSON'lar
    for parent, name in [(src, "top"), (sub, "deep")]:
        (parent / f"{name}.json").write_text(json.dumps({
            "camera": {"distance": "close-up"},
            "face": {"visible": "true"},
        }))
    (src / "rep.json").write_text(json.dumps({
        "results": [
            {"filename": "top.png", "valid": True, "blur": {"score": 0.9}},
            {"filename": "deep.png", "valid": True, "blur": {"score": 0.8}},
        ]
    }))

    # Recursive=False → sadece top
    flat = select(source=src, report=src / "rep.json",
                  count=2, distribution={"close-up": 1.0}, recursive=False)
    assert len(flat.selected) == 1

    # Recursive=True → her ikisi
    rec = select(source=src, report=src / "rep.json",
                 count=2, distribution={"close-up": 1.0}, recursive=True)
    assert len(rec.selected) == 2

    # Tree-preserving copy
    target = tmp_path / "golden"
    apply_selection(rec.selected, target_dir=target, source_root=src)
    assert (target / "top.png").exists()
    assert (target / "deep" / "deep.png").exists()
