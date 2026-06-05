"""webui — Media Dataset Prep UI paketi.

tools/* alt klasörlerini sys.path'e ekleyen bootstrap burada — tool core
import'larından (validator_core, dedup_core, ...) ÖNCE çalışmalı. Bu paketin
herhangi bir alt modülü import edildiğinde __init__ önce çalışır, böylece
path hazır olur."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
for _tool_path in TOOLS_DIR.iterdir():
    if _tool_path.is_dir() and not _tool_path.name.startswith('.'):
        sys.path.insert(0, str(_tool_path))
