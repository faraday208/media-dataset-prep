"""
Media Dataset Prep — Meta Orchestrator UI

NiceGUI tabanlı, AI dataset hazırlama pipeline'ı için human-in-the-loop arayüz.
Pipeline'ın 8 adımı (00 organize → 07 golden-set) sekmeler halinde sunulur;
her adım kendi tool'unu in-process import eder ve sonuçları görselleştirir.

Çalıştırmak için:
    uv run --group ui python ui.py
"""
from __future__ import annotations

import asyncio
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
# media-validator (tools/01-validate) — alias'lı import (organizer ile collision'sız)
from src.validators.file_validator import FileValidator  # noqa: E402
from src.scanner import (  # noqa: E402
    collect_images as validate_collect_images,
    apply_action as validate_apply_action,
    undo_from_report as validate_undo_from_report,
    write_report as validate_write_report,
    DEFAULT_REPORT_NAME as VALIDATE_REPORT_NAME,
)
# media-deduplicator (tools/02-duplicate) — `core` paketi adı validator'ın `src` ile
# çakışmıyor (validator src/, deduplicator core/). Direkt import OK.
from core import (  # noqa: E402
    Hasher as DupHasher,
    apply_action as dedup_apply_action,
    find_exact_duplicates,
    find_similar_images,
    humanize_bytes as dedup_humanize_bytes,
    undo_from_report as dedup_undo_from_report,
    write_report as dedup_write_report,
    DEFAULT_REPORT_NAME as DEDUP_REPORT_NAME,
)

# Step 00 için kullanılan medya uzantıları
MEDIA_EXTENSIONS = media_organizer.MEDIA_EXTENSIONS


# ----------------------------- State ---------------------------------------

@dataclass
class PipelineState:
    """
    In-memory pipeline state — UI session boyunca yaşar (v0.1: persistence yok).

    Tab'lar `on_change` ile refresh callback kaydeder; Validate veya başka
    state-altering aksiyon `notify_change()` çağırır → kayıtlı tüm
    callback'ler tetiklenir (Observer pattern).
    """
    dataset_path: str = ""
    last_report_paths: dict[int, str] = field(default_factory=dict)
    _refresh_callbacks: list = field(default_factory=list)

    def is_valid_dataset(self) -> bool:
        return bool(self.dataset_path) and Path(self.dataset_path).is_dir()

    def on_change(self, callback) -> None:
        """Bir tab'ı state değişikliği bildirimine abone et."""
        self._refresh_callbacks.append(callback)

    def notify_change(self) -> None:
        """Tüm abone tab'ları yeniden render et."""
        for cb in list(self._refresh_callbacks):
            try:
                cb()
            except Exception as e:
                print(f"[STATE] refresh callback hatası: {e}")

    def reset_callbacks(self) -> None:
        """Yeni page mount edildiğinde eski callback'leri temizle."""
        self._refresh_callbacks = []


STATE = PipelineState()


