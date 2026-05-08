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
    (1, "Validate", "Format ve dosya bütünlüğü kontrolü", False),
    (2, "Duplicate", "Birebir + benzer kopya tespiti", False),
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

    with ui.tab_panels(tabs, value=initial).classes("w-full"):
        with ui.tab_panel(overview_tab):
            build_overview_tab()
        for (idx, name, desc, wired), tab_obj in zip(PIPELINE_STEPS, step_tab_objs):
            with ui.tab_panel(tab_obj):
                if wired:
                    build_organize_tab()  # şimdilik sadece 00 wired
                else:
                    build_stub_tab(idx, name, desc)


def main():
    ui.run(
        title="Media Dataset Prep",
        port=int(os.environ.get("UI_PORT", "8200")),
        reload=False,
        show=False,
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
