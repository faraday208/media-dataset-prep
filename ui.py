"""Media Dataset Prep — composition root / giriş noktası.

Tüm sayfalar webui/ paketine taşındı. Bu dosya yalnızca: tools/* bootstrap
tetikleyen `import webui`, public API/test uyumu için re-export'lar, NiceGUI
`@ui.page` router ve `main()` içerir. `uv run python ui.py` ile çalışır."""
from __future__ import annotations

import os

import webui  # noqa: F401 — tools/* sys.path bootstrap (core import'larından önce)
from nicegui import app, ui

# Public API / test uyumu: taşınan semboller re-export edilir (import ui; ui.X)
from webui.state import PipelineState, STATE, PIPELINE_STEPS  # noqa: F401
from webui.helpers import (  # noqa: F401
    _safe_call,
    _safe_set_value,
    _safe_set_text,
    _safe_set_visible,
    _safe_enable,
    _safe_disable,
    _safe_notify,
    _resolve_dataset_relative,
    _report_dir_for,
    _report_path,
    _append_manifest_from_report,
    _reject_dir_for,
    _find_manifest,
    _load_project_memory,
    step_status,
    scan_dataset_stats,
    humanize_bytes,
    _list_subdirs,
    _path_to_url,
    _aspect_label,
    _bpp_label,
    MEDIA_EXTENSIONS,
)
from webui.browse import _open_browse_dialog  # noqa: F401
from webui.header import build_header
from webui.pages.overview import build_overview_tab
from webui.pages.organize import build_organize_tab
from webui.pages.validate import build_validate_tab
from webui.pages.duplicate import build_duplicate_tab
from webui.pages.quality import build_quality_tab
from webui.pages.watermark import build_watermark_tab
from webui.pages.resize import build_resize_tab
from webui.pages.caption import build_caption_tab
from webui.pages.golden_set import build_golden_set_tab


def build_stub_tab(idx: int, name: str, desc: str):
    with ui.column().classes(
        "w-full max-w-screen-md mx-auto p-12 gap-3 items-center justify-center min-h-96"
    ):
        ui.icon("construction", size="3rem").classes("text-slate-300")
        ui.label(f"{idx:02d} — {name}").classes(
            "text-2xl font-semibold text-slate-500"
        )
        ui.label(desc).classes("text-base text-slate-500 text-center")
        ui.separator().classes("my-2 w-32")
        ui.label("Bu adımın meta UI wire-up'ı henüz yapılmadı.").classes(
            "text-sm text-slate-500"
        )
        ui.label("Tool kendi başına CLI ile çalıştırılabilir — README'ye bak.").classes(
            "text-xs text-slate-400"
        )


# ----------------------------- UI: Main page -------------------------------

@ui.page("/")
def main_page(tab: str = "overview"):
    """`?tab=00` veya `?tab=overview` ile direkt o tab'a açılır."""
    # Yeni page mount: eski sekmelerin callback'leri kalmasın (memory leak / yanlış render)
    STATE.reset_callbacks()
    build_header()

    # Tab sırası: Overview önce (default landing), sonra 00-07 sırayla
    with ui.tabs().classes("w-full").props("align=left") as tabs:
        overview_tab = ui.tab("Overview", icon="dashboard")
        step_tab_objs = []
        for idx, name, _desc, wired in PIPELINE_STEPS:
            label = f"{idx:02d} {name}"
            t = ui.tab(label)
            if not wired:
                t.classes("opacity-60")
            step_tab_objs.append(t)

    # Query string ile default tab seçimi
    initial = overview_tab
    requested = (tab or "overview").lower().strip()
    if requested != "overview":
        try:
            wanted_idx = int(requested)
            if 0 <= wanted_idx < len(step_tab_objs):
                initial = step_tab_objs[wanted_idx]
        except ValueError:
            pass

    # Wired tab dispatcher — yeni step wire ettikçe burayı genişlet
    WIRED_BUILDERS = {
        0: build_organize_tab,
        1: build_validate_tab,
        2: build_duplicate_tab,
        3: build_quality_tab,
        4: build_watermark_tab,
        5: build_resize_tab,
        6: build_caption_tab,
        7: build_golden_set_tab,
    }

    with ui.tab_panels(tabs, value=initial).classes("w-full"):
        with ui.tab_panel(overview_tab):
            build_overview_tab()
        for (idx, name, desc, wired), tab_obj in zip(PIPELINE_STEPS, step_tab_objs):
            with ui.tab_panel(tab_obj):
                if wired and idx in WIRED_BUILDERS:
                    WIRED_BUILDERS[idx]()
                else:
                    build_stub_tab(idx, name, desc)


def main():
    # Static file mount — UI'da kullanıcının dataset'inden image preview göstermek
    # için kök filesystem'i /fs prefix'i altında mount ediyoruz. Lokal kullanım,
    # network expose'a uygun değil (production'da proxy/auth düşünülmeli).
    app.add_static_files("/fs", "/")
    ui.run(
        title="Media Dataset Prep",
        port=int(os.environ.get("UI_PORT", "8200")),
        reload=False,
        show=False,
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
