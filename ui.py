"""
Media Dataset Prep — Meta Orchestrator UI

NiceGUI tabanlı, AI dataset hazırlama pipeline'ı için human-in-the-loop arayüz.
Pipeline'ın 8 adımı (00 organize → 07 golden-set) sekmeler halinde sunulur;
her adım kendi tool'unu in-process import eder ve sonuçları görselleştirir.

Çalıştırmak için:
    uv run --group ui python ui.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from nicegui import app, ui

# Workspace tool'larını import edebilmek için tools/ alt klasörlerini path'e ekle
REPO_ROOT = Path(__file__).resolve().parent
TOOLS_DIR = REPO_ROOT / "tools"
for tool_path in TOOLS_DIR.iterdir():
    if tool_path.is_dir() and not tool_path.name.startswith('.'):
        sys.path.insert(0, str(tool_path))

import media_organizer  # noqa: E402

# Step 00 için kullanılan medya uzantıları
MEDIA_EXTENSIONS = media_organizer.MEDIA_EXTENSIONS


# ----------------------------- State ---------------------------------------

@dataclass
class PipelineState:
    """In-memory pipeline state — UI session boyunca yaşar (v0.1: persistence yok)."""
    dataset_path: str = ""
    last_report_paths: dict[int, str] = field(default_factory=dict)  # step_idx → report.json yolu

    def is_valid_dataset(self) -> bool:
        return bool(self.dataset_path) and Path(self.dataset_path).is_dir()


STATE = PipelineState()


# Pipeline adımları — UI'da sıralı listeleme + status indicator için merkez tanım
PIPELINE_STEPS: list[tuple[int, str, str]] = [
    (0, "Organize", "Dosya isimlerini düzenli numaralandır"),
    (1, "Validate", "Format ve dosya bütünlüğü kontrolü"),
    (2, "Duplicate", "Birebir + benzer kopya tespiti"),
    (3, "Quality", "Blur, brightness, contrast metrikleri"),
    (4, "Watermark", "YOLOv8 ile filigran tespit/temizleme"),
    (5, "Resize", "Lanczos ile boyutlandırma"),
    (6, "Caption", "Qwen3-VL multi-pass caption"),
    (7, "Golden Set", "Manuel cherry-pick"),
]


def step_status(idx: int) -> str:
    """Bir step için durum sembolü döndür: ✓ done / ○ pending / ⚠ error."""
    if idx in STATE.last_report_paths and Path(STATE.last_report_paths[idx]).exists():
        return "✓"
    return "○"


# ----------------------------- Helpers -------------------------------------

def scan_dataset_stats(path: str) -> dict:
    """Bir dataset dizinini tara — toplam dosya, tip dağılımı, total boyut."""
    if not path or not Path(path).is_dir():
        return {"total": 0, "by_ext": {}, "size_bytes": 0, "subdirs": 0}

    by_ext: Counter[str] = Counter()
    total_size = 0
    subdirs = 0
    total = 0

    for entry in Path(path).rglob('*'):
        if entry.is_file():
            ext = entry.suffix.lower()
            if ext in MEDIA_EXTENSIONS:
                by_ext[ext] += 1
                total += 1
                try:
                    total_size += entry.stat().st_size
                except OSError:
                    pass
        elif entry.is_dir() and entry != Path(path):
            subdirs += 1

    return {
        "total": total,
        "by_ext": dict(by_ext.most_common()),
        "size_bytes": total_size,
        "subdirs": subdirs,
    }


def humanize_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


# ----------------------------- UI: Header ----------------------------------

def build_header():
    with ui.header().classes("items-center justify-between bg-slate-800 text-white"):
        ui.label("Media Dataset Prep").classes("text-xl font-semibold")

        with ui.row().classes("items-center gap-2"):
            ui.label("Dataset:").classes("text-sm")
            path_input = ui.input(
                placeholder="/path/to/dataset",
                value=STATE.dataset_path,
                on_change=lambda e: setattr(STATE, "dataset_path", e.value),
            ).props("dense outlined dark").classes("w-96")

            def _validate():
                if STATE.is_valid_dataset():
                    ui.notify(f"Dataset OK: {STATE.dataset_path}", type="positive")
                else:
                    ui.notify("Dizin yok veya geçersiz", type="negative")

            ui.button("Validate", on_click=_validate).props("flat dense color=white")


# ----------------------------- UI: Overview --------------------------------

def build_overview_tab():
    with ui.column().classes("w-full p-6 gap-4"):
        ui.label("Pipeline Overview").classes("text-2xl font-semibold")

        stats_label = ui.label().classes("text-base font-mono whitespace-pre")
        ext_label = ui.label().classes("text-sm font-mono text-slate-600 whitespace-pre")

        steps_grid = ui.column().classes("gap-1 mt-4")

        def refresh():
            stats = scan_dataset_stats(STATE.dataset_path)
            if not STATE.is_valid_dataset():
                stats_label.set_text("⚠ Önce header'da geçerli bir dataset yolu seçin.")
                ext_label.set_text("")
            else:
                stats_label.set_text(
                    f"Yol      : {STATE.dataset_path}\n"
                    f"Toplam   : {stats['total']} medya dosyası\n"
                    f"Boyut    : {humanize_bytes(stats['size_bytes'])}\n"
                    f"Alt dizin: {stats['subdirs']}"
                )
                ext_lines = "\n".join(
                    f"  {ext:<8} {count:>6}" for ext, count in stats["by_ext"].items()
                )
                ext_label.set_text("Tip dağılımı:\n" + ext_lines if ext_lines else "")

            steps_grid.clear()
            with steps_grid:
                for idx, name, desc in PIPELINE_STEPS:
                    status = step_status(idx)
                    color = "text-green-600" if status == "✓" else "text-slate-400"
                    with ui.row().classes("items-center gap-3"):
                        ui.label(status).classes(f"text-xl {color} font-mono w-6")
                        ui.label(f"{idx:02d}").classes("text-slate-500 font-mono w-8")
                        ui.label(name).classes("font-medium w-32")
                        ui.label(desc).classes("text-sm text-slate-600")

        ui.button("Refresh", on_click=refresh).props("flat color=primary")
        refresh()


# ----------------------------- UI: 00 Organize -----------------------------

def build_organize_tab():
    with ui.column().classes("w-full p-6 gap-4"):
        ui.label("00 — Organize").classes("text-2xl font-semibold")
        ui.label(
            "Medya dosyalarını tip-bazlı sequence ile yeniden adlandır. "
            "Tüm CLI flag'leri burada — preview önce, sonra execute."
        ).classes("text-sm text-slate-600")

        with ui.row().classes("w-full gap-4"):
            # Sol: form
            with ui.column().classes("w-1/2 gap-2"):
                prefix_input = ui.input(
                    "Prefix",
                    placeholder="(boş bırakılırsa dataset klasör adı)",
                ).props("dense outlined")

                recursive_select = ui.select(
                    {"none": "Off (sadece üst seviye)",
                     "flat": "Flat (tüm tree → tek sequence)",
                     "tree": "Tree (her subdir kendi sequence'ı)"},
                    label="Recursive",
                    value="none",
                ).props("dense outlined")

                include_ext = ui.checkbox(
                    "Filename'de extension yer alsın (prefix_jpg_1.jpg)",
                    value=False,
                )

                mode_select = ui.select(
                    {"rename": "In-place rename",
                     "copy": "Copy to output-dir",
                     "move": "Move to output-dir"},
                    label="Mode",
                    value="rename",
                ).props("dense outlined")

                output_input = ui.input(
                    "Output dir (copy/move/recursive flat için)",
                    placeholder="/path/to/output",
                ).props("dense outlined")

                with ui.row().classes("gap-2"):
                    preview_btn = ui.button("Dry-Run Preview").props("color=primary")
                    execute_btn = ui.button("Execute").props("color=positive")

                ui.separator().classes("my-2")
                undo_input = ui.input(
                    "Undo: rename_report.json yolu",
                    placeholder="/path/to/.../rename_report.json",
                ).props("dense outlined")
                cleanup_check = ui.checkbox("Cleanup empty dirs", value=False)
                undo_btn = ui.button("Undo from report").props("color=warning")

            # Sağ: output paneli
            with ui.column().classes("w-1/2 gap-2"):
                summary_label = ui.label("(henüz çalışmadı)").classes(
                    "text-sm font-mono whitespace-pre"
                )
                preview_table = ui.table(
                    columns=[
                        {"name": "ext", "label": "Ext", "field": "ext"},
                        {"name": "old", "label": "Eski", "field": "old"},
                        {"name": "new", "label": "Yeni", "field": "new"},
                    ],
                    rows=[],
                    pagination=20,
                ).classes("w-full")

        # ------ Action handlers ------

        def _validate_inputs() -> Optional[str]:
            if not STATE.is_valid_dataset():
                return "Dataset yolu geçerli değil (header'da doğrula)"
            if mode_select.value in ("copy", "move") and not output_input.value:
                return f"{mode_select.value} modu --output-dir gerektirir"
            if recursive_select.value == "flat" and not output_input.value:
                return "--recursive flat → --output-dir zorunlu"
            return None

        def _build_plan():
            recursive_mode = (
                None if recursive_select.value == "none" else recursive_select.value
            )
            output_dir = output_input.value or None

            if recursive_mode == "tree":
                per_dir = media_organizer.scan_directory(
                    STATE.dataset_path, recursive_mode="tree"
                )
                prefix = prefix_input.value or None
                plan = media_organizer.generate_tree_rename_plan(
                    per_dir,
                    source_root=STATE.dataset_path,
                    prefix=prefix,
                    include_extension=include_ext.value,
                    output_dir=output_dir,
                )
            else:
                files = media_organizer.scan_directory(
                    STATE.dataset_path, recursive_mode=recursive_mode
                )
                prefix = prefix_input.value or os.path.basename(
                    os.path.abspath(STATE.dataset_path)
                )
                plan = media_organizer.generate_rename_plan(
                    files,
                    prefix=prefix,
                    include_extension=include_ext.value,
                    output_dir=output_dir,
                )
            return plan

        def _populate_preview(plan):
            preview_table.rows = [
                {"ext": p["extension"], "old": p["old_filename"], "new": p["new_filename"]}
                for p in plan
            ]
            preview_table.update()

        def on_preview():
            err = _validate_inputs()
            if err:
                ui.notify(err, type="negative")
                return
            try:
                plan = _build_plan()
                _populate_preview(plan)
                summary_label.set_text(f"Preview: {len(plan)} dosya planlandı (henüz uygulanmadı)")
                ui.notify(f"{len(plan)} dosya için plan oluşturuldu", type="info")
            except Exception as e:
                ui.notify(f"Hata: {e}", type="negative")

        def on_execute():
            err = _validate_inputs()
            if err:
                ui.notify(err, type="negative")
                return
            try:
                plan = _build_plan()
                _populate_preview(plan)
                mode = mode_select.value
                # Recursive flat in-place engeli zaten media_organizer'da var ama
                # burada da preempt: flat → mode'u rename'den uygun olana zorla
                if recursive_select.value == "flat" and mode == "rename":
                    ui.notify("Recursive flat in-place desteklenmiyor", type="negative")
                    return
                media_organizer.execute_rename(plan, dry_run=False, mode=mode)
                report_dir = output_input.value or STATE.dataset_path
                report_path = os.path.join(report_dir, "rename_report.json")
                media_organizer.save_report(plan, report_path, mode=mode)
                STATE.last_report_paths[0] = report_path
                summary_label.set_text(
                    f"✓ {len(plan)} dosya işlendi (mode={mode})\nRapor: {report_path}"
                )
                ui.notify(f"{len(plan)} dosya işlendi", type="positive")
            except Exception as e:
                ui.notify(f"Execute hatası: {e}", type="negative")

        def on_undo():
            report = undo_input.value or STATE.last_report_paths.get(0)
            if not report:
                ui.notify("Undo için rapor yolu girin (veya önce execute çalıştırın)",
                          type="negative")
                return
            if not Path(report).exists():
                ui.notify(f"Rapor yok: {report}", type="negative")
                return
            try:
                rc = media_organizer.undo_from_report(
                    report, dry_run=False, cleanup_empty_dirs=cleanup_check.value
                )
                if rc == 0:
                    summary_label.set_text(f"✓ Undo tamamlandı: {report}")
                    ui.notify("Undo başarılı", type="positive")
                else:
                    ui.notify(f"Undo kısmen tamamlandı (rc={rc})", type="warning")
            except Exception as e:
                ui.notify(f"Undo hatası: {e}", type="negative")

        preview_btn.on("click", on_preview)
        execute_btn.on("click", on_execute)
        undo_btn.on("click", on_undo)


# ----------------------------- UI: Stub tabs -------------------------------

def build_stub_tab(idx: int, name: str, desc: str):
    with ui.column().classes("w-full p-6 gap-4 items-center justify-center min-h-96"):
        ui.label(f"{idx:02d} — {name}").classes("text-2xl font-semibold text-slate-400")
        ui.label(desc).classes("text-base text-slate-500")
        ui.label("(coming soon — tool'un meta UI wire-up'ı henüz yapılmadı)").classes(
            "text-sm italic text-slate-400 mt-4"
        )
        ui.label("Tool kendi başına CLI ile çalıştırılabilir.").classes(
            "text-xs text-slate-400"
        )


# ----------------------------- UI: Main page -------------------------------

@ui.page("/")
def main_page():
    build_header()
    with ui.tabs().classes("w-full") as tabs:
        tab_objs = []
        for idx, name, _desc in PIPELINE_STEPS:
            label = f"{idx:02d} {name}"
            tab_objs.append(ui.tab(label))
        overview_tab = ui.tab("Overview")

    with ui.tab_panels(tabs, value=tab_objs[0]).classes("w-full"):
        for (idx, name, desc), tab_obj in zip(PIPELINE_STEPS, tab_objs):
            with ui.tab_panel(tab_obj):
                if idx == 0:
                    build_organize_tab()
                else:
                    build_stub_tab(idx, name, desc)
        with ui.tab_panel(overview_tab):
            build_overview_tab()


def main():
    ui.run(
        title="Media Dataset Prep",
        port=int(os.environ.get("UI_PORT", "8200")),
        reload=False,
        show=False,
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
