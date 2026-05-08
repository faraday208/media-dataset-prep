"""
media-golden-set'in meta-orchestrator'a integrasyonu için testler.

Tool'un iç davranışını DOĞRULAMAZ — onun için tool'un kendi 35 testi var.
Burada: workspace katmanı + pipeline 07 adımı uçtan uca kontratı.
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_GOLDEN = REPO_ROOT / "tools" / "07-golden-set"


def test_golden_tool_present():
    assert TOOLS_GOLDEN.exists(), \
        f"{TOOLS_GOLDEN} yok — install-tools.sh çalıştırılmadı mı?"
    assert (TOOLS_GOLDEN / "run.py").is_file()
    assert (TOOLS_GOLDEN / "goldenset_core" / "selector.py").is_file()
    assert (TOOLS_GOLDEN / "goldenset_core" / "actions.py").is_file()
    assert (TOOLS_GOLDEN / "goldenset_core" / "reporter.py").is_file()


def test_golden_pyproject_declares_expected_name():
    pyproj = (TOOLS_GOLDEN / "pyproject.toml").read_text()
    assert 'name = "media-golden-set"' in pyproj
    import re
    m = re.search(r'version = "(\d+)\.(\d+)\.(\d+)"', pyproj)
    assert m
    assert int(m.group(1)) >= 1


def test_golden_importable_via_workspace():
    """goldenset_core paketi import edilebiliyor."""
    sys.path.insert(0, str(TOOLS_GOLDEN))
    try:
        from goldenset_core import (  # noqa: F401
            select,
            apply_selection,
            undo_from_report,
            write_report,
            parse_distribution,
            get_bucket,
            REPORT_TOOL,
        )
        assert REPORT_TOOL == "media-golden-set"
        assert callable(select)
        assert callable(apply_selection)
        assert callable(undo_from_report)
    finally:
        sys.path.pop(0)


def test_golden_parse_distribution():
    sys.path.insert(0, str(TOOLS_GOLDEN))
    try:
        from goldenset_core import parse_distribution
        d = parse_distribution("close-up:30,upper-body:30,full-body:40")
        assert sum(d.values()) == 1.0
    finally:
        sys.path.pop(0)


def test_golden_select_e2e_no_external_deps(tmp_path):
    """Workspace katmanı sağlıklı: select + apply + report stdlib-only çalışır."""
    sys.path.insert(0, str(TOOLS_GOLDEN))
    try:
        from goldenset_core import select, apply_selection, write_report

        # Sahte minimal dataset
        from PIL import Image
        Image.new("RGB", (8, 8), "red").save(tmp_path / "img1.png")
        Image.new("RGB", (8, 8), "blue").save(tmp_path / "img2.png")
        for fn in ("img1", "img2"):
            (tmp_path / f"{fn}.json").write_text(json.dumps({
                "camera": {"distance": "close-up"},
                "face": {"visible": "true"},
            }))
        (tmp_path / "rep.json").write_text(json.dumps({
            "results": [
                {"filename": "img1.png", "valid": True, "blur": {"score": 0.9}},
                {"filename": "img2.png", "valid": True, "blur": {"score": 0.8}},
            ]
        }))

        res = select(
            source=tmp_path,
            report=tmp_path / "rep.json",
            count=2,
            distribution={"close-up": 1.0},
        )
        assert len(res.selected) == 2

        target = tmp_path / "golden"
        ar = apply_selection(res.selected, target_dir=target)
        assert (target / "img1.png").exists()

        rp = write_report(
            report_path=target / "selection_report.json",
            source_root=tmp_path,
            config={"count": 2},
            selection=res,
            apply_result=ar,
        )
        payload = json.loads(rp.read_text())
        assert payload["tool"] == "media-golden-set"
        assert payload["summary"]["selected"] == 2
    finally:
        sys.path.pop(0)


def test_golden_run_parser_imports():
    """run.py argparse build edebiliyor — wrapper sağlıklı."""
    # Diğer tool'ların run.py'sı sys.modules'da kalmış olabilir; temizle
    sys.modules.pop("run", None)
    sys.path.insert(0, str(TOOLS_GOLDEN))
    try:
        from run import _build_parser
        args = _build_parser().parse_args([
            "-i", "/x", "-o", "/y", "--report", "/r.json",
            "--count", "10", "--distribution", "close-up:50,upper-body:50",
        ])
        assert args.input == "/x"
        assert args.output == "/y"
        assert args.count == 10
    finally:
        sys.path.pop(0)
        sys.modules.pop("run", None)