# Pipeline adımları — (idx, name, desc, wired)
# wired=True: meta UI'da tab tam fonksiyonel
# wired=False: stub tab + "soon" badge (tool kendi başına CLI ile kullanılabilir)
PIPELINE_STEPS: list[tuple[int, str, str, bool]] = [
    (0, "Organize", "Dosya isimlerini düzenli numaralandır", True),
    (1, "Validate", "Format ve dosya bütünlüğü kontrolü", True),
    (2, "Duplicate", "Birebir + benzer kopya tespiti", True),
    (3, "Quality", "Blur, brightness, contrast metrikleri", False),
    (4, "Watermark", "YOLOv8 ile filigran tespit/temizleme", False),
    (5, "Resize", "Lanczos ile boyutlandırma", False),
    (6, "Caption", "Qwen3-VL multi-pass caption", False),
    (7, "Golden Set", "Manuel cherry-pick", False),
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

def _list_subdirs(path: str) -> list[str]:
    """Bir dizinin alt klasörlerini sıralı döndür. Hidden ve hata olanları atla."""
    try:
        entries = []
        for entry in sorted(os.listdir(path)):
            if entry.startswith('.'):
                continue
            full = os.path.join(path, entry)
            if os.path.isdir(full):
                entries.append(entry)
        return entries
    except (PermissionError, FileNotFoundError, NotADirectoryError):
        return []


def _open_browse_dialog(target_input, *, title="Dizin seç", on_select=None):
    """
    Sunucu tarafı dizin tarayıcı dialog'u — kullanıcı tıklayarak gezer,
    "Bu dizini seç" ile target_input'a yazar.

    on_select: opsiyonel callback (path: str) -> None
        Seçim sonrası ek aksiyon (örn. STATE.dataset_path güncelleme).
        Verilmezse sadece input'a yazılır.
    """
    # Başlangıç noktası: mevcut input değeri varsa o, yoksa $HOME, o da yoksa /
    start = target_input.value or os.environ.get("HOME") or "/"
    if not os.path.isdir(start):
        start = os.environ.get("HOME") or "/"

    current = {"path": os.path.abspath(start)}

    with ui.dialog() as dialog, ui.card().classes("w-[800px]"):
        ui.label(title).classes("text-lg font-semibold")

        path_label = ui.label().classes("text-sm font-mono text-slate-700 break-all")
        subdirs_list = ui.column().classes("w-full gap-1 max-h-96 overflow-auto")

        def render():
            path_label.set_text("📁 " + current["path"])
            subdirs_list.clear()
            with subdirs_list:
                # Üst dizine git
                if current["path"] != "/":
                    parent = os.path.dirname(current["path"])
                    with ui.row().classes(
                        "items-center gap-2 cursor-pointer hover:bg-slate-100 p-2 rounded"
                    ).on("click", lambda: navigate(parent)):
                        ui.icon("arrow_upward").classes("text-slate-500")
                        ui.label("..  (üst dizin)").classes("text-sm")

                # Alt dizinler
                for name in _list_subdirs(current["path"]):
                    sub_path = os.path.join(current["path"], name)
                    with ui.row().classes(
                        "items-center gap-2 cursor-pointer hover:bg-slate-100 p-2 rounded"
                    ).on("click", lambda p=sub_path: navigate(p)):
                        ui.icon("folder").classes("text-amber-600")
                        ui.label(name).classes("text-sm")

                if not _list_subdirs(current["path"]):
                    ui.label("(alt klasör yok)").classes(
                        "text-xs italic text-slate-400 p-2"
                    )

        def navigate(new_path):
            current["path"] = new_path
            render()

        def select_current():
            chosen = current["path"]
            target_input.set_value(chosen)
            if on_select:
                on_select(chosen)
            dialog.close()
            ui.notify(f"Seçildi: {chosen}", type="positive")

        with ui.row().classes("w-full justify-between mt-4"):
            ui.button("Cancel", on_click=dialog.close).props(
                "flat color=grey no-caps"
            )
            ui.button("Bu dizini seç", on_click=select_current).props(
                "color=primary no-caps"
            )

        render()

    dialog.open()


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

            def _on_dataset_pick(chosen: str):
                STATE.dataset_path = chosen
                STATE.notify_change()  # Overview otomatik tazelenir

            ui.button(
                icon="folder_open",
                on_click=lambda: _open_browse_dialog(
                    path_input,
                    title="Dataset dizini seç",
                    on_select=_on_dataset_pick,
                ),
            ).props("flat dense color=white").tooltip("Browse — dataset dizini seç")

            def _validate():
                if STATE.is_valid_dataset():
                    ui.notify(f"Dataset OK: {STATE.dataset_path}", type="positive")
                    STATE.notify_change()  # Overview ve diğer abone tab'ları tazele
                else:
                    ui.notify("Dizin yok veya geçersiz", type="negative")

            ui.button("Validate", on_click=_validate).props(
                "flat dense color=white no-caps"
            )


# ----------------------------- UI: Overview --------------------------------

def build_overview_tab():
    with ui.column().classes("w-full max-w-screen-xl mx-auto p-6 gap-4"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("Pipeline Overview").classes("text-2xl font-semibold")
            refresh_btn = ui.button("Refresh").props("flat color=primary no-caps")

        # Stats kartları — solda dataset özeti, sağda ext breakdown
        with ui.grid(columns="2fr 1fr").classes("w-full gap-4"):
            with ui.card().classes("w-full"):
                ui.label("Dataset").classes("text-sm uppercase text-slate-500 tracking-wide")
                stats_label = ui.label().classes("text-base font-mono whitespace-pre")

            with ui.card().classes("w-full"):
                ui.label("Tip dağılımı").classes("text-sm uppercase text-slate-500 tracking-wide")
                ext_label = ui.label().classes("text-sm font-mono text-slate-700 whitespace-pre")

        # Step listesi — kart içinde
        with ui.card().classes("w-full"):
            ui.label("Pipeline durumu").classes("text-sm uppercase text-slate-500 tracking-wide")
            steps_grid = ui.column().classes("gap-2 mt-2")

        def refresh():
            stats = scan_dataset_stats(STATE.dataset_path)
            if not STATE.is_valid_dataset():
                stats_label.set_text("⚠ Önce header'da geçerli bir\ndataset yolu seçin.")
                ext_label.set_text("(yol seçilmedi)")
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
                ext_label.set_text(ext_lines if ext_lines else "(medya dosyası yok)")

            steps_grid.clear()
            with steps_grid:
                for idx, name, desc, wired in PIPELINE_STEPS:
                    status = step_status(idx)
                    color = "text-green-600" if status == "✓" else "text-slate-400"
                    row_opacity = "" if wired else "opacity-60"
                    with ui.row().classes(f"items-center gap-3 {row_opacity}"):
                        ui.label(status).classes(f"text-xl {color} font-mono w-6")
                        ui.label(f"{idx:02d}").classes("text-slate-500 font-mono w-8")
                        ui.label(name).classes("font-medium w-32")
                        ui.label(desc).classes("text-sm text-slate-600 flex-grow")
                        if not wired:
                            ui.badge("soon").props("color=grey-5")

        refresh_btn.on("click", refresh)
        STATE.on_change(refresh)  # Validate / Browse seçimi sonrası otomatik tazele
        refresh()


# ----------------------------- UI: 00 Organize -----------------------------

def build_organize_tab():
    with ui.column().classes("w-full max-w-screen-xl mx-auto p-6 gap-4"):
        ui.label("00 — Organize").classes("text-2xl font-semibold")
        ui.label(
            "Medya dosyalarını tip-bazlı sequence ile yeniden adlandır. "
            "Tüm CLI flag'leri burada — preview önce, sonra execute."
        ).classes("text-sm text-slate-600")

        with ui.grid(columns="1fr 1fr").classes("w-full gap-6 mt-2"):
            # Sol kolon: form (kart içinde)
            with ui.card().classes("w-full"):
                ui.label("Configuration").classes(
                    "text-sm uppercase text-slate-500 tracking-wide"
                )
                prefix_input = ui.input(
                    "Prefix",
                    placeholder="(boş = dataset klasör adı)",
                ).props("dense outlined").classes("w-full")

                recursive_select = ui.select(
                    {"none": "Off — sadece üst seviye",
                     "flat": "Flat — tüm tree, tek sequence",
                     "tree": "Tree — her subdir kendi sequence'ı"},
                    label="Recursive",
                    value="none",
                ).props("dense outlined").classes("w-full")

                include_ext = ui.checkbox(
                    "Filename'de extension yer alsın (prefix_jpg_1.jpg)",
                    value=False,
                )

                # Mode seçenekleri — Recursive=Flat seçilince In-place gizlenir
                # (cross-folder relocation kaynak ağacında destructive olur).
                MODE_OPTIONS_ALL = {
                    "rename": "In-place rename",
                    "copy": "Copy to output-dir",
                    "move": "Move to output-dir",
                }
                MODE_OPTIONS_NO_INPLACE = {
                    k: v for k, v in MODE_OPTIONS_ALL.items() if k != "rename"
                }

                mode_select = ui.select(
                    MODE_OPTIONS_ALL,
                    label="Mode",
                    value="rename",
                ).props("dense outlined").classes("w-full")

                def _sync_mode_options(recursive_value: str):
                    if recursive_value == "flat":
                        mode_select.options = MODE_OPTIONS_NO_INPLACE
                        if mode_select.value == "rename":
                            mode_select.value = "copy"
                            ui.notify(
                                "Flat mod in-place'i desteklemiyor — Copy'ye geçildi",
                                type="info",
                            )
                    else:
                        mode_select.options = MODE_OPTIONS_ALL
                    mode_select.update()

                recursive_select.on_value_change(
                    lambda e: _sync_mode_options(e.value)
                )

                with ui.row().classes("w-full items-center gap-1 no-wrap"):
                    output_input = ui.input(
                        "Output dir",
                        placeholder="copy/move/recursive flat için zorunlu",
                    ).props("dense outlined").classes("flex-grow")
                    ui.button(
                        icon="folder_open",
                        on_click=lambda: _open_browse_dialog(
                            output_input, title="Output dizini seç"
                        ),
                    ).props("flat dense color=grey-7").tooltip(
                        "Browse — output dizini seç"
                    )

                with ui.row().classes("gap-2 mt-2 w-full"):
                    preview_btn = ui.button("Dry-Run Preview").props(
                        "color=primary no-caps"
                    )
                    execute_btn = ui.button("Execute").props("color=positive no-caps")

                ui.separator().classes("my-3")
                ui.label("Undo").classes(
                    "text-sm uppercase text-slate-500 tracking-wide"
                )
                undo_input = ui.input(
                    "rename_report.json yolu",
                    placeholder="(execute sonrası otomatik dolar)",
                ).props("dense outlined").classes("w-full")
                cleanup_check = ui.checkbox("Cleanup empty dirs", value=False)
                with ui.row().classes("gap-2"):
                    undo_preview_btn = ui.button("Preview Undo").props(
                        "outline color=primary no-caps"
                    )
                    undo_btn = ui.button("Undo from report").props(
                        "outline color=grey-7 no-caps"
                    )

            # Sağ kolon: özet + preview tablosu
            with ui.card().classes("w-full"):
                with ui.row().classes("items-center justify-between w-full"):
                    ui.label("Preview").classes(
                        "text-sm uppercase text-slate-500 tracking-wide"
                    )
                summary_label = ui.label(
                    "Henüz preview üretilmedi — sol panelde Dry-Run Preview tıkla."
                ).classes("text-sm text-slate-600 italic mt-1")
                preview_table = ui.table(
                    columns=[
                        {"name": "ext", "label": "Ext", "field": "ext", "align": "left"},
                        {"name": "old", "label": "Eski isim", "field": "old", "align": "left"},
                        {"name": "new", "label": "Yeni isim", "field": "new", "align": "left"},
                        {"name": "src", "label": "Sort kaynağı", "field": "src", "align": "left"},
                        {"name": "subdir", "label": "Subdir", "field": "subdir", "align": "left"},
                    ],
                    rows=[],
                    pagination=15,
                ).classes("w-full mt-2")

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
                {
                    "ext": p["extension"],
                    "old": p["old_filename"],
                    "new": p["new_filename"],
                    "src": p.get("time_source", "—"),
                    "subdir": p.get("subdir", "—"),
                }
                for p in plan
            ]
            preview_table.update()

        def _summarize_plan(plan, *, executed: bool, mode: str = "") -> str:
            """Plan üzerine özet — dosya sayısı + sort-time kaynak dağılımı."""
            src_counts = Counter(p.get("time_source", "?") for p in plan)
            src_breakdown = ", ".join(
                f"{c} via {s}" for s, c in sorted(src_counts.items())
            )
            verb = f"✓ {len(plan)} dosya işlendi (mode={mode})" if executed else \
                   f"Preview: {len(plan)} dosya planlandı (henüz uygulanmadı)"
            return f"{verb}\nSort-time: {src_breakdown}"

        def on_preview():
            err = _validate_inputs()
            if err:
                ui.notify(err, type="negative")
                return
            try:
                plan = _build_plan()
                _populate_preview(plan)
                summary_label.set_text(_summarize_plan(plan, executed=False))
                ui.notify(f"{len(plan)} dosya için plan oluşturuldu", type="info")
            except Exception as e:
                ui.notify(f"Hata: {e}", type="negative")

        def _do_execute(plan):
            """Asıl execute mantığı — conflict onayı sonrası burada toplanır."""
            mode = mode_select.value
            try:
                media_organizer.execute_rename(plan, dry_run=False, mode=mode)
                report_dir = output_input.value or STATE.dataset_path
                report_path = os.path.join(report_dir, "rename_report.json")
                media_organizer.save_report(plan, report_path, mode=mode)
                STATE.last_report_paths[0] = report_path
                undo_input.set_value(report_path)
                summary_label.set_text(
                    _summarize_plan(plan, executed=True, mode=mode)
                    + f"\nRapor: {report_path}"
                )
                ui.notify(f"{len(plan)} dosya işlendi", type="positive")
                STATE.notify_change()  # Overview'da step 00 ✓ olur
            except Exception as e:
                ui.notify(f"Execute hatası: {e}", type="negative")

        def _show_conflict_dialog(conflicts, on_confirm):
            """Çakışma listesini modal ile göster, kullanıcı onaylarsa devam et."""
            with ui.dialog() as dlg, ui.card().classes("w-[700px]"):
                ui.label("⚠ Naming Conflicts").classes("text-lg font-semibold")
                ui.label(
                    f"{len(conflicts)} dosyada çakışma var. Devam edersen bunlar "
                    "üzerine yazılabilir veya plan başarısız olabilir."
                ).classes("text-sm text-slate-700")

                # Çakışmaları listele (ilk 20, gerisi say)
                with ui.column().classes(
                    "w-full gap-1 max-h-72 overflow-auto bg-slate-50 p-2 rounded"
                ):
                    for c in conflicts[:20]:
                        ui.label(f"• {c['new_path']}  ({c['reason']})").classes(
                            "text-xs font-mono text-slate-700"
                        )
                    if len(conflicts) > 20:
                        ui.label(f"… +{len(conflicts) - 20} daha").classes(
                            "text-xs italic text-slate-500"
                        )

                with ui.row().classes("w-full justify-end gap-2 mt-3"):
                    ui.button("Cancel", on_click=dlg.close).props(
                        "flat color=grey no-caps"
                    )

                    def _confirm():
                        dlg.close()
                        on_confirm()

                    ui.button("Yine de devam et", on_click=_confirm).props(
                        "color=warning no-caps"
                    )
            dlg.open()

        def on_execute():
            err = _validate_inputs()
            if err:
                ui.notify(err, type="negative")
                return

            # UI seviyesi preempt — library zaten engeller ama erken hata daha hoş
            if recursive_select.value == "flat" and mode_select.value == "rename":
                ui.notify("Recursive flat in-place desteklenmiyor", type="negative")
                return

            try:
                plan = _build_plan()
                _populate_preview(plan)

                # Same-dir notice — output_dir kaynakla aynıysa library in-place'e düşürür
                output_dir = output_input.value
                if output_dir and os.path.abspath(output_dir) == os.path.abspath(
                    STATE.dataset_path
                ):
                    ui.notify(
                        "Output dir kaynakla aynı — in-place rename'e düşülüyor",
                        type="info",
                    )

                # Conflict check — varsa modal, yoksa direkt execute
                conflicts = media_organizer.check_conflicts(plan)
                if conflicts:
                    _show_conflict_dialog(conflicts, lambda: _do_execute(plan))
                else:
                    _do_execute(plan)
            except Exception as e:
                ui.notify(f"Plan hatası: {e}", type="negative")

        def _run_undo(dry_run: bool):
            report = undo_input.value or STATE.last_report_paths.get(0)
            if not report:
                ui.notify(
                    "Undo için rapor yolu girin (veya önce execute çalıştırın)",
                    type="negative",
                )
                return
            if not Path(report).exists():
                ui.notify(f"Rapor yok: {report}", type="negative")
                return
            try:
                rc = media_organizer.undo_from_report(
                    report, dry_run=dry_run, cleanup_empty_dirs=cleanup_check.value
                )
                label = "Undo preview" if dry_run else "Undo"
                if rc == 0:
                    if dry_run:
                        summary_label.set_text(
                            f"{label} başarılı: değişiklik yapılmadı, planı terminal'de gör.\n"
                            f"Rapor: {report}"
                        )
                        ui.notify(
                            "Preview tamam — diskte değişiklik yok", type="info"
                        )
                    else:
                        summary_label.set_text(f"✓ Undo tamamlandı: {report}")
                        ui.notify("Undo başarılı", type="positive")
                        STATE.notify_change()
                else:
                    ui.notify(
                        f"{label} kısmen tamamlandı (rc={rc})", type="warning"
                    )
            except Exception as e:
                ui.notify(f"{'Undo preview' if dry_run else 'Undo'} hatası: {e}",
                          type="negative")

        def on_undo():
            _run_undo(dry_run=False)

        def on_undo_preview():
            _run_undo(dry_run=True)

        preview_btn.on("click", on_preview)
        execute_btn.on("click", on_execute)
        undo_preview_btn.on("click", on_undo_preview)
        undo_btn.on("click", on_undo)


# ----------------------------- UI: Stub tabs -------------------------------

def build_validate_tab():
    """01 — Validate: format / boyut / aspect / bütünlük + opsiyonel move/delete + undo."""
    with ui.column().classes("w-full max-w-screen-xl mx-auto p-6 gap-4"):
        ui.label("01 — Validate").classes("text-2xl font-semibold")
        ui.label(
            "Hatalı görselleri tespit et: format / boyut / aspect / bütünlük. "
            "Sadece raporla, /rejected'a taşı veya sil — undo destekli."
        ).classes("text-sm text-slate-600")

        with ui.grid(columns="1fr 1fr").classes("w-full gap-6 mt-2"):
            # ----- Sol kolon: form -----
            with ui.card().classes("w-full"):
                ui.label("Configuration").classes(
                    "text-sm uppercase text-slate-500 tracking-wide"
                )

                recursive_check = ui.checkbox("Recursive — alt klasörleri de tara", value=True)

                action_select = ui.select(
                    {
                        "none": "Sadece raporla (default)",
                        "move": "/rejected'a taşı (undoable)",
                        "delete": "Sil (irreversible)",
                    },
                    label="Hatalı dosyalar için aksiyon",
                    value="none",
                ).props("dense outlined").classes("w-full")

                with ui.row().classes("w-full items-center gap-1 no-wrap"):
                    invalid_dir_input = ui.input(
                        "Invalid dir",
                        placeholder="move için zorunlu (örn. ./rejected)",
                    ).props("dense outlined").classes("flex-grow")
                    ui.button(
                        icon="folder_open",
                        on_click=lambda: _open_browse_dialog(
                            invalid_dir_input, title="Invalid (rejected) dizini seç"
                        ),
                    ).props("flat dense color=grey-7").tooltip(
                        "Browse — invalid dir seç"
                    )

                with ui.row().classes("gap-3 mt-1"):
                    dryrun_check = ui.checkbox("Dry-run", value=True)
                    yes_check = ui.checkbox("Onaysız (delete için)", value=False)

                with ui.expansion("Threshold ayarları (advanced)", icon="tune").classes(
                    "w-full mt-2"
                ):
                    with ui.column().classes("w-full gap-2 p-2"):
                        with ui.grid(columns="1fr 1fr").classes("w-full gap-3"):
                            min_short_edge = ui.number(
                                "Min short edge (px)", value=512, min=1, step=1,
                            ).props("dense outlined")
                            max_short_edge = ui.number(
                                "Max short edge (px)", value=8192, min=1, step=1,
                            ).props("dense outlined")
                            min_aspect = ui.number(
                                "Min aspect (w/h)", value=0.5, step=0.1, format="%.2f",
                            ).props("dense outlined")
                            max_aspect = ui.number(
                                "Max aspect (w/h)", value=2.0, step=0.1, format="%.2f",
                            ).props("dense outlined")
                            min_size_kb = ui.number(
                                "Min file size (KB)", value=100, min=0, step=1,
                            ).props("dense outlined")
                            max_size_mb = ui.number(
                                "Max file size (MB)", value=50, min=1, step=1,
                            ).props("dense outlined")
                        allowed_formats_input = ui.input(
                            "Allowed formats (virgülle)",
                            value="jpg,jpeg,png,webp",
                        ).props("dense outlined").classes("w-full")

                with ui.row().classes("gap-2 mt-3 w-full items-center"):
                    run_btn = ui.button("Run validation").props(
                        "color=primary no-caps"
                    )
                    progress_label = ui.label("").classes(
                        "text-xs text-slate-600"
                    )
                progress_bar = ui.linear_progress(
                    value=0, show_value=False
                ).classes("w-full")
                progress_bar.visible = False

                ui.separator().classes("my-3")
                ui.label("Undo").classes(
                    "text-sm uppercase text-slate-500 tracking-wide"
                )
                undo_input = ui.input(
                    "validate_report.json yolu",
                    placeholder="(move action sonrası otomatik dolar)",
                ).props("dense outlined").classes("w-full")
                with ui.row().classes("gap-2"):
                    undo_preview_btn = ui.button("Preview Undo").props(
                        "outline color=primary no-caps"
                    )
                    undo_btn = ui.button("Undo").props(
                        "outline color=grey-7 no-caps"
                    )

            # ----- Sağ kolon: results -----
            with ui.card().classes("w-full"):
                ui.label("Sonuç").classes(
                    "text-sm uppercase text-slate-500 tracking-wide"
                )
                summary_label = ui.label(
                    "Henüz validate çalıştırılmadı — sol panelde Run validation tıkla."
                ).classes("text-sm text-slate-600 italic mt-1")

                with ui.row().classes("w-full justify-around mt-2"):
                    with ui.column().classes("items-center gap-0"):
                        total_card = ui.label("—").classes(
                            "text-3xl font-bold text-slate-700"
                        )
                        ui.label("Total").classes(
                            "text-xs uppercase text-slate-500 tracking-wide"
                        )
                    with ui.column().classes("items-center gap-0"):
                        valid_card = ui.label("—").classes(
                            "text-3xl font-bold text-green-600"
                        )
                        ui.label("Valid").classes(
                            "text-xs uppercase text-slate-500 tracking-wide"
                        )
                    with ui.column().classes("items-center gap-0"):
                        invalid_card = ui.label("—").classes(
                            "text-3xl font-bold text-red-600"
                        )
                        ui.label("Invalid").classes(
                            "text-xs uppercase text-slate-500 tracking-wide"
                        )

                ui.separator().classes("my-2")
                ui.label("Reason kırılımı").classes(
                    "text-xs uppercase text-slate-500 tracking-wide"
                )
                reasons_panel = ui.column().classes("w-full gap-1 mt-1")

                ui.separator().classes("my-2")
                invalid_table = ui.table(
                    columns=[
                        {"name": "filename", "label": "Dosya", "field": "filename", "align": "left", "sortable": True},
                        {"name": "subdir", "label": "Subdir", "field": "subdir", "align": "left", "sortable": True},
                        {"name": "reason", "label": "Sebep", "field": "reason", "align": "left", "sortable": True},
                        {"name": "dim", "label": "Boyut (WxH)", "field": "dim", "align": "left"},
                        {"name": "size_kb", "label": "Size (KB)", "field": "size_kb", "align": "right", "sortable": True},
                    ],
                    rows=[],
                    pagination=10,
                ).classes("w-full mt-1")

        # ------ Action handlers ------

        def _build_config() -> dict:
            return {
                "file_validation": {
                    "allowed_formats": [
                        f.strip().lower()
                        for f in (allowed_formats_input.value or "").split(",")
                        if f.strip()
                    ] or ["jpg", "jpeg", "png", "webp"],
                    "min_file_size_kb": float(min_size_kb.value or 0),
                    "max_file_size_mb": float(max_size_mb.value or 50),
                },
                "dimensions": {
                    "min_short_edge": int(min_short_edge.value or 0),
                    "max_short_edge": int(max_short_edge.value or 8192),
                    "aspect_ratio": {
                        "min": float(min_aspect.value or 0),
                        "max": float(max_aspect.value or 999),
                    },
                },
            }

        def _validate_inputs() -> Optional[str]:
            if not STATE.is_valid_dataset():
                return "Dataset yolu geçerli değil (header'da doğrula)"
            if action_select.value == "move" and not invalid_dir_input.value:
                return "Move aksiyonu için Invalid dir gerekli"
            return None

        def _extract_subdir(abs_path: str) -> str:
            """results[i].path → dataset'e göre relative subdir (recursive scan'de
            aynı isimli dosyaları ayırt etmek için)."""
            if not abs_path or not STATE.dataset_path:
                return "—"
            try:
                rel = Path(abs_path).relative_to(Path(STATE.dataset_path).resolve())
                parent = str(rel.parent)
                return "—" if parent == "." else parent
            except (ValueError, OSError):
                return "—"

        def _on_action_change(value: str):
            """Move seçilince invalid_dir input'u <dataset>/rejected ile auto-doldur
            (kullanıcı boş bıraktıysa)."""
            if value == "move" and not invalid_dir_input.value and STATE.dataset_path:
                invalid_dir_input.value = str(Path(STATE.dataset_path) / "rejected")
                invalid_dir_input.update()

        action_select.on_value_change(lambda e: _on_action_change(e.value))

        def _populate_results(results: list[dict], summary: dict, action_msg: str = ""):
            total_card.set_text(str(summary["total"]))
            valid_card.set_text(str(summary["valid"]))
            invalid_card.set_text(str(summary["invalid"]))

            # Reason kırılımı
            reasons_panel.clear()
            with reasons_panel:
                if not summary["reasons"]:
                    ui.label("(reason yok — hepsi valid)").classes(
                        "text-xs text-slate-500 italic"
                    )
                else:
                    total_inv = max(summary["invalid"], 1)
                    for reason, count in sorted(
                        summary["reasons"].items(), key=lambda x: -x[1]
                    ):
                        pct = count / total_inv * 100
                        with ui.row().classes("w-full items-center gap-2"):
                            ui.label(reason).classes(
                                "text-xs font-mono text-slate-700 w-44 truncate"
                            )
                            ui.linear_progress(value=pct / 100, show_value=False).classes(
                                "flex-grow"
                            )
                            ui.label(f"{count} ({pct:.0f}%)").classes(
                                "text-xs text-slate-600 w-16 text-right"
                            )

            # Invalid table
            invalid_table.rows = [
                {
                    "filename": r.get("filename", ""),
                    "subdir": _extract_subdir(r.get("path", "")),
                    "reason": r.get("reason", ""),
                    "dim": f"{r.get('width', 0)}×{r.get('height', 0)}"
                           if r.get("width") else "—",
                    "size_kb": f"{r.get('file_size_kb', 0):.1f}",
                }
                for r in results if not r.get("valid")
            ]
            invalid_table.update()

            verb = "Validate tamam"
            summary_label.set_text(
                f"{verb}: {summary['valid']}/{summary['total']} valid"
                + (f"\n{action_msg}" if action_msg else "")
            )

        def _maybe_warn_full_rejection(summary: dict):
            """%100 invalid çıkarsa kullanıcıyı uyar — threshold'lar muhtemelen
            çok sıkı. (CLI'de tqdm sonrası reason listesi zaten gösterir;
            UI'da explicit warning daha keşfedilebilir.)"""
            if summary["total"] > 0 and summary["invalid"] == summary["total"]:
                ui.notify(
                    "⚠ %100 reddedildi — threshold'larınız çok sıkı olabilir. "
                    "Threshold ayarlarını gevşetmeyi deneyin.",
                    type="warning",
                    timeout=8000,
                )

        async def on_run():
            err = _validate_inputs()
            if err:
                ui.notify(err, type="negative")
                return

            run_btn.disable()
            progress_bar.visible = True
            progress_bar.set_value(0)
            try:
                config = _build_config()
                validator = FileValidator(config)
                exts = {f".{f}" for f in config["file_validation"]["allowed_formats"]}
                exts |= {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}

                progress_label.set_text("Tarama…")
                await asyncio.sleep(0)
                images = validate_collect_images(
                    STATE.dataset_path,
                    recursive=recursive_check.value,
                    allowed_exts=exts,
                )
                if not images:
                    ui.notify("Hiç dosya bulunamadı", type="warning")
                    return

                # Validate — chunk'lar halinde, her N dosyada bir UI'ı yenile
                total = len(images)
                results: list[dict] = []
                valid = invalid = 0
                reasons: dict[str, int] = {}
                update_every = max(1, total // 100)
                progress_label.set_text(f"0 / {total}")

                for i, img in enumerate(images):
                    r = validator.validate(img)
                    results.append(r.to_dict())
                    if r.valid:
                        valid += 1
                    else:
                        invalid += 1
                        reasons[r.reason] = reasons.get(r.reason, 0) + 1
                    if (i + 1) % update_every == 0 or (i + 1) == total:
                        progress_bar.set_value((i + 1) / total)
                        progress_label.set_text(f"{i + 1} / {total}")
                        await asyncio.sleep(0)

                summary = {
                    "total": total,
                    "valid": valid,
                    "invalid": invalid,
                    "reasons": reasons,
                }

                action = action_select.value
                if action != "none":
                    if action == "delete" and not dryrun_check.value and not yes_check.value:
                        _confirm_delete_dialog(
                            invalid,
                            on_confirm=lambda: _execute_action(
                                action, results, summary, exts
                            ),
                        )
                        _maybe_warn_full_rejection(summary)
                        return
                    _execute_action(action, results, summary, exts)
                    _maybe_warn_full_rejection(summary)
                    return

                # action="none": sadece rapor
                report_path = Path(STATE.dataset_path) / VALIDATE_REPORT_NAME
                _write_report_helper(
                    report_path,
                    summary=summary,
                    results=results,
                    action_result=validate_apply_action(
                        results, source_root=STATE.dataset_path, action="none"
                    ),
                    config=config,
                    exts=exts,
                )
                undo_input.set_value(str(report_path))
                STATE.last_report_paths[1] = str(report_path)
                _populate_results(
                    results, summary,
                    action_msg=f"Rapor: {report_path}",
                )
                ui.notify(
                    f"{invalid}/{total} hatalı (sadece raporlandı)",
                    type="info",
                )
                _maybe_warn_full_rejection(summary)
                STATE.notify_change()

            except Exception as e:
                ui.notify(f"Validate hatası: {e}", type="negative")
            finally:
                progress_bar.visible = False
                progress_label.set_text("")
                run_btn.enable()

        def _confirm_delete_dialog(invalid_count: int, *, on_confirm):
            with ui.dialog() as dlg, ui.card().classes("w-[500px]"):
                ui.label("⚠ Kalıcı silme onayı").classes("text-lg font-semibold")
                ui.label(
                    f"{invalid_count} hatalı dosya KALICI olarak silinecek. "
                    "Bu işlem geri alınamaz. Önce 'Move' ile dene veya Dry-run aç."
                ).classes("text-sm text-slate-700")
                with ui.row().classes("w-full justify-end gap-2 mt-3"):
                    ui.button("Cancel", on_click=dlg.close).props(
                        "flat color=grey no-caps"
                    )

                    def _confirm():
                        dlg.close()
                        on_confirm()

                    ui.button("Sil", on_click=_confirm).props(
                        "color=negative no-caps"
                    )
            dlg.open()

        def _execute_action(action: str, results: list[dict], summary: dict, exts: set):
            try:
                action_res = validate_apply_action(
                    results,
                    source_root=STATE.dataset_path,
                    action=action,
                    invalid_dir=invalid_dir_input.value or None,
                    dry_run=dryrun_check.value,
                )
                # Rapor
                if action == "move" and invalid_dir_input.value:
                    report_path = Path(invalid_dir_input.value) / VALIDATE_REPORT_NAME
                else:
                    report_path = Path(STATE.dataset_path) / VALIDATE_REPORT_NAME
                _write_report_helper(
                    report_path,
                    summary=summary,
                    results=results,
                    action_result=action_res,
                    config=_build_config(),
                    exts=exts,
                )
                undo_input.set_value(str(report_path))
                STATE.last_report_paths[1] = str(report_path)

                dryrun_tag = " (DRY-RUN)" if dryrun_check.value else ""
                if action == "move":
                    msg = f"Taşınan: {len(action_res.entries)}{dryrun_tag} → {action_res.invalid_dir}"
                else:
                    msg = f"Silinen: {len(action_res.entries)}{dryrun_tag}"
                _populate_results(
                    results, summary,
                    action_msg=f"{msg}\nRapor: {report_path}",
                )
                ui.notify(msg, type="positive" if not dryrun_check.value else "info")
                STATE.notify_change()
            except Exception as e:
                ui.notify(f"Aksiyon hatası: {e}", type="negative")

        def _write_report_helper(report_path, *, summary, results, action_result,
                                  config, exts):
            validate_write_report(
                report_path,
                source_root=STATE.dataset_path,
                recursive=recursive_check.value,
                allowed_exts=exts,
                summary=summary,
                results=results,
                action_result=action_result,
                config_summary={
                    "allowed_formats": config["file_validation"]["allowed_formats"],
                    "min_short_edge": config["dimensions"]["min_short_edge"],
                    "max_short_edge": config["dimensions"]["max_short_edge"],
                    "aspect_ratio_range":
                        f"{config['dimensions']['aspect_ratio']['min']} - "
                        f"{config['dimensions']['aspect_ratio']['max']}",
                },
            )

        def _run_undo(dry_run: bool):
            report = undo_input.value or STATE.last_report_paths.get(1)
            if not report:
                ui.notify(
                    "Undo için rapor yolu girin (veya önce move/delete çalıştırın)",
                    type="negative",
                )
                return
            if not Path(report).exists():
                ui.notify(f"Rapor yok: {report}", type="negative")
                return
            try:
                summary = validate_undo_from_report(report, dry_run=dry_run)
                label = "Undo preview" if dry_run else "Undo"
                msg = (
                    f"{label}: restored={summary['restored']}, "
                    f"skipped={summary['skipped']}"
                )
                if summary["irreversible_deletes"]:
                    msg += f", irreversible_deletes={summary['irreversible_deletes']}"
                ui.notify(msg, type="info" if dry_run else "positive")
                summary_label.set_text(msg)
                if not dry_run:
                    STATE.notify_change()
            except Exception as e:
                ui.notify(f"{'Undo preview' if dry_run else 'Undo'} hatası: {e}",
                          type="negative")

        run_btn.on("click", on_run)
        undo_preview_btn.on("click", lambda: _run_undo(dry_run=True))
        undo_btn.on("click", lambda: _run_undo(dry_run=False))


def _path_to_url(path: str) -> str:
    """Lokal dosya path'ini UI'nın static mount'una göre URL'e çevir.
    /fs prefix'i main()'de mount edildi."""
    p = Path(path).resolve()
    return f"/fs{p}"


def _bpp_label(width: int, height: int, size_bytes: int) -> tuple[str, str] | None:
    """BPP (bytes per pixel) etiketi + Tailwind renk class — AI training context.

    Eşikler **AI/VAE encoder** için (göz değil): JPG q40-60 (0.05-0.5 aralığı)
    gözle temiz ama block-artifact'leri model'e training noise olarak gözükür.

    - < 0.05 → red    (DİSKALİFİYE — yıkıcı, q<10)
    - < 0.5  → yellow (suboptimal — JPG q70 altı, AI için ideal değil)
    - ≥ 0.5  → green  (AI training-ready — JPG q90+ / WebP q90+ / PNG)

    Eşikler core/actions.py BEST stratejisiyle aynı (DISQUALIFY_BPP=0.05,
    FULL_SCORE_BPP=0.5).
    """
    if not (width and height) or size_bytes <= 0:
        return None
    bpp = size_bytes / (width * height)
    if bpp < 0.05:
        color = "text-red-600"
        suffix = " ⚠"
    elif bpp < 0.5:
        color = "text-yellow-600"
        suffix = ""
    else:
        color = "text-green-600"
        suffix = ""
    return f"BPP {bpp:.3f}{suffix}", color


def build_duplicate_tab():
    """02 — Duplicate: exact/similar tarama + pair-wise gallery review + action + undo."""
    # Tab-local state — tab her render edildiğinde sıfırlanır
    tab_state: dict = {
        "scan_result": None,        # core.ScanResult
        "current_group_idx": 0,
        "manual_keepers": {},       # group_idx → kept_path (UI override)
    }

    with ui.column().classes("w-full max-w-screen-2xl mx-auto p-6 gap-4"):
        ui.label("02 — Duplicate").classes("text-2xl font-semibold")
        ui.label(
            "Exact (md5) veya similar (perceptual hash) duplicate tespit. "
            "Her grupta hangi dosyanın kalacağını seç (default: keep_strategy)."
        ).classes("text-sm text-slate-600")

        with ui.grid(columns="320px 1fr").classes("w-full gap-6 mt-2"):
            # ---------- Sol: Configuration ----------
            with ui.card().classes("w-full"):
                ui.label("Configuration").classes(
                    "text-sm uppercase text-slate-500 tracking-wide"
                )

                mode_select = ui.select(
                    {"exact": "Exact (md5)", "similar": "Similar (perceptual hash)"},
                    label="Mode",
                    value="exact",
                ).props("dense outlined").classes("w-full")

                # Similar parametreleri (mode=similar olduğunda görünür)
                with ui.column().classes("w-full gap-2") as similar_panel:
                    threshold_input = ui.number(
                        "Threshold (0-64, düşük=daha sıkı)",
                        value=10, min=0, max=64, step=1,
                    ).props("dense outlined").classes("w-full")
                    algorithm_select = ui.select(
                        ["phash", "ahash", "dhash", "whash", "average_hash"],
                        label="Algorithm",
                        value="phash",
                    ).props("dense outlined").classes("w-full")
                    workers_input = ui.number(
                        "Workers", value=0, min=0, step=1,
                        # 0 = CPU count
                    ).props("dense outlined").classes("w-full")
                similar_panel.visible = False

                def _toggle_similar(value: str):
                    similar_panel.visible = (value == "similar")
                mode_select.on_value_change(lambda e: _toggle_similar(e.value))

                recursive_check = ui.checkbox("Recursive", value=True)

                keep_strategy_select = ui.select(
                    {
                        "first": "İlk dosyayı tut",
                        "largest": "En büyük",
                        "smallest": "En küçük",
                        "highest_resolution": "En yüksek çözünürlük",
                        "best": "Best (BPP-aware composite)",
                    },
                    label="Keep strategy (default)",
                    value="first",
                ).props("dense outlined").classes("w-full")

                default_zoom_select = ui.select(
                    {
                        "fit": "Fit (ekrana sığar)",
                        "1.0": "100% (gerçek piksel)",
                        "2.0": "200%",
                        "0.5": "50%",
                    },
                    label="Lightbox başlangıç zoom",
                    value="fit",
                ).props("dense outlined").classes("w-full")

                def _on_default_zoom_change(value: str):
                    tab_state["default_zoom"] = (
                        "fit" if value == "fit" else float(value)
                    )
                default_zoom_select.on_value_change(
                    lambda e: _on_default_zoom_change(e.value)
                )

                action_select = ui.select(
                    {
                        "none": "Sadece raporla (default)",
                        "move": "/rejected'a taşı (undoable)",
                        "delete": "Sil (irreversible)",
                    },
                    label="Aksiyon",
                    value="none",
                ).props("dense outlined").classes("w-full")

                with ui.row().classes("w-full items-center gap-1 no-wrap"):
                    invalid_dir_input = ui.input(
                        "Invalid dir",
                        placeholder="move için zorunlu",
                    ).props("dense outlined").classes("flex-grow")
                    ui.button(
                        icon="folder_open",
                        on_click=lambda: _open_browse_dialog(
                            invalid_dir_input, title="Rejected dizini seç"
                        ),
                    ).props("flat dense color=grey-7").tooltip("Browse")

                with ui.row().classes("gap-3 mt-1"):
                    dryrun_check = ui.checkbox("Dry-run", value=True)
                    yes_check = ui.checkbox("Onaysız (delete)", value=False)

                with ui.row().classes("gap-2 mt-3 w-full items-center"):
                    scan_btn = ui.button("Scan").props("color=primary no-caps")
                    apply_btn = ui.button("Aksiyonu uygula").props(
                        "color=positive no-caps"
                    )
                    apply_btn.disable()
                progress_label = ui.label("").classes("text-xs text-slate-600")
                progress_bar = ui.linear_progress(
                    value=0, show_value=False
                ).classes("w-full")
                progress_bar.visible = False

                ui.separator().classes("my-3")
                ui.label("Undo").classes(
                    "text-sm uppercase text-slate-500 tracking-wide"
                )
                undo_input = ui.input(
                    "duplicate_report.json yolu",
                    placeholder="(move action sonrası otomatik dolar)",
                ).props("dense outlined").classes("w-full")
                with ui.row().classes("gap-2"):
                    undo_preview_btn = ui.button("Preview").props(
                        "outline color=primary no-caps"
                    )
                    undo_btn = ui.button("Undo").props(
                        "outline color=grey-7 no-caps"
                    )

            # ---------- Sağ: Sonuç + Gallery ----------
            with ui.card().classes("w-full"):
                ui.label("Sonuç").classes(
                    "text-sm uppercase text-slate-500 tracking-wide"
                )
                summary_label = ui.label(
                    "Henüz scan yapılmadı — sol panelde Scan tıkla."
                ).classes("text-sm text-slate-600 italic mt-1")

                with ui.row().classes("w-full justify-around mt-2"):
                    for label_text in ("Total", "Unique", "Groups", "Removable"):
                        with ui.column().classes("items-center gap-0"):
                            card = ui.label("—").classes("text-2xl font-bold text-slate-700")
                            tab_state.setdefault("stat_cards", {})[label_text.lower()] = card
                            ui.label(label_text).classes(
                                "text-xs uppercase text-slate-500 tracking-wide"
                            )
                space_label = ui.label("").classes("text-xs text-slate-500 text-center mt-1")

                ui.separator().classes("my-3")

                # Group navigator
                with ui.row().classes("w-full items-center gap-2"):
                    prev_btn = ui.button(icon="chevron_left").props(
                        "flat dense color=grey-7"
                    )
                    group_label = ui.label("Grup —").classes("text-base font-semibold")
                    next_btn = ui.button(icon="chevron_right").props(
                        "flat dense color=grey-7"
                    )
                    ui.space()
                    ui.label("Bulk:").classes("text-xs text-slate-500")
                    bulk_first_btn = ui.button("first").props(
                        "flat dense color=grey-7"
                    ).tooltip("İlk dosya")
                    bulk_largest_btn = ui.button("largest").props(
                        "flat dense color=grey-7"
                    ).tooltip("En büyük byte")
                    bulk_best_btn = ui.button("best").props(
                        "flat dense color=primary"
                    ).tooltip("BPP-aware: AI training quality")
                    bulk_hires_btn = ui.button("hi-res").props(
                        "flat dense color=grey-7"
                    ).tooltip("En yüksek çözünürlük")
                prev_btn.disable()
                next_btn.disable()

                # Group içerik paneli (gallery)
                gallery_panel = ui.column().classes("w-full gap-3")
                with gallery_panel:
                    ui.label("Scan sonrası burada görsel grup gösterilir.").classes(
                        "text-sm text-slate-500 italic"
                    )

        # ------------- Action handlers -------------

        def _build_config() -> dict:
            return {
                "mode": mode_select.value,
                "threshold": int(threshold_input.value or 10),
                "algorithm": algorithm_select.value,
                "workers": int(workers_input.value or 0) or None,
            }

        def _validate_inputs() -> Optional[str]:
            if not STATE.is_valid_dataset():
                return "Dataset yolu geçerli değil (header'da doğrula)"
            if action_select.value == "move" and not invalid_dir_input.value:
                return "Move için Invalid dir gerekli"
            return None

        def _on_action_change(value: str):
            if value == "move" and not invalid_dir_input.value and STATE.dataset_path:
                invalid_dir_input.value = str(Path(STATE.dataset_path) / "duplicates_rejected")
                invalid_dir_input.update()
        action_select.on_value_change(lambda e: _on_action_change(e.value))

        def _refresh_stats():
            sr = tab_state["scan_result"]
            if sr is None:
                return
            cards = tab_state["stat_cards"]
            cards["total"].set_text(str(sr.total_scanned))
            cards["unique"].set_text(str(sr.unique_count))
            cards["groups"].set_text(str(len(sr.groups)))
            cards["removable"].set_text(str(sr.removable_count))
            space_label.set_text(
                f"Kazanılabilecek: {dedup_humanize_bytes(sr.space_freeable_bytes)}"
            )

        def _refresh_gallery():
            sr = tab_state["scan_result"]
            gallery_panel.clear()
            if sr is None or not sr.groups:
                with gallery_panel:
                    if sr is not None:
                        ui.label("Duplicate bulunamadı — temiz dataset.").classes(
                            "text-sm text-slate-500"
                        )
                    else:
                        ui.label("Scan sonrası burada görsel grup gösterilir.").classes(
                            "text-sm text-slate-500 italic"
                        )
                return

            idx = tab_state["current_group_idx"]
            idx = max(0, min(idx, len(sr.groups) - 1))
            tab_state["current_group_idx"] = idx
            grp = sr.groups[idx]

            group_label.set_text(f"Grup {idx + 1} / {len(sr.groups)}  ·  {len(grp.files)} dosya")

            # Manuel keeper varsa onu kullan, yoksa group.kept (apply_action sonrası)
            # veya files[0]['path'] (default first)
            current_keeper = (
                tab_state["manual_keepers"].get(idx)
                or grp.kept
                or grp.files[0]["path"]
            )

            with gallery_panel:
                # Hash + algorithm bilgi
                meta_text = f"hash={grp.hash[:12]}…  algorithm={grp.algorithm}"
                if grp.threshold is not None:
                    meta_text += f"  threshold={grp.threshold}"
                ui.label(meta_text).classes("text-xs font-mono text-slate-500")

                # Dosya kartları — yan yana grid
                num_cols = min(4, len(grp.files))
                with ui.grid(columns=f"repeat({num_cols}, 1fr)").classes("w-full gap-3"):
                    for f in grp.files:
                        path = f["path"]
                        is_keeper = (path == current_keeper)
                        card_classes = (
                            "p-2 rounded border-2 "
                            + ("border-green-500 bg-green-50"
                               if is_keeper else "border-slate-200")
                        )
                        with ui.column().classes(card_classes):
                            # Thumbnail — tıklayınca lightbox modal aç
                            try:
                                img_widget = ui.image(_path_to_url(path)).classes(
                                    "w-full h-72 object-contain bg-slate-100 cursor-pointer "
                                    "hover:opacity-90 transition"
                                )
                                img_widget.on(
                                    "click", lambda _e, p=path: _open_lightbox(p)
                                )
                                img_widget.tooltip("Büyük görüntü için tıkla")
                            except Exception:
                                ui.label("(önizleme yok)").classes("text-xs text-slate-400")

                            with ui.row().classes("w-full items-center gap-1"):
                                ui.label(Path(path).name).classes(
                                    "text-xs font-mono truncate flex-grow"
                                ).tooltip(path)
                                ui.button(
                                    icon="open_in_new",
                                    on_click=lambda p=path: _open_lightbox(p),
                                ).props("flat dense size=sm color=grey-7").tooltip("Aç")

                            # Resolution + size + (similar mode'da distance)
                            sz = f.get("size_bytes", 0)
                            info_parts = [dedup_humanize_bytes(sz)]
                            w, h = f.get("width", 0), f.get("height", 0)
                            if w and h:
                                info_parts.insert(0, f"{w}×{h}")
                            if "distance" in f:
                                info_parts.append(f"d={f['distance']}")
                            ui.label(" · ".join(info_parts)).classes(
                                "text-xs text-slate-600"
                            )
                            # BPP — renkli (kalite göstergesi)
                            bpp_info = _bpp_label(w, h, sz)
                            if bpp_info:
                                bpp_text, bpp_color = bpp_info
                                ui.label(bpp_text).classes(
                                    f"text-xs font-mono {bpp_color}"
                                ).tooltip(
                                    "Bytes per pixel — AI training quality\n"
                                    "< 0.05: yıkıcı (DQ), < 0.5: suboptimal\n"
                                    "≥ 0.5: training-ready (JPG q90+/PNG)"
                                )
                            keep_btn_label = "✓ Korunan" if is_keeper else "Bunu tut"
                            keep_btn_color = "color=positive" if is_keeper else "color=grey-7"
                            ui.button(
                                keep_btn_label,
                                on_click=lambda p=path, i=idx: _set_keeper(i, p),
                            ).props(f"flat dense {keep_btn_color} no-caps")

        def _open_lightbox(start_path: str):
            """Tam ekran lightbox + carousel + zoom — ←/→ ile grup içinde gez,
            +/− ile zoom, 0=Fit, 1=100%, "Bunu tut" ile keeper seç. Native <img>
            + viewport units (Quasar QImg padding-bottom hack'i atlatıldı)."""
            sr = tab_state["scan_result"]
            if sr is None or not sr.groups:
                return
            grp = sr.groups[tab_state["current_group_idx"]]
            files = grp.files
            if not files:
                return
            start_idx = next(
                (i for i, f in enumerate(files) if f["path"] == start_path), 0
            )
            # zoom: 'fit' (default — ekrana sığar) veya float (1.0=100% natural pixel)
            lb_state = {"idx": start_idx, "zoom": tab_state.get("default_zoom", "fit")}

            with ui.dialog().props("maximized") as dlg, ui.card().classes(
                "w-full h-screen p-0 bg-black overflow-hidden"
            ):
                # overflow-auto: zoom > fit'te scrollbar otomatik çıkar
                with ui.column().classes(
                    "w-full h-full overflow-auto relative bg-black "
                    "items-center justify-center"
                ):
                    # Image holder — set_content ile güncelleniyor
                    img_html = ui.html("")

                    # Üst overlay: filename + zoom kontrol + keep + close
                    with ui.row().classes(
                        "absolute top-2 left-2 right-2 items-center gap-2 z-10 flex-wrap"
                    ):
                        title_label = ui.label("").classes(
                            "text-white text-sm bg-black/60 px-3 py-1 rounded font-mono"
                        )
                        info_label = ui.label("").classes(
                            "text-white text-xs bg-black/60 px-2 py-1 rounded"
                        )
                        bpp_label_widget = ui.label("").classes(
                            "text-xs px-2 py-1 rounded bg-black/60"
                        )
                        ui.space()
                        # Zoom kontrolleri
                        with ui.row().classes(
                            "items-center gap-1 bg-black/60 rounded px-1"
                        ):
                            ui.button(icon="remove").props(
                                "flat dense color=white size=sm"
                            ).tooltip("Zoom out (−)").on(
                                "click", lambda: _zoom_step(-1)
                            )
                            zoom_btn = ui.button("Fit").props(
                                "flat dense color=white size=sm no-caps"
                            ).tooltip("Fit ↔ 100% (çift tıkla / 0 / 1)")
                            zoom_btn.on("click", lambda: _zoom_toggle())
                            ui.button(icon="add").props(
                                "flat dense color=white size=sm"
                            ).tooltip("Zoom in (+)").on(
                                "click", lambda: _zoom_step(1)
                            )
                        keeper_badge = ui.label("").classes(
                            "text-white text-xs px-3 py-1 rounded"
                        )
                        keep_btn = ui.button("Bunu tut").props(
                            "color=positive no-caps"
                        )
                        ui.button(icon="close", on_click=dlg.close).props(
                            "flat round color=white"
                        ).tooltip("Kapat (Esc)")

                    # Sol-sağ navigation (sadece >1 dosya varsa)
                    if len(files) > 1:
                        ui.button(icon="chevron_left").props(
                            "fab-mini color=white text-color=black"
                        ).classes(
                            "absolute left-4 top-1/2 -translate-y-1/2 z-10 opacity-80"
                        ).on("click", lambda: _lb_step(-1))
                        ui.button(icon="chevron_right").props(
                            "fab-mini color=white text-color=black"
                        ).classes(
                            "absolute right-4 top-1/2 -translate-y-1/2 z-10 opacity-80"
                        ).on("click", lambda: _lb_step(1))

                    # Alt overlay: dosya sayacı + klavye hint
                    with ui.row().classes(
                        "absolute bottom-2 left-1/2 -translate-x-1/2 "
                        "items-center gap-2 z-10"
                    ):
                        counter_label = ui.label("").classes(
                            "text-white text-sm bg-black/60 px-3 py-1 rounded font-mono"
                        )
                        hint_parts = []
                        if len(files) > 1:
                            hint_parts.append("← →")
                        hint_parts.append("+ −")
                        hint_parts.append("0=Fit")
                        hint_parts.append("1=100%")
                        ui.label(" · ".join(hint_parts)).classes(
                            "text-white text-xs bg-black/40 px-2 py-1 rounded"
                        )

                    # Zoom step preset'leri (% cinsinden)
                    ZOOM_LEVELS = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0]

                    def _render():
                        f = files[lb_state["idx"]]
                        path = f["path"]
                        url = _path_to_url(path)
                        w, h = f.get("width", 0), f.get("height", 0)
                        sz = f.get("size_bytes", 0)
                        title_label.set_text(Path(path).name)
                        info_parts = []
                        if w and h:
                            info_parts.append(f"{w}×{h}")
                        info_parts.append(dedup_humanize_bytes(sz))
                        if "distance" in f:
                            info_parts.append(f"d={f['distance']}")
                        info_label.set_text(" · ".join(info_parts))

                        # BPP — kalite göstergesi (renkli)
                        bpp_info = _bpp_label(w, h, sz)
                        if bpp_info:
                            bpp_text, bpp_color_class = bpp_info
                            bpp_label_widget.set_text(bpp_text)
                            # Renk + bg birlikte (overlay için kontrast)
                            bpp_label_widget.classes(
                                replace=(
                                    f"{bpp_color_class} bg-white/90 "
                                    "text-xs px-2 py-1 rounded font-mono font-semibold"
                                )
                            )
                            bpp_label_widget.tooltip(
                                "Bytes per pixel — AI training quality\n"
                                "< 0.05: yıkıcı (DQ — q<10 artifact)\n"
                                "0.05-0.5: suboptimal (JPG q70 altı, training noise)\n"
                                "≥ 0.5: training-ready (JPG q90+, WebP q90+, PNG)"
                            )
                        else:
                            bpp_label_widget.set_text("")

                        # Zoom — fit (ekrana sığar) veya natural × ratio (scrollable)
                        z = lb_state["zoom"]
                        if z == "fit" or not (w and h):
                            img_style = (
                                "max-width: 100vw; max-height: 100vh; "
                                "width: auto; height: auto; "
                                "object-fit: contain; display: block; margin: auto;"
                            )
                            zoom_btn.set_text("Fit")
                        else:
                            # natural × zoom — scrollable
                            disp_w = int(w * z)
                            disp_h = int(h * z)
                            img_style = (
                                f"width: {disp_w}px; height: {disp_h}px; "
                                f"max-width: none; max-height: none; "
                                f"display: block; margin: auto;"
                            )
                            zoom_btn.set_text(f"{int(z*100)}%")

                        # Keeper indicator
                        manual = tab_state["manual_keepers"].get(
                            tab_state["current_group_idx"]
                        )
                        is_keeper = (path == (manual or grp.kept))
                        if is_keeper:
                            keeper_badge.set_text("✓ Korunan")
                            keeper_badge.classes(
                                replace="bg-green-600 text-white text-xs px-3 py-1 rounded"
                            )
                            keep_btn.props("color=grey-7 no-caps")
                            keep_btn.set_text("Korunuyor")
                            keep_btn.disable()
                        else:
                            keeper_badge.set_text("")
                            keep_btn.props("color=positive no-caps")
                            keep_btn.set_text("Bunu tut")
                            keep_btn.enable()

                        counter_label.set_text(
                            f"{lb_state['idx'] + 1} / {len(files)}"
                        )
                        img_html.set_content(
                            f'<img src="{url}" style="{img_style}">'
                        )

                    def _lb_step(delta: int):
                        lb_state["idx"] = (lb_state["idx"] + delta) % len(files)
                        _render()

                    def _lb_keep():
                        path = files[lb_state["idx"]]["path"]
                        _set_keeper(tab_state["current_group_idx"], path)
                        _render()  # badge + buton update

                    def _zoom_step(delta: int):
                        """+1 zoom in, −1 zoom out. Fit'tekiyse 1.0'a (100%)
                        atlar; ZOOM_LEVELS preset'leri arasında step."""
                        z = lb_state["zoom"]
                        if z == "fit":
                            # Fit'ten zoom in/out — 1.0'dan başla
                            lb_state["zoom"] = 1.0 if delta > 0 else "fit"
                        else:
                            try:
                                idx = ZOOM_LEVELS.index(z)
                            except ValueError:
                                # Listedeki en yakına yuvarla
                                idx = min(
                                    range(len(ZOOM_LEVELS)),
                                    key=lambda i: abs(ZOOM_LEVELS[i] - z),
                                )
                            new_idx = max(0, min(len(ZOOM_LEVELS) - 1, idx + delta))
                            lb_state["zoom"] = ZOOM_LEVELS[new_idx]
                        _render()

                    def _zoom_toggle():
                        """Fit ↔ 100% toggle (zoom buton tıklaması)."""
                        lb_state["zoom"] = (
                            1.0 if lb_state["zoom"] == "fit" else "fit"
                        )
                        _render()

                    def _zoom_set(value):
                        lb_state["zoom"] = value
                        _render()

                    keep_btn.on("click", _lb_keep)

                    # Klavye desteği
                    def _on_key(e):
                        if not e.action.keydown:
                            return
                        if e.key.arrow_left:
                            _lb_step(-1)
                        elif e.key.arrow_right:
                            _lb_step(1)
                        elif e.key.enter:
                            _lb_keep()
                        elif str(e.key) in {"+", "="}:
                            _zoom_step(1)
                        elif str(e.key) == "-":
                            _zoom_step(-1)
                        elif str(e.key) == "0":
                            _zoom_set("fit")
                        elif str(e.key) == "1":
                            _zoom_set(1.0)

                    keyboard = ui.keyboard(on_key=_on_key, active=True)
                    dlg.on("hide", lambda: setattr(keyboard, "active", False))

                    _render()
            dlg.open()

        def _set_keeper(group_idx: int, path: str):
            tab_state["manual_keepers"][group_idx] = path
            _refresh_gallery()

        def _go_prev():
            if tab_state["scan_result"] and tab_state["current_group_idx"] > 0:
                tab_state["current_group_idx"] -= 1
                _refresh_gallery()

        def _go_next():
            sr = tab_state["scan_result"]
            if sr and tab_state["current_group_idx"] < len(sr.groups) - 1:
                tab_state["current_group_idx"] += 1
                _refresh_gallery()

        prev_btn.on("click", _go_prev)
        next_btn.on("click", _go_next)

        def _bulk_set_keeper(strategy: str):
            """Tüm gruplara keep_strategy uygula. dedup_apply_action(action='none')
            ile g.kept'leri set ettirip manual_keepers'a kopyalıyoruz —
            tüm stratejiler (first/largest/smallest/highest_resolution/best)
            için ortak yol."""
            sr = tab_state["scan_result"]
            if sr is None:
                return
            try:
                dedup_apply_action(sr, action="none", keep_strategy=strategy)
                for i, g in enumerate(sr.groups):
                    if g.kept:
                        tab_state["manual_keepers"][i] = g.kept
                _refresh_gallery()
                ui.notify(
                    f"Bulk keeper={strategy} uygulandı ({len(sr.groups)} grup)",
                    type="info",
                )
            except Exception as e:
                ui.notify(f"Bulk hatası: {e}", type="negative")

        bulk_first_btn.on("click", lambda: _bulk_set_keeper("first"))
        bulk_largest_btn.on("click", lambda: _bulk_set_keeper("largest"))
        bulk_best_btn.on("click", lambda: _bulk_set_keeper("best"))
        bulk_hires_btn.on("click", lambda: _bulk_set_keeper("highest_resolution"))

        async def on_scan():
            err = _validate_inputs()
            if err:
                ui.notify(err, type="negative")
                return

            cfg = _build_config()
            if cfg["mode"] == "similar" and not DupHasher.is_perceptual_hash_available():
                ui.notify("imagehash kütüphanesi yüklü değil", type="negative")
                return

            scan_btn.disable()
            apply_btn.disable()
            progress_bar.visible = True
            progress_bar.set_value(0)
            progress_label.set_text("Tarama…")

            def _cb(current: int, total: int, msg: str):
                if total > 0:
                    progress_bar.set_value(current / total)
                progress_label.set_text(msg)

            try:
                await asyncio.sleep(0)
                if cfg["mode"] == "exact":
                    sr = find_exact_duplicates(
                        STATE.dataset_path,
                        recursive=recursive_check.value,
                        progress_cb=_cb,
                    )
                else:
                    sr = find_similar_images(
                        STATE.dataset_path,
                        threshold=cfg["threshold"],
                        algorithm=cfg["algorithm"],
                        recursive=recursive_check.value,
                        workers=cfg["workers"],
                        progress_cb=_cb,
                    )

                tab_state["scan_result"] = sr
                tab_state["current_group_idx"] = 0
                tab_state["manual_keepers"] = {}

                # Initial keeper'ları seçili strategy ile set et
                # (apply_action wrapping üzerinden tüm strategy'ler destekli)
                _bulk_set_keeper(keep_strategy_select.value)

                _refresh_stats()
                _refresh_gallery()

                if sr.has_duplicates:
                    prev_btn.enable()
                    next_btn.enable()
                    apply_btn.enable()
                else:
                    prev_btn.disable()
                    next_btn.disable()
                    apply_btn.disable()

                summary_label.set_text(
                    f"Scan tamam: {len(sr.groups)} grup, "
                    f"{sr.removable_count} silinebilir, "
                    f"{dedup_humanize_bytes(sr.space_freeable_bytes)} kazanım"
                )
                ui.notify(
                    f"{len(sr.groups)} grup bulundu" if sr.has_duplicates
                    else "Duplicate bulunamadı",
                    type="positive" if sr.has_duplicates else "info",
                )
            except Exception as e:
                ui.notify(f"Scan hatası: {e}", type="negative")
            finally:
                progress_bar.visible = False
                progress_label.set_text("")
                scan_btn.enable()

        scan_btn.on("click", on_scan)

        def _confirm_delete_dialog(count: int, *, on_confirm):
            with ui.dialog() as dlg, ui.card().classes("w-[500px]"):
                ui.label("⚠ Kalıcı silme onayı").classes("text-lg font-semibold")
                ui.label(
                    f"{count} duplicate dosya KALICI olarak silinecek. "
                    "Bu işlem geri alınamaz. Önce 'Move' ile dene."
                ).classes("text-sm text-slate-700")
                with ui.row().classes("w-full justify-end gap-2 mt-3"):
                    ui.button("Cancel", on_click=dlg.close).props("flat color=grey no-caps")

                    def _confirm():
                        dlg.close()
                        on_confirm()

                    ui.button("Sil", on_click=_confirm).props("color=negative no-caps")
            dlg.open()

        def _do_apply():
            sr = tab_state["scan_result"]
            if sr is None:
                ui.notify("Önce Scan çalıştır", type="negative")
                return

            # Manuel keeper override'larını apply_action'a uygulanacak şekilde
            # ScanResult.groups[*].files'ı yeniden sırala — keeper ilk eleman
            # olsun, böylece keep_strategy="first" doğru sonucu verir.
            for i, g in enumerate(sr.groups):
                manual = tab_state["manual_keepers"].get(i)
                if manual:
                    # Manual'i listenin başına al
                    files = g.files
                    keep_idx = next(
                        (k for k, f in enumerate(files) if f["path"] == manual),
                        0,
                    )
                    if keep_idx != 0:
                        g.files = [files[keep_idx]] + files[:keep_idx] + files[keep_idx + 1:]

            action = action_select.value
            if action == "delete" and not dryrun_check.value and not yes_check.value:
                _confirm_delete_dialog(sr.removable_count, on_confirm=_do_apply_inner)
                return
            _do_apply_inner()

        def _do_apply_inner():
            sr = tab_state["scan_result"]
            try:
                ar = dedup_apply_action(
                    sr,
                    action=action_select.value,
                    invalid_dir=invalid_dir_input.value or None,
                    keep_strategy="first",  # zaten manuel keeper'ı başa aldık
                    dry_run=dryrun_check.value,
                )

                if action_select.value == "move" and invalid_dir_input.value:
                    report_path = Path(invalid_dir_input.value) / DEDUP_REPORT_NAME
                else:
                    report_path = Path(STATE.dataset_path) / DEDUP_REPORT_NAME

                cfg = _build_config()
                dedup_write_report(
                    report_path,
                    scan_result=sr,
                    action_result=ar,
                    recursive=recursive_check.value,
                    config=cfg,
                )
                undo_input.set_value(str(report_path))
                STATE.last_report_paths[2] = str(report_path)

                dryrun_tag = " (DRY-RUN)" if dryrun_check.value else ""
                if action_select.value == "move":
                    msg = f"Taşınan: {len(ar.entries)}{dryrun_tag} → {ar.invalid_dir}"
                elif action_select.value == "delete":
                    msg = f"Silinen: {len(ar.entries)}{dryrun_tag}"
                else:
                    msg = f"Sadece raporlandı: {len(sr.groups)} grup"
                summary_label.set_text(f"{msg}\nRapor: {report_path}")
                ui.notify(msg, type="positive" if not dryrun_check.value else "info")
                STATE.notify_change()
            except Exception as e:
                ui.notify(f"Aksiyon hatası: {e}", type="negative")

        apply_btn.on("click", _do_apply)

        def _run_undo(dry_run: bool):
            report = undo_input.value or STATE.last_report_paths.get(2)
            if not report:
                ui.notify("Undo için rapor yolu girin", type="negative")
                return
            if not Path(report).exists():
                ui.notify(f"Rapor yok: {report}", type="negative")
                return
            try:
                summary = dedup_undo_from_report(report, dry_run=dry_run)
                label = "Undo preview" if dry_run else "Undo"
                msg = (
                    f"{label}: restored={summary['restored']}, "
                    f"skipped={summary['skipped']}"
                )
                if summary["irreversible_deletes"]:
                    msg += f", irreversible_deletes={summary['irreversible_deletes']}"
                ui.notify(msg, type="info" if dry_run else "positive")
                summary_label.set_text(msg)
                if not dry_run:
                    STATE.notify_change()
            except Exception as e:
                ui.notify(f"Undo hatası: {e}", type="negative")

        undo_preview_btn.on("click", lambda: _run_undo(dry_run=True))
        undo_btn.on("click", lambda: _run_undo(dry_run=False))


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
