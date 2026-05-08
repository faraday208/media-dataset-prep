"""
media-captioner'ın meta-orchestrator'a integrasyonu için testler.

Tool'un iç davranışını DOĞRULAMAZ — onun için tool'un kendi 14 testi var.
Burada: workspace katmanı + pipeline 06 adımı uçtan uca kontratı.

NOT: Gerçek Ollama inference test'leri server gerektirdiği için yok.
Sadece workspace import + pyproject + json_to_txt export e2e.
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_CAPTION = REPO_ROOT / "tools" / "06-caption"


def test_caption_tool_present():
    assert TOOLS_CAPTION.exists(), \
        f"{TOOLS_CAPTION} yok — install-tools.sh çalıştırılmadı mı?"
    assert (TOOLS_CAPTION / "run.py").is_file()
    assert (TOOLS_CAPTION / "caption_core" / "batch_client.py").is_file()
    assert (TOOLS_CAPTION / "caption_core" / "json_to_txt.py").is_file()
    assert (TOOLS_CAPTION / "caption_core" / "prompts").is_dir()


def test_caption_pyproject_declares_expected_name():
    pyproj = (TOOLS_CAPTION / "pyproject.toml").read_text()
    assert 'name = "media-captioner"' in pyproj
    import re
    m = re.search(r'version = "(\d+)\.(\d+)\.(\d+)"', pyproj)
    assert m
    assert int(m.group(1)) >= 1


def test_caption_importable_via_workspace():
    """caption_core paketi import edilebiliyor."""
    sys.path.insert(0, str(TOOLS_CAPTION))
    try:
        from caption_core import batch_client, json_to_txt  # noqa: F401
        from caption_core.batch_client import (
            PASS_CONFIG, SUPPORTED_EXTENSIONS, load_prompt,
        )
        assert set(PASS_CONFIG.keys()) == {1, 2, 3, 4, 5}
        assert ".jpg" in SUPPORTED_EXTENSIONS
        assert callable(load_prompt)
    finally:
        sys.path.pop(0)


def test_caption_all_5_pass_prompts_exist():
    """5 pass için prompt dosyaları var."""
    sys.path.insert(0, str(TOOLS_CAPTION))
    try:
        from caption_core.batch_client import PASS_CONFIG
        prompts_dir = TOOLS_CAPTION / "caption_core" / "prompts"
        for i in range(1, 6):
            fname = PASS_CONFIG[i]["file"]
            assert (prompts_dir / fname).is_file(), f"{fname} eksik"
    finally:
        sys.path.pop(0)


def test_caption_export_e2e_no_ollama(tmp_path):
    """json_to_txt ile JSON → TXT export, Ollama'sız çalışır."""
    sys.path.insert(0, str(TOOLS_CAPTION))
    try:
        from caption_core.json_to_txt import extract_captions
        # Sahte caption JSON yarat
        (tmp_path / "img1.json").write_text(json.dumps({
            "captioning": {
                "short": "Short caption.",
                "medium": "Medium caption description.",
                "long": "Long caption with detailed description.",
            }
        }))
        extract_captions(str(tmp_path), "medium")
        out = tmp_path / "img1.txt"
        assert out.exists()
        assert "Medium caption" in out.read_text()
    finally:
        sys.path.pop(0)


def test_caption_run_parser_imports():
    """run.py argparse build edebiliyor — wrapper sağlıklı."""
    sys.path.insert(0, str(TOOLS_CAPTION))
    try:
        from run import _build_parser
        args = _build_parser().parse_args(["-i", "/tmp/x"])
        assert args.input == "/tmp/x"
        assert args.model.startswith("qwen")
        assert args.workers >= 1
    finally:
        sys.path.pop(0)
