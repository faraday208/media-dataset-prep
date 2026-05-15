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
from validator_core.validators.file_validator import FileValidator  # noqa: E402
from validator_core.scanner import (  # noqa: E402
    collect_images as validate_collect_images,
    apply_action as validate_apply_action,
    undo_from_report as validate_undo_from_report,
    write_report as validate_write_report,
    DEFAULT_REPORT_NAME as VALIDATE_REPORT_NAME,
)
# media-deduplicator (tools/02-duplicate) — dedup_core paketi
from dedup_core import (  # noqa: E402
    Hasher as DupHasher,
    apply_action as dedup_apply_action,
    find_exact_duplicates,
    find_similar_images,
    humanize_bytes as dedup_humanize_bytes,
    undo_from_report as dedup_undo_from_report,
    write_report as dedup_write_report,
    DEFAULT_REPORT_NAME as DEDUP_REPORT_NAME,
)
# media-quality-checker (tools/03-quality) — quality_core paketi
from quality_core import (  # noqa: E402
    apply_action as quality_apply_action,
    find_quality_issues,
    undo_from_report as quality_undo_from_report,
    write_report as quality_write_report,
    DEFAULT_REPORT_NAME as QUALITY_REPORT_NAME,
)
# media-captioner (tools/06-caption) — caption_core paketi
from caption_core import batch_client as caption_batch_client  # noqa: E402
from caption_core.batch_client import (  # noqa: E402
    PASS_CONFIG as CAPTION_PASS_CONFIG,
    SUPPORTED_EXTENSIONS as CAPTION_SUPPORTED_EXTENSIONS,
    check_server_health as caption_check_server_health,
)
from caption_core.json_to_txt import extract_captions as caption_extract_captions  # noqa: E402
# media-golden-set (tools/07-golden-set) — goldenset_core paketi
from goldenset_core import (  # noqa: E402
    apply_selection as golden_apply_selection,
    parse_distribution as golden_parse_distribution,
    select as golden_select,
    undo_from_report as golden_undo_from_report,
    write_report as golden_write_report,
)
# media-watermark-detector (tools/04-watermark) — watermark_core paketi
from watermark_core import (  # noqa: E402
    apply_action as watermark_apply_action,
    find_watermarks,
    undo_from_report as watermark_undo_from_report,
    write_report as watermark_write_report,
    DEFAULT_CONFIDENCE as WATERMARK_DEFAULT_CONFIDENCE,
    DEFAULT_MODEL_PATH as WATERMARK_DEFAULT_MODEL_PATH,
    DEFAULT_REPORT_NAME as WATERMARK_REPORT_NAME,
)
# media-resizer (tools/05-resize) — resize_core paketi
from resize_core import (  # noqa: E402
    resize_dataset,
    undo_from_report as resize_undo_from_report,
    write_report as resize_write_report,
    DEFAULT_REPORT_NAME as RESIZE_REPORT_NAME,
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
    available_outputs: dict[int, str] = field(default_factory=dict)
    _dismissed_outputs: set[int] = field(default_factory=set)
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

    def register_output(self, step_idx: int, output_dir: str) -> None:
        """Output üreten adım (Organize copy/move, Resize copy, Golden-set) execute
        sonrası çağırır. dataset_path değişmez; banner ile kullanıcıya 'switch'
        teklif edilir. Aynı dizine register edilirse no-op."""
        if not output_dir:
            return
        try:
            norm = str(Path(output_dir).resolve())
            cur = str(Path(self.dataset_path).resolve()) if self.dataset_path else ""
        except OSError:
            return
        if norm == cur:
            return
        self.available_outputs[step_idx] = norm
        self._dismissed_outputs.discard(step_idx)
        self.notify_change()

    def latest_output(self) -> Optional[tuple[int, str]]:
        """En yeni (en yüksek step idx) dismiss edilmemiş output'u döndür."""
        active = {k: v for k, v in self.available_outputs.items()
                  if k not in self._dismissed_outputs}
        if not active:
            return None
        idx = max(active)
        return idx, active[idx]

    def switch_to(self, output_dir: str) -> None:
        """Banner'daki Switch butonu çağırır — dataset_path'i değiştirir."""
        self.dataset_path = output_dir
        self.notify_change()

    def dismiss_output(self, step_idx: int) -> None:
        """Banner'daki Dismiss butonu çağırır — output saklı kalır ama banner'da
        gösterilmez (re-register'da otomatik geri gelir)."""
        self._dismissed_outputs.add(step_idx)
        self.notify_change()

    def clear_output(self, step_idx: int) -> None:
        """Undo başarılı olduğunda çağrılır — output artık geçersiz, banner'dan
        tamamen temizle."""
        self.available_outputs.pop(step_idx, None)
        self._dismissed_outputs.discard(step_idx)
        self.notify_change()


STATE = PipelineState()


# Pipeline adımları — (idx, name, desc, wired)
# wired=True: meta UI'da tab tam fonksiyonel
# wired=False: stub tab + "soon" badge (tool kendi başına CLI ile kullanılabilir)
PIPELINE_STEPS: list[tuple[int, str, str, bool]] = [
    (0, "Organize", "Dosya isimlerini düzenli numaralandır", True),
    (1, "Validate", "Format ve dosya bütünlüğü kontrolü", True),
    (2, "Duplicate", "Birebir + benzer kopya tespiti", True),
    (3, "Quality", "Blur, brightness, contrast, BPP metrikleri", True),
    (4, "Watermark", "YOLOv8 ile filigran tespit + filtreleme", True),
    (5, "Resize", "Lanczos batch resize (copy/in-place)", True),
    (6, "Caption", "Qwen3-VL multi-pass caption + insan onayı", True),
    (7, "Golden Set", "Quality + caption-aware cherry-pick", True),
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


def _wire_latest_output_link(input_widget) -> None:
    """Form input'un altına 'pipeline'daki son output'u kullan' butonu ekle.
    Butona basılınca form input STATE.latest_output()[1]'e set edilir — global
    STATE.dataset_path değişmez (form-local override). Görünürlüğü reaktif:
    latest_output mevcutsa + form değerinden farklıysa görünür."""
    def _use_latest(_=None):
        latest = STATE.latest_output()
        if latest:
            input_widget.set_value(latest[1])
            ui.notify(f"Form input → {latest[1]}", type="info")

    btn = ui.button(
        "⇡ Pipeline'daki son output'u kullan",
        on_click=_use_latest,
    ).props("flat dense color=primary no-caps").classes("text-xs")

    def _refresh_visibility():
        latest = STATE.latest_output()
        if not latest:
            btn.visible = False
            return
        try:
            cur = str(Path(input_widget.value).resolve()) if input_widget.value else ""
        except OSError:
            cur = input_widget.value or ""
        btn.visible = latest[1] != cur

    _refresh_visibility()
    STATE.on_change(_refresh_visibility)
    input_widget.on_value_change(lambda _e: _refresh_visibility())


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

    # Lazy banner: output üreten adımdan sonra "yeni klasöre geç" affordance'ı.
    # Header'ın altına sticky bir row olarak iner.
    banner_row = ui.row().classes(
        "w-full bg-amber-100 px-4 py-2 items-center gap-3"
    )

    def refresh_banner() -> None:
        banner_row.clear()
        latest = STATE.latest_output()
        if not latest:
            banner_row.style("display:none")
            return
        idx, output_dir = latest
        try:
            cur_norm = str(Path(STATE.dataset_path).resolve()) if STATE.dataset_path else ""
        except OSError:
            cur_norm = STATE.dataset_path or ""
        if output_dir == cur_norm:
            banner_row.style("display:none")
            return
        banner_row.style("display:flex")
        step_name = PIPELINE_STEPS[idx][1]
        with banner_row:
            ui.icon("swap_horiz").classes("text-amber-700")
            ui.label(f"Step {idx:02d} {step_name} yeni output:").classes(
                "text-sm font-medium text-amber-900"
            )
            ui.label(output_dir).classes("text-sm font-mono text-amber-800")

            def _switch(_=None, target=output_dir):
                STATE.switch_to(target)
                ui.notify(f"Dataset → {target}", type="positive")

            def _dismiss(_=None, step=idx):
                STATE.dismiss_output(step)

            ui.button("Switch", on_click=_switch).props(
                "dense color=amber-9 no-caps"
            ).classes("ml-auto")
            ui.button("Dismiss", on_click=_dismiss).props(
                "flat dense color=amber-9 no-caps"
            )

    refresh_banner()
    STATE.on_change(refresh_banner)


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
                    _suggest_output_dir(mode_select.value)

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

                def _suggest_output_dir(mode: str) -> None:
                    """Copy/move seçildiğinde output_input boşsa
                    `{dataset_path}/organized`'i önerir."""
                    if (
                        mode in ("copy", "move")
                        and not output_input.value
                        and STATE.dataset_path
                    ):
                        output_input.set_value(
                            os.path.join(STATE.dataset_path, "organized")
                        )

                mode_select.on_value_change(
                    lambda e: _suggest_output_dir(e.value)
                )
                # İlk render'da default mode'a göre öneri (default rename → no-op)
                _suggest_output_dir(mode_select.value)

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
                # Copy/move modunda yeni output klasörü pipeline'a "alternatif dataset"
                # olarak sunulur — banner üzerinden kullanıcı isterse switch eder.
                if mode in ("copy", "move") and output_input.value:
                    STATE.register_output(0, output_input.value)
                else:
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
                        # Undo başarılı → organize output (varsa) artık geçersiz
                        STATE.clear_output(0)
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


def _aspect_label(width: int, height: int) -> str:
    """Aspect ratio etiketi — yaygın oranlara match (16:9, 4:3, 3:4, 1:1...)
    veya decimal fallback (örn. 1.42).

    Aynı grupta farklı aspect'ler varsa kullanıcı görsel olarak crop/pad/
    upscale şüphesi yapabilir."""
    if not (width and height):
        return ""
    ratio = width / height
    presets = [
        ((16, 9), "16:9"),
        ((9, 16), "9:16"),
        ((4, 3), "4:3"),
        ((3, 4), "3:4"),
        ((3, 2), "3:2"),
        ((2, 3), "2:3"),
        ((1, 1), "1:1"),
        ((5, 4), "5:4"),
        ((4, 5), "4:5"),
        ((21, 9), "21:9"),
        ((9, 21), "9:21"),
        ((2, 1), "2:1"),
        ((1, 2), "1:2"),
    ]
    for (a, b), label in presets:
        target = a / b
        if abs(ratio - target) / target < 0.02:  # %2 tolerans
            return label
    return f"{ratio:.2f}:1"


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

                            # Resolution + aspect + size + (similar mode'da distance)
                            sz = f.get("size_bytes", 0)
                            w, h = f.get("width", 0), f.get("height", 0)
                            info_parts = []
                            if w and h:
                                aspect = _aspect_label(w, h)
                                info_parts.append(f"{w}×{h} ({aspect})")
                            info_parts.append(dedup_humanize_bytes(sz))
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
                            info_parts.append(f"{w}×{h} ({_aspect_label(w, h)})")
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


def build_quality_tab():
    """03 — Quality: 4 metric (blur/brightness/contrast/bpp) + composite scan
    + action (move/delete) + undo. Validator pattern'i form-only."""
    with ui.column().classes("w-full max-w-screen-xl mx-auto p-6 gap-4"):
        ui.label("03 — Quality").classes("text-2xl font-semibold")
        ui.label(
            "4 quality metric ile composite kontrol — blur (Laplacian), "
            "brightness (mean px), contrast (stddev), BPP (bytes/pixel). "
            "Düşük-quality dosyaları rapor / move / delete."
        ).classes("text-sm text-slate-600")

        with ui.grid(columns="1fr 1fr").classes("w-full gap-6 mt-2"):
            # ----- Sol kolon: form -----
            with ui.card().classes("w-full"):
                ui.label("Configuration").classes(
                    "text-sm uppercase text-slate-500 tracking-wide"
                )

                recursive_check = ui.checkbox("Recursive — alt klasörler", value=True)

                # Hangi check'ler çalışsın
                ui.label("Aktif kontroller").classes(
                    "text-xs uppercase text-slate-500 tracking-wide mt-2"
                )
                with ui.row().classes("gap-3"):
                    blur_check = ui.checkbox("Blur", value=True)
                    bright_check = ui.checkbox("Brightness", value=True)
                    contrast_check = ui.checkbox("Contrast", value=True)
                    bpp_check = ui.checkbox("BPP", value=True)

                action_select = ui.select(
                    {
                        "none": "Sadece raporla (default)",
                        "move": "/rejected'a taşı (undoable)",
                        "delete": "Sil (irreversible)",
                    },
                    label="Düşük-quality için aksiyon",
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

                # Threshold ayarları
                with ui.expansion("Threshold ayarları (advanced)", icon="tune").classes(
                    "w-full mt-2"
                ):
                    with ui.column().classes("w-full gap-2 p-2"):
                        ui.label("Blur (Laplacian variance — düşük=bulanık)").classes(
                            "text-xs text-slate-500"
                        )
                        blur_threshold = ui.number(
                            "Min blur score", value=100, min=0, step=10,
                        ).props("dense outlined")

                        ui.label("Brightness (mean pixel 0-255)").classes(
                            "text-xs text-slate-500 mt-2"
                        )
                        with ui.grid(columns="1fr 1fr").classes("w-full gap-3"):
                            min_brightness = ui.number(
                                "Min", value=30, min=0, max=255, step=5,
                            ).props("dense outlined")
                            max_brightness = ui.number(
                                "Max", value=225, min=0, max=255, step=5,
                            ).props("dense outlined")

                        ui.label("Contrast (stddev — düşük=düz)").classes(
                            "text-xs text-slate-500 mt-2"
                        )
                        contrast_threshold = ui.number(
                            "Min contrast", value=15, min=0, step=1,
                        ).props("dense outlined")

                        ui.label("BPP (bytes/pixel — düşük=aşırı sıkıştırma)").classes(
                            "text-xs text-slate-500 mt-2"
                        )
                        min_bpp = ui.number(
                            "Min BPP", value=0.1, min=0, step=0.05, format="%.3f",
                        ).props("dense outlined")

                with ui.row().classes("gap-2 mt-3 w-full items-center"):
                    run_btn = ui.button("Run quality check").props(
                        "color=primary no-caps"
                    )
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
                    "quality_report.json yolu",
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
                    "Henüz quality check çalıştırılmadı."
                ).classes("text-sm text-slate-600 italic mt-1")

                with ui.row().classes("w-full justify-around mt-2"):
                    with ui.column().classes("items-center gap-0"):
                        total_card = ui.label("—").classes(
                            "text-3xl font-bold text-slate-700"
                        )
                        ui.label("Total").classes(
                            "text-xs uppercase text-slate-500"
                        )
                    with ui.column().classes("items-center gap-0"):
                        valid_card = ui.label("—").classes(
                            "text-3xl font-bold text-green-600"
                        )
                        ui.label("Valid").classes(
                            "text-xs uppercase text-slate-500"
                        )
                    with ui.column().classes("items-center gap-0"):
                        invalid_card = ui.label("—").classes(
                            "text-3xl font-bold text-red-600"
                        )
                        ui.label("Invalid").classes(
                            "text-xs uppercase text-slate-500"
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
                        {"name": "blur", "label": "Blur", "field": "blur", "align": "right", "sortable": True},
                        {"name": "bright", "label": "Bright", "field": "bright", "align": "right", "sortable": True},
                        {"name": "contrast", "label": "Contrast", "field": "contrast", "align": "right", "sortable": True},
                        {"name": "bpp", "label": "BPP", "field": "bpp", "align": "right", "sortable": True},
                        {"name": "bpp_color", "label": "Kalite", "field": "bpp_color", "align": "left"},
                    ],
                    rows=[],
                    pagination=10,
                ).classes("w-full mt-1")

        # ------ Action handlers ------

        def _build_config() -> dict:
            return {
                "quality": {
                    "blur_threshold": float(blur_threshold.value or 100),
                    "brightness": {
                        "min": float(min_brightness.value or 30),
                        "max": float(max_brightness.value or 225),
                    },
                    "contrast_threshold": float(contrast_threshold.value or 15),
                    "bpp": {"min": float(min_bpp.value or 0.1)},
                },
            }

        def _enabled_checks() -> list[str]:
            checks = []
            if blur_check.value:
                checks.append("blur")
            if bright_check.value:
                checks.append("brightness")
            if contrast_check.value:
                checks.append("contrast")
            if bpp_check.value:
                checks.append("bpp")
            return checks or ["all"]

        def _validate_inputs() -> Optional[str]:
            if not STATE.is_valid_dataset():
                return "Dataset yolu geçerli değil (header'da doğrula)"
            if action_select.value == "move" and not invalid_dir_input.value:
                return "Move için Invalid dir gerekli"
            if not _enabled_checks():
                return "En az bir check seçili olmalı"
            return None

        def _on_action_change(value: str):
            if value == "move" and not invalid_dir_input.value and STATE.dataset_path:
                invalid_dir_input.value = str(Path(STATE.dataset_path) / "quality_rejected")
                invalid_dir_input.update()
        action_select.on_value_change(lambda e: _on_action_change(e.value))

        def _fmt(v):
            if v is None:
                return "—"
            try:
                return f"{float(v):.2f}"
            except (TypeError, ValueError):
                return str(v)

        def _q_extract_subdir(abs_path: str) -> str:
            """v1.1+ regression: r['path'] absolute → dataset relative subdir."""
            if not abs_path or not STATE.dataset_path:
                return "—"
            try:
                rel = Path(abs_path).relative_to(Path(STATE.dataset_path).resolve())
                parent = str(rel.parent)
                return "—" if parent == "." else parent
            except (ValueError, OSError):
                return "—"

        def _q_bpp_indicator(r: dict) -> str:
            """BPP renk-aware kısa etiket (kalite kolonu için)."""
            bpp = r.get("bpp_score")
            if bpp is None:
                return "—"
            try:
                bpp_v = float(bpp)
            except (TypeError, ValueError):
                return "—"
            if bpp_v < 0.05:
                return "🔴 DQ"
            if bpp_v < 0.5:
                return "🟡 düşük"
            return "🟢 OK"

        def _maybe_warn_full_rejection(sr):
            """Threshold çok sıkıysa kullanıcıyı uyar (validator pattern'i)."""
            if sr.total_scanned > 0 and sr.invalid_count == sr.total_scanned:
                ui.notify(
                    "⚠ %100 reddedildi — threshold'larınız çok sıkı olabilir. "
                    "Threshold ayarlarını gevşetip tekrar deneyin.",
                    type="warning", timeout=8000,
                )

        def _populate_results(sr, action_msg: str = ""):
            total_card.set_text(str(sr.total_scanned))
            valid_card.set_text(str(sr.valid_count))
            invalid_card.set_text(str(sr.invalid_count))

            reasons_panel.clear()
            with reasons_panel:
                if not sr.reasons:
                    ui.label("(düşük-quality bulunamadı)").classes(
                        "text-xs text-slate-500 italic"
                    )
                else:
                    total_inv = max(sr.invalid_count, 1)
                    for reason, count in sorted(sr.reasons.items(), key=lambda x: -x[1]):
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

            invalid_table.rows = [
                {
                    "filename": r.get("filename", ""),
                    "subdir": _q_extract_subdir(r.get("path", "")),
                    "reason": r.get("reason", ""),
                    "blur": _fmt(r.get("blur_score")),
                    "bright": _fmt(r.get("brightness_score")),
                    "contrast": _fmt(r.get("contrast_score")),
                    "bpp": _fmt(r.get("bpp_score")),
                    "bpp_color": _q_bpp_indicator(r),
                }
                for r in sr.results if not r.get("valid")
            ]
            invalid_table.update()

            verb = "Quality check tamam"
            summary_label.set_text(
                f"{verb}: {sr.valid_count}/{sr.total_scanned} valid"
                + (f"\n{action_msg}" if action_msg else "")
            )

        async def on_run():
            err = _validate_inputs()
            if err:
                ui.notify(err, type="negative")
                return

            run_btn.disable()
            progress_bar.visible = True
            progress_bar.set_value(0)
            progress_label.set_text("Tarama…")

            try:
                config = _build_config()
                checks = _enabled_checks()

                # Progress callback — scanner'dan UI'a güncelleme
                def _cb(current: int, total: int, msg: str):
                    if total > 0:
                        progress_bar.set_value(current / total)
                    progress_label.set_text(msg)

                await asyncio.sleep(0)
                # asyncio.to_thread ile non-blocking — UI thread serbest kalır,
                # büyük dataset'te (10k+ dosya) responsive
                sr = await asyncio.to_thread(
                    find_quality_issues,
                    STATE.dataset_path,
                    config=config,
                    checks=checks,
                    recursive=recursive_check.value,
                    progress_cb=_cb,
                )

                if sr.total_scanned == 0:
                    ui.notify("Hiç dosya bulunamadı", type="warning")
                    return

                action = action_select.value
                if action == "delete" and not dryrun_check.value and not yes_check.value:
                    _confirm_delete_dialog(
                        sr.invalid_count,
                        on_confirm=lambda: _execute_action(sr, action),
                    )
                    _maybe_warn_full_rejection(sr)
                    return
                _execute_action(sr, action)
                _maybe_warn_full_rejection(sr)

            except Exception as e:
                ui.notify(f"Quality check hatası: {e}", type="negative")
            finally:
                progress_bar.visible = False
                progress_label.set_text("")
                run_btn.enable()

        def _confirm_delete_dialog(count: int, *, on_confirm):
            with ui.dialog() as dlg, ui.card().classes("w-[500px]"):
                ui.label("⚠ Kalıcı silme onayı").classes("text-lg font-semibold")
                ui.label(
                    f"{count} düşük-quality dosya KALICI olarak silinecek. "
                    "Geri alınamaz. Önce 'Move' ile dene."
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

        def _execute_action(sr, action: str):
            try:
                ar = quality_apply_action(
                    sr.results,
                    source_root=STATE.dataset_path,
                    action=action,
                    invalid_dir=invalid_dir_input.value or None,
                    dry_run=dryrun_check.value,
                )
                if action == "move" and invalid_dir_input.value:
                    report_path = Path(invalid_dir_input.value) / QUALITY_REPORT_NAME
                else:
                    report_path = Path(STATE.dataset_path) / QUALITY_REPORT_NAME

                quality_write_report(
                    report_path,
                    scan_result=sr,
                    action_result=ar,
                    recursive=recursive_check.value,
                    config={
                        "checks": _enabled_checks(),
                        "thresholds": _build_config()["quality"],
                    },
                )
                undo_input.set_value(str(report_path))
                STATE.last_report_paths[3] = str(report_path)

                dryrun_tag = " (DRY-RUN)" if dryrun_check.value else ""
                if action == "move":
                    msg = f"Taşınan: {len(ar.entries)}{dryrun_tag} → {ar.invalid_dir}"
                elif action == "delete":
                    msg = f"Silinen: {len(ar.entries)}{dryrun_tag}"
                else:
                    msg = f"Sadece raporlandı: {sr.invalid_count} düşük-quality"

                _populate_results(sr, action_msg=f"{msg}\nRapor: {report_path}")
                ui.notify(msg, type="positive" if not dryrun_check.value else "info")
                STATE.notify_change()
            except Exception as e:
                ui.notify(f"Aksiyon hatası: {e}", type="negative")

        run_btn.on("click", on_run)

        def _run_undo(dry_run: bool):
            report = undo_input.value or STATE.last_report_paths.get(3)
            if not report:
                ui.notify("Undo için rapor yolu girin", type="negative")
                return
            if not Path(report).exists():
                ui.notify(f"Rapor yok: {report}", type="negative")
                return
            try:
                summary = quality_undo_from_report(report, dry_run=dry_run)
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


def build_watermark_tab():
    """04 — Watermark: YOLOv8 detect + invalid-action (move/delete) + undo.
    Form-only: kullanıcı model/confidence ayarlar, invalid-action seçer."""
    with ui.column().classes("w-full max-w-screen-xl mx-auto p-6 gap-4"):
        ui.label("04 — Watermark").classes("text-2xl font-semibold")
        ui.label(
            "YOLOv8 ile watermark tespit. Watermark'lı dosyaları rapor / "
            "move (tree-preserving) / delete. Inpainting yok — scope-out."
        ).classes("text-sm text-slate-600")

        with ui.grid(columns="1fr 1fr").classes("w-full gap-6 mt-2"):
            # Sol: form
            with ui.card().classes("w-full"):
                ui.label("Configuration").classes(
                    "text-sm uppercase text-slate-500 tracking-wide"
                )

                with ui.row().classes("w-full items-center gap-1 no-wrap"):
                    input_dir_input = ui.input(
                        "Dataset klasörü",
                        value=STATE.dataset_path or "",
                    ).props("dense outlined").classes("flex-grow")
                    ui.button(
                        icon="folder_open",
                        on_click=lambda: _open_browse_dialog(
                            input_dir_input, title="Dataset klasörü seç"
                        ),
                    ).props("flat dense color=grey-7").tooltip("Browse")

                recursive_check = ui.checkbox(
                    "Recursive — alt klasörler", value=True
                )

                model_input = ui.input(
                    "YOLO model path", value=WATERMARK_DEFAULT_MODEL_PATH,
                ).props("dense outlined").classes("w-full")

                confidence_input = ui.number(
                    "Confidence eşiği",
                    value=WATERMARK_DEFAULT_CONFIDENCE,
                    min=0.0, max=1.0, step=0.05, format="%.2f",
                ).props("dense outlined").classes("w-full")

                action_select = ui.select(
                    {
                        "none": "Sadece raporla (default)",
                        "move": "/rejected'a taşı (undoable, tree-preserve)",
                        "delete": "Sil (irreversible)",
                    },
                    label="Watermark'lı için aksiyon",
                    value="none",
                ).props("dense outlined").classes("w-full")

                with ui.row().classes("w-full items-center gap-1 no-wrap"):
                    invalid_dir_input = ui.input(
                        "Rejected klasörü",
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
                    run_btn = ui.button("Watermark scan").props(
                        "color=primary no-caps"
                    )
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
                    "watermark_report.json yolu",
                    placeholder="(move sonrası otomatik dolar)",
                ).props("dense outlined").classes("w-full")
                undo_btn = ui.button("Undo").props(
                    "outline color=grey-7 no-caps"
                )

            # Sağ: sonuç
            with ui.card().classes("w-full"):
                ui.label("Sonuç").classes(
                    "text-sm uppercase text-slate-500 tracking-wide"
                )
                summary_label = ui.label(
                    "Henüz scan çalıştırılmadı."
                ).classes("text-sm text-slate-600 italic mt-1")
                with ui.row().classes("w-full justify-around mt-2"):
                    with ui.column().classes("items-center gap-0"):
                        total_card = ui.label("—").classes(
                            "text-3xl font-bold text-slate-700"
                        )
                        ui.label("Total").classes(
                            "text-xs uppercase text-slate-500"
                        )
                    with ui.column().classes("items-center gap-0"):
                        clean_card = ui.label("—").classes(
                            "text-3xl font-bold text-green-600"
                        )
                        ui.label("Temiz").classes(
                            "text-xs uppercase text-slate-500"
                        )
                    with ui.column().classes("items-center gap-0"):
                        wm_card = ui.label("—").classes(
                            "text-3xl font-bold text-red-600"
                        )
                        ui.label("Watermark'lı").classes(
                            "text-xs uppercase text-slate-500"
                        )

                ui.separator().classes("my-2")
                wm_table = ui.table(
                    columns=[
                        {"name": "filename", "label": "Dosya", "field": "filename", "align": "left", "sortable": True},
                        {"name": "subdir", "label": "Subdir", "field": "subdir", "align": "left", "sortable": True},
                        {"name": "count", "label": "Det", "field": "count", "align": "right", "sortable": True},
                        {"name": "max_conf", "label": "Max conf", "field": "max_conf", "align": "right", "sortable": True},
                    ],
                    rows=[],
                    pagination=10,
                ).classes("w-full mt-1")

        def _do_run():
            d = (input_dir_input.value or "").strip()
            if not d:
                ui.notify("Dataset klasörü gerekli", type="warning")
                return
            input_dir = Path(d)
            if not input_dir.is_dir():
                ui.notify(f"Geçerli dizin değil: {input_dir}", type="negative")
                return

            action = action_select.value
            invalid_dir = (invalid_dir_input.value or "").strip()
            if action == "move" and not invalid_dir:
                ui.notify("Move için rejected klasörü gerekli", type="warning")
                return

            run_btn.disable()
            progress_bar.visible = True
            progress_label.text = "YOLO inference başladı..."

            def _progress_cb(current: int, total: int, msg: str):
                if total > 0:
                    progress_bar.value = current / total
                progress_label.text = f"{msg} ({current}/{total})"

            try:
                sr = find_watermarks(
                    input_dir,
                    model_path=model_input.value,
                    confidence=float(confidence_input.value or 0.25),
                    recursive=bool(recursive_check.value),
                    progress_cb=_progress_cb,
                )
            except FileNotFoundError as e:
                progress_bar.visible = False
                run_btn.enable()
                progress_label.text = f"Hata: {e}"
                ui.notify(f"Model bulunamadı: {e}", type="negative")
                return
            except RuntimeError as e:
                progress_bar.visible = False
                run_btn.enable()
                progress_label.text = f"Hata: {e}"
                ui.notify(f"Inference hatası: {e}", type="negative")
                return

            ar = watermark_apply_action(
                sr.results,
                source_root=input_dir,
                action=action,
                invalid_dir=invalid_dir or None,
                dry_run=bool(dryrun_check.value),
            )

            # Rapor yolu çözümle
            if action == "move" and invalid_dir:
                report_path = Path(invalid_dir) / WATERMARK_REPORT_NAME
            else:
                report_path = input_dir / WATERMARK_REPORT_NAME
            try:
                watermark_write_report(
                    report_path,
                    scan_result=sr, action_result=ar,
                    recursive=bool(recursive_check.value),
                )
            except Exception as e:  # noqa: BLE001
                ui.notify(f"Rapor yazma hatası: {e}", type="negative")

            progress_bar.visible = False
            run_btn.enable()
            mode = " (DRY-RUN)" if dryrun_check.value else ""
            summary_label.text = (
                f"Total: {sr.total_scanned}, Watermark: {sr.invalid_count}, "
                f"Action: {ar.action}{mode}"
            )
            total_card.text = str(sr.total_scanned)
            clean_card.text = str(sr.valid_count)
            wm_card.text = str(sr.invalid_count)

            # Invalid table
            rows = []
            for r in sr.results:
                if r.get("valid"):
                    continue
                p = Path(r.get("path") or r.get("filename", ""))
                try:
                    subdir = str(p.parent.relative_to(input_dir.resolve()))
                except (ValueError, OSError):
                    subdir = str(p.parent.name)
                dets = r.get("detections") or []
                max_conf = (
                    max((d.get("confidence", 0) for d in dets), default=0.0)
                    if dets else 0.0
                )
                rows.append({
                    "filename": p.name,
                    "subdir": subdir if subdir != "." else "—",
                    "count": r.get("detection_count", 0),
                    "max_conf": f"{max_conf:.2f}" if max_conf else "—",
                })
            wm_table.rows = rows

            STATE.last_report_paths[4] = str(report_path)
            undo_input.value = str(report_path)
            ui.notify(
                f"Watermark scan: {sr.invalid_count}/{sr.total_scanned} watermark'lı{mode}",
                type="positive",
            )
            STATE.notify_change()

        def _do_undo():
            rp = (undo_input.value or "").strip()
            if not rp:
                ui.notify("Rapor yolu gerekli", type="warning")
                return
            try:
                summary = watermark_undo_from_report(Path(rp), dry_run=False)
            except Exception as e:  # noqa: BLE001
                ui.notify(f"Undo hatası: {e}", type="negative")
                return
            ui.notify(
                f"Undo: restored={summary['restored']} skipped={summary['skipped']}",
                type="positive",
            )
            STATE.notify_change()

        run_btn.on("click", _do_run)
        undo_btn.on("click", _do_undo)


def build_resize_tab():
    """05 — Resize: Lanczos batch resize (copy/in-place) + undo (copy mode)."""
    with ui.column().classes("w-full max-w-screen-xl mx-auto p-6 gap-4"):
        ui.label("05 — Resize").classes("text-2xl font-semibold")
        ui.label(
            "Lanczos algoritmasıyla aspect-preserving toplu resize. "
            "Copy mode (orijinal korunur) veya in-place (orijinal kaybolur)."
        ).classes("text-sm text-slate-600")

        with ui.grid(columns="1fr 1fr").classes("w-full gap-6 mt-2"):
            with ui.card().classes("w-full"):
                ui.label("Configuration").classes(
                    "text-sm uppercase text-slate-500 tracking-wide"
                )

                with ui.row().classes("w-full items-center gap-1 no-wrap"):
                    input_dir_input = ui.input(
                        "Source dataset",
                        value=STATE.dataset_path or "",
                    ).props("dense outlined").classes("flex-grow")
                    ui.button(
                        icon="folder_open",
                        on_click=lambda: _open_browse_dialog(
                            input_dir_input, title="Source seç"
                        ),
                    ).props("flat dense color=grey-7").tooltip("Browse")
                _wire_latest_output_link(input_dir_input)

                mode_select = ui.select(
                    {
                        "copy": "Copy — orijinal korunur, output'a yazılır (default)",
                        "in-place": "In-place — orijinal kaybolur (UNDO YOK)",
                    },
                    label="Mode",
                    value="copy",
                ).props("dense outlined").classes("w-full")

                with ui.row().classes("w-full items-center gap-1 no-wrap") as out_row:
                    out_input = ui.input(
                        "Output (copy mode için)",
                        placeholder="copy mode için zorunlu",
                    ).props("dense outlined").classes("flex-grow")
                    ui.button(
                        icon="folder_open",
                        on_click=lambda: _open_browse_dialog(
                            out_input, title="Output seç"
                        ),
                    ).props("flat dense color=grey-7").tooltip("Browse")

                def _toggle_out(val: str):
                    out_row.visible = (val == "copy")
                mode_select.on_value_change(lambda e: _toggle_out(e.value))

                recursive_check = ui.checkbox("Recursive", value=True)

                with ui.row().classes("w-full gap-3"):
                    max_w_input = ui.number(
                        "Max width", value=1024, min=64, step=64,
                    ).props("dense outlined").classes("flex-grow")
                    max_h_input = ui.number(
                        "Max height", value=1024, min=64, step=64,
                    ).props("dense outlined").classes("flex-grow")

                quality_input = ui.number(
                    "JPEG quality", value=95, min=60, max=100, step=1,
                ).props("dense outlined").classes("w-full")

                dryrun_check = ui.checkbox("Dry-run", value=False)

                with ui.row().classes("gap-2 mt-3 w-full items-center"):
                    run_btn = ui.button("Resize").props("color=primary no-caps")
                progress_label = ui.label("").classes("text-xs text-slate-600")
                progress_bar = ui.linear_progress(
                    value=0, show_value=False
                ).classes("w-full")
                progress_bar.visible = False

                ui.separator().classes("my-3")
                ui.label("Undo (sadece copy mode)").classes(
                    "text-sm uppercase text-slate-500 tracking-wide"
                )
                undo_input = ui.input(
                    "resize_report.json yolu",
                    placeholder="(run sonrası otomatik dolar)",
                ).props("dense outlined").classes("w-full")
                undo_btn = ui.button("Undo").props(
                    "outline color=grey-7 no-caps"
                )

            # Sağ: sonuç
            with ui.card().classes("w-full"):
                ui.label("Sonuç").classes(
                    "text-sm uppercase text-slate-500 tracking-wide"
                )
                summary_label = ui.label(
                    "Henüz resize çalıştırılmadı."
                ).classes("text-sm text-slate-600 italic mt-1")
                with ui.row().classes("w-full justify-around mt-2"):
                    with ui.column().classes("items-center gap-0"):
                        total_card = ui.label("—").classes(
                            "text-3xl font-bold text-slate-700"
                        )
                        ui.label("Total").classes(
                            "text-xs uppercase text-slate-500"
                        )
                    with ui.column().classes("items-center gap-0"):
                        resized_card = ui.label("—").classes(
                            "text-3xl font-bold text-blue-600"
                        )
                        ui.label("Resized").classes(
                            "text-xs uppercase text-slate-500"
                        )
                    with ui.column().classes("items-center gap-0"):
                        skipped_card = ui.label("—").classes(
                            "text-3xl font-bold text-slate-400"
                        )
                        ui.label("Skipped").classes(
                            "text-xs uppercase text-slate-500"
                        )

        def _do_run():
            d = (input_dir_input.value or "").strip()
            if not d:
                ui.notify("Source gerekli", type="warning")
                return
            input_dir = Path(d)
            if not input_dir.is_dir():
                ui.notify(f"Geçerli dizin değil: {input_dir}", type="negative")
                return

            mode = mode_select.value
            out_dir = (out_input.value or "").strip()
            if mode == "copy" and not out_dir:
                ui.notify("Copy mode için Output gerekli", type="warning")
                return

            run_btn.disable()
            progress_bar.visible = True
            progress_label.text = "Resize başladı..."

            def _progress_cb(current: int, total: int, msg: str):
                if total > 0:
                    progress_bar.value = current / total
                progress_label.text = f"{msg} ({current}/{total})"

            try:
                sr = resize_dataset(
                    input_dir,
                    max_size=(int(max_w_input.value or 1024),
                              int(max_h_input.value or 1024)),
                    mode=mode,
                    output_dir=out_dir if mode == "copy" else None,
                    quality=int(quality_input.value or 95),
                    recursive=bool(recursive_check.value),
                    dry_run=bool(dryrun_check.value),
                    progress_cb=_progress_cb,
                )
            except Exception as e:  # noqa: BLE001
                progress_bar.visible = False
                run_btn.enable()
                progress_label.text = f"Hata: {e}"
                ui.notify(f"Resize hatası: {e}", type="negative")
                return

            # Rapor
            default_dir = Path(out_dir) if out_dir else input_dir
            report_path = default_dir / RESIZE_REPORT_NAME
            try:
                resize_write_report(
                    report_path,
                    scan_result=sr,
                    recursive=bool(recursive_check.value),
                    dry_run=bool(dryrun_check.value),
                )
            except Exception as e:  # noqa: BLE001
                ui.notify(f"Rapor yazma hatası: {e}", type="negative")

            progress_bar.visible = False
            run_btn.enable()
            mode_lbl = " (DRY-RUN)" if dryrun_check.value else ""
            summary_label.text = (
                f"Total: {sr.total_scanned}, Resized: {sr.resized_count}, "
                f"Skipped: {sr.skipped_count}, Errors: {sr.error_count}{mode_lbl}"
            )
            total_card.text = str(sr.total_scanned)
            resized_card.text = str(sr.resized_count)
            skipped_card.text = str(sr.skipped_count)

            STATE.last_report_paths[5] = str(report_path)
            undo_input.value = str(report_path)
            ui.notify(
                f"Resize: {sr.resized_count}/{sr.total_scanned} işlendi{mode_lbl}",
                type="positive",
            )
            # Copy modunda + gerçek run'da yeni klasör pipeline'a alternatif olarak
            # sunulur. Dry-run'da gerçek dosya yok → register etme.
            if mode == "copy" and out_dir and not dryrun_check.value:
                STATE.register_output(5, out_dir)

        def _do_undo():
            rp = (undo_input.value or "").strip()
            if not rp:
                ui.notify("Rapor yolu gerekli", type="warning")
                return
            try:
                summary = resize_undo_from_report(Path(rp), dry_run=False)
            except Exception as e:  # noqa: BLE001
                ui.notify(f"Undo hatası: {e}", type="negative")
                return
            ui.notify(
                f"Undo: removed={summary['removed']} skipped={summary['skipped']}",
                type="positive",
            )
            # Undo başarılı → resize output artık geçersiz, banner'dan temizle
            STATE.clear_output(5)

        run_btn.on("click", _do_run)
        undo_btn.on("click", _do_undo)


def build_caption_tab():
    """06 — Caption: Qwen3-VL multi-pass captioning + insan onayı (review).

    Flow:
      1. Form: dataset path, model/server/workers, pass selector, character, ...
      2. Run: batch_client.process_folder threaded → caption JSON'lar yazılır
      3. Refresh gallery: img + medium caption preview (görsel klikleyince editor)
      4. Editor dialog: short/medium/long edit + structured 5-pass tabs + Save
      5. Export: JSON → TXT (caption_type seçilebilir)
    """
    import json
    import threading

    tab_state: dict = {
        "thread": None,        # captioning arka plan thread
        "cancelled": False,
        "current_assets": [],  # [(img_path, caption_dict), ...]
    }

    with ui.column().classes("w-full max-w-screen-2xl mx-auto p-6 gap-4"):
        ui.label("06 — Caption").classes("text-2xl font-semibold")
        ui.label(
            "Qwen3-VL multi-pass (5-pass) caption üretimi + insan onayı. "
            "Tool batch_client'i Ollama HTTP backend'i ile çağırır; her pass "
            "sonrası JSON birleştirilir. Gallery'den her görselin caption'ını "
            "edit edebilirsin (AI etiketli veriyi training'e almadan ÖNCE)."
        ).classes("text-sm text-slate-600")

        with ui.grid(columns="380px 1fr").classes("w-full gap-6 mt-2"):
            # ---------- Sol: Configuration ----------
            with ui.card().classes("w-full"):
                ui.label("Configuration").classes(
                    "text-sm uppercase text-slate-500 tracking-wide"
                )

                with ui.row().classes("w-full items-center gap-1 no-wrap"):
                    input_dir_input = ui.input(
                        "Dataset klasörü",
                        value=STATE.dataset_path or "",
                        placeholder="/path/to/images",
                    ).props("dense outlined").classes("flex-grow")
                    ui.button(
                        icon="folder_open",
                        on_click=lambda: _open_browse_dialog(
                            input_dir_input, title="Dataset klasörü seç"
                        ),
                    ).props("flat dense color=grey-7").tooltip("Browse")
                _wire_latest_output_link(input_dir_input)

                # Backend / connection
                model_input = ui.input(
                    "Model", value="huihui_ai/qwen3-vl-abliterated:30b-a3b-instruct",
                ).props("dense outlined").classes("w-full")
                server_input = ui.input(
                    "Server URL", value="http://localhost:11434",
                ).props("dense outlined").classes("w-full")

                with ui.row().classes("w-full gap-3"):
                    workers_input = ui.number(
                        "Workers", value=4, min=1, step=1,
                    ).props("dense outlined").classes("flex-grow")
                    max_tokens_input = ui.number(
                        "Max tokens", value=1024, min=128, step=128,
                    ).props("dense outlined").classes("flex-grow")

                pass_select = ui.select(
                    {
                        "all": "Tümü (5 pass)",
                        "1": "1 — Face",
                        "2": "2 — Body / Pose",
                        "3": "3 — Clothing",
                        "4": "4 — Scene / Camera",
                        "5": "5 — Captioning",
                    },
                    label="Pass",
                    value="all",
                ).props("dense outlined").classes("w-full")

                character_input = ui.input(
                    "Character (prompt değişkeni)", value="woman",
                ).props("dense outlined").classes("w-full")

                with ui.row().classes("gap-3 mt-1"):
                    overwrite_check = ui.checkbox("Overwrite", value=False)
                    merge_only_check = ui.checkbox(
                        "Merge only", value=False
                    ).tooltip("Yeni pass yapmadan mevcut pass JSON'larını birleştir")

                ui.separator().classes("my-2")
                ui.label("Export").classes(
                    "text-xs uppercase text-slate-500 tracking-wide"
                )
                caption_type_select = ui.select(
                    {"short": "Short", "medium": "Medium", "long": "Long"},
                    label="Export caption tipi",
                    value="medium",
                ).props("dense outlined").classes("w-full")

                # Action buttons
                with ui.row().classes("gap-2 mt-3 w-full items-center"):
                    health_btn = ui.button("Health check").props(
                        "outline color=grey-7 no-caps"
                    )
                    run_btn = ui.button("Caption + Export").props(
                        "color=primary no-caps"
                    )
                    export_btn = ui.button("Sadece export").props(
                        "outline color=positive no-caps"
                    )
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
                    "caption_report.json yolu",
                    placeholder="(run sonrası otomatik dolar)",
                ).props("dense outlined").classes("w-full")
                undo_btn = ui.button("Undo").props(
                    "outline color=grey-7 no-caps"
                )

            # ---------- Sağ: Gallery + Editor ----------
            with ui.card().classes("w-full"):
                with ui.row().classes("w-full items-center justify-between"):
                    summary_label = ui.label(
                        "Henüz caption üretilmedi."
                    ).classes("text-sm text-slate-600 italic")
                    refresh_btn = ui.button(
                        "Yenile", icon="refresh"
                    ).props("flat dense color=grey-7 no-caps")

                gallery_grid = ui.grid(columns=4).classes("w-full gap-3 mt-2")

        # ============= Helpers =============

        def _input_dir() -> Optional[Path]:
            v = (input_dir_input.value or "").strip()
            if not v:
                return None
            p = Path(v)
            return p if p.is_dir() else None

        def _scan_caption_assets() -> list[tuple[Path, dict]]:
            """Input dir'da görsel + yan-yana caption JSON çiftlerini topla."""
            d = _input_dir()
            if not d:
                return []
            assets: list[tuple[Path, dict]] = []
            for ext in CAPTION_SUPPORTED_EXTENSIONS:
                for img in d.glob(f"*{ext}"):
                    cap_path = img.with_suffix(".json")
                    if not cap_path.is_file():
                        continue
                    try:
                        cap_data = json.loads(cap_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        cap_data = {}
                    # Sadece caption JSON'larını al (pass JSON'ları .face.json, .body.json, vb.)
                    # Final birleşik dosya .json (suffix yok). Filtre: 'captioning' veya 'face' anahtarı içermeli
                    if any(k in cap_data for k in ("captioning", "face", "body", "clothing", "scene")):
                        assets.append((img, cap_data))
            return sorted(assets, key=lambda x: x[0].name)

        def _refresh_gallery():
            assets = _scan_caption_assets()
            tab_state["current_assets"] = assets
            gallery_grid.clear()
            if not assets:
                with gallery_grid:
                    ui.label("Caption JSON'ı olan görsel yok.").classes(
                        "text-sm text-slate-500 italic col-span-4"
                    )
                summary_label.text = "Caption üretilmedi (gallery boş)."
                return
            summary_label.text = f"{len(assets)} caption'lı görsel"

            with gallery_grid:
                for img_path, cap in assets:
                    with ui.card().classes("p-2 cursor-pointer hover:shadow-lg") as card:
                        ui.image(_path_to_url(str(img_path))).classes(
                            "w-full h-40 object-cover rounded"
                        )
                        ui.label(img_path.name).classes(
                            "text-xs text-slate-700 truncate mt-1"
                        ).style("max-width: 100%")
                        med = (cap.get("captioning") or {}).get("medium") or "—"
                        ui.label(med).classes(
                            "text-xs text-slate-500 line-clamp-3"
                        ).style("max-width: 100%; min-height: 2.5rem;")
                        card.on("click", lambda _e, ip=img_path, c=cap: _open_editor(ip, c))

        def _open_editor(img_path: Path, cap: dict):
            """Caption editor — short/medium/long edit + 5-pass structured."""
            cap_path = img_path.with_suffix(".json")
            with ui.dialog() as dialog, ui.card().style(
                "max-width: 1200px; min-width: 900px; width: 90vw"
            ):
                with ui.row().classes("w-full gap-4 no-wrap"):
                    # Görsel
                    with ui.column().classes("w-1/2 gap-2"):
                        ui.image(_path_to_url(str(img_path))).classes(
                            "w-full max-h-96 object-contain rounded"
                        )
                        ui.label(img_path.name).classes("text-xs text-slate-500")

                    # Caption editor
                    with ui.column().classes("w-1/2 gap-2"):
                        ui.label("Captions (edit)").classes(
                            "text-sm uppercase text-slate-500 tracking-wide"
                        )
                        captioning = cap.get("captioning") or {}
                        short_input = ui.textarea(
                            "Short", value=captioning.get("short", "")
                        ).props("dense outlined autogrow").classes("w-full")
                        medium_input = ui.textarea(
                            "Medium", value=captioning.get("medium", "")
                        ).props("dense outlined autogrow").classes("w-full")
                        long_input = ui.textarea(
                            "Long", value=captioning.get("long", "")
                        ).props("dense outlined autogrow").classes("w-full")

                        with ui.expansion("5-pass structured (read-only)", icon="data_object").classes("w-full"):
                            with ui.column().classes("gap-2 text-xs"):
                                for key in ("face", "body", "clothing", "scene"):
                                    ui.label(key.upper()).classes(
                                        "text-xs uppercase text-slate-500"
                                    )
                                    ui.code(
                                        json.dumps(cap.get(key) or {}, indent=2, ensure_ascii=False)
                                    ).classes("text-xs w-full")

                        with ui.row().classes("gap-2 mt-2 w-full justify-end"):
                            ui.button("İptal", on_click=dialog.close).props(
                                "flat color=grey-7 no-caps"
                            )

                            def _save():
                                # Caption JSON'ı update et
                                new_cap = dict(cap)
                                new_cap["captioning"] = {
                                    "short": (short_input.value or "").strip(),
                                    "medium": (medium_input.value or "").strip(),
                                    "long": (long_input.value or "").strip(),
                                }
                                # approved işareti — gelecek pipeline adımları için
                                new_cap["_approved"] = True
                                try:
                                    cap_path.write_text(
                                        json.dumps(new_cap, indent=2, ensure_ascii=False),
                                        encoding="utf-8",
                                    )
                                except OSError as e:
                                    ui.notify(f"Save hatası: {e}", type="negative")
                                    return
                                ui.notify(
                                    f"Kaydedildi → {cap_path.name}", type="positive"
                                )
                                dialog.close()
                                _refresh_gallery()

                            ui.button("Kaydet & Onayla", on_click=_save).props(
                                "color=positive no-caps"
                            )
            dialog.open()

        # ============= Action handlers =============

        def _do_health_check():
            d = _input_dir()
            srv = (server_input.value or "").strip()
            if not srv:
                ui.notify("Server URL gerekli", type="warning")
                return
            try:
                ok = caption_check_server_health(srv, "ollama")
            except Exception as e:
                ui.notify(f"Health check hatası: {e}", type="negative")
                return
            if ok:
                ui.notify(f"✓ Server up: {srv}", type="positive")
            else:
                ui.notify(f"⚠ Server cevap vermiyor: {srv}", type="negative")

        async def _do_run(*, export_only: bool):
            d = _input_dir()
            if not d:
                ui.notify("Geçerli dataset klasörü seç", type="warning")
                return
            srv = (server_input.value or "").strip()
            mdl = (model_input.value or "").strip()
            ctype = caption_type_select.value
            workers = int(workers_input.value or 4)
            max_tokens = int(max_tokens_input.value or 1024)
            character = (character_input.value or "woman").strip()
            overwrite = bool(overwrite_check.value)
            merge_only = bool(merge_only_check.value)

            ps = pass_select.value
            pass_nums = [1, 2, 3, 4, 5] if ps == "all" else [int(ps)]

            run_btn.disable()
            export_btn.disable()
            progress_bar.visible = True
            progress_label.text = "Başlatılıyor..."

            # Long-running: background thread (NiceGUI'yi bloklamasın)
            error_holder: dict = {"err": None}

            def _worker():
                try:
                    if not export_only:
                        caption_batch_client.process_folder(
                            folder_path=str(d),
                            server_url=srv,
                            pass_nums=pass_nums,
                            model=mdl,
                            max_tokens=max_tokens,
                            max_workers=workers,
                            character_name=character,
                            overwrite=overwrite,
                            merge_only=merge_only,
                            backend="ollama",
                        )
                    # Export TXT
                    caption_extract_captions(str(d), ctype, overwrite=False)
                except Exception as e:  # noqa: BLE001
                    error_holder["err"] = str(e)

            t = threading.Thread(target=_worker, daemon=True)
            tab_state["thread"] = t
            t.start()

            # Periyodik progress refresh
            while t.is_alive():
                # input dir'da kaç JSON var
                try:
                    found = sum(1 for _ in d.glob("*.json"))
                except OSError:
                    found = 0
                progress_label.text = f"Caption üretiliyor… ({found} JSON yazıldı)"
                await asyncio.sleep(2)

            t.join()

            progress_bar.visible = False
            run_btn.enable()
            export_btn.enable()

            if error_holder["err"]:
                progress_label.text = f"Hata: {error_holder['err']}"
                ui.notify(f"Captioning hatası: {error_holder['err']}", type="negative")
                return

            progress_label.text = "✓ Tamam"
            # Rapor yolu otomatik undo'ya doldur
            STATE.last_report_paths[6] = str(d / "caption_report.json")
            undo_input.value = STATE.last_report_paths[6]
            ui.notify("Caption + export tamamlandı", type="positive")
            _refresh_gallery()

        def _do_undo():
            rp = (undo_input.value or "").strip()
            if not rp:
                ui.notify("Rapor yolu gerekli", type="warning")
                return
            rep_path = Path(rp)
            if not rep_path.is_file():
                ui.notify(f"Rapor bulunamadı: {rep_path}", type="negative")
                return
            try:
                rep = json.loads(rep_path.read_text(encoding="utf-8"))
                if rep.get("tool") != "media-captioner":
                    ui.notify(
                        f"Tool mismatch: {rep.get('tool')!r}", type="negative"
                    )
                    return
                removed = skipped = 0
                for entry in rep.get("actions", []):
                    for path_str in entry.get("created_files", []):
                        p = Path(path_str)
                        if p.exists():
                            try:
                                p.unlink()
                                removed += 1
                            except OSError:
                                skipped += 1
                        else:
                            skipped += 1
                ui.notify(
                    f"Undo: removed={removed} skipped={skipped}",
                    type="positive",
                )
                _refresh_gallery()
            except Exception as e:  # noqa: BLE001
                ui.notify(f"Undo hatası: {e}", type="negative")

        # Bind handlers
        health_btn.on("click", _do_health_check)
        run_btn.on("click", lambda: _do_run(export_only=False))
        export_btn.on("click", lambda: _do_run(export_only=True))
        refresh_btn.on("click", _refresh_gallery)
        undo_btn.on("click", _do_undo)

        # Tab açılınca / state değişince mevcut caption'ları göster
        STATE.on_change(_refresh_gallery)
        _refresh_gallery()


def build_golden_set_tab():
    """07 — Golden Set: quality+caption-aware cherry-pick form.

    Form: source dataset + quality_report + count + distribution +
    character + face-target + recursive + dry-run + force. Run sonucu:
    selection stats (avg score, face count, bucket dağılım) + apply
    sonucu (kaç kopyalandı). Tree-preserving copy (recursive aktifken).
    """
    import json

    tab_state: dict = {"last_selection": None}

    with ui.column().classes("w-full max-w-screen-xl mx-auto p-6 gap-4"):
        ui.label("07 — Golden Set").classes("text-2xl font-semibold")
        ui.label(
            "Quality skoru + caption JSON'lardan cherry-pick. Distribution "
            "dengeli olur (close-up/upper-body/full-body). Face-target ile "
            "min N face-visible asset garantilenir (swap)."
        ).classes("text-sm text-slate-600")

        with ui.grid(columns="380px 1fr").classes("w-full gap-6 mt-2"):
            # ---------- Sol: Configuration ----------
            with ui.card().classes("w-full"):
                ui.label("Configuration").classes(
                    "text-sm uppercase text-slate-500 tracking-wide"
                )

                with ui.row().classes("w-full items-center gap-1 no-wrap"):
                    src_input = ui.input(
                        "Source dataset",
                        value=STATE.dataset_path or "",
                    ).props("dense outlined").classes("flex-grow")
                    ui.button(
                        icon="folder_open",
                        on_click=lambda: _open_browse_dialog(
                            src_input, title="Source dataset seç"
                        ),
                    ).props("flat dense color=grey-7").tooltip("Browse")
                _wire_latest_output_link(src_input)

                with ui.row().classes("w-full items-center gap-1 no-wrap"):
                    out_input = ui.input(
                        "Hedef golden-set klasörü",
                    ).props("dense outlined").classes("flex-grow")
                    ui.button(
                        icon="folder_open",
                        on_click=lambda: _open_browse_dialog(
                            out_input, title="Golden-set hedefi seç"
                        ),
                    ).props("flat dense color=grey-7").tooltip("Browse")

                with ui.row().classes("w-full items-center gap-1 no-wrap"):
                    rep_input = ui.input(
                        "quality_report.json yolu",
                        placeholder="dataset/quality_report.json",
                    ).props("dense outlined").classes("flex-grow")

                count_input = ui.number(
                    "Count (toplam asset)", value=200, min=1, step=10,
                ).props("dense outlined").classes("w-full")

                distribution_input = ui.input(
                    "Distribution",
                    value="close-up:30,upper-body:30,full-body:40",
                ).props("dense outlined").classes("w-full")

                character_input = ui.input(
                    "Character (opsiyonel)",
                    placeholder="alpha / beta / boş",
                ).props("dense outlined").classes("w-full")

                face_target_input = ui.number(
                    "Face target (min N face-visible)",
                    value=0, min=0, step=10,
                ).props("dense outlined").classes("w-full")

                with ui.row().classes("gap-3 mt-1"):
                    recursive_check = ui.checkbox(
                        "Recursive (tree-preserve)", value=False
                    )
                    force_check = ui.checkbox("Force overwrite", value=False)
                    dryrun_check = ui.checkbox("Dry-run", value=True)

                with ui.row().classes("gap-2 mt-3 w-full items-center"):
                    run_btn = ui.button("Cherry-pick").props(
                        "color=primary no-caps"
                    )
                progress_label = ui.label("").classes("text-xs text-slate-600")

                ui.separator().classes("my-3")
                ui.label("Undo").classes(
                    "text-sm uppercase text-slate-500 tracking-wide"
                )
                undo_input = ui.input(
                    "selection_report.json yolu",
                    placeholder="(run sonrası otomatik dolar)",
                ).props("dense outlined").classes("w-full")
                undo_btn = ui.button("Undo").props(
                    "outline color=grey-7 no-caps"
                )

            # ---------- Sağ: Sonuç + preview ----------
            with ui.card().classes("w-full"):
                ui.label("Sonuç").classes(
                    "text-sm uppercase text-slate-500 tracking-wide"
                )
                summary_label = ui.label(
                    "Henüz cherry-pick yapılmadı."
                ).classes("text-sm text-slate-600 italic mt-1")

                with ui.row().classes("w-full justify-around mt-2"):
                    with ui.column().classes("items-center gap-0"):
                        sel_card = ui.label("—").classes(
                            "text-3xl font-bold text-slate-700"
                        )
                        ui.label("Selected").classes(
                            "text-xs uppercase text-slate-500"
                        )
                    with ui.column().classes("items-center gap-0"):
                        score_card = ui.label("—").classes(
                            "text-3xl font-bold text-blue-600"
                        )
                        ui.label("Avg score").classes(
                            "text-xs uppercase text-slate-500"
                        )
                    with ui.column().classes("items-center gap-0"):
                        face_card = ui.label("—").classes(
                            "text-3xl font-bold text-emerald-600"
                        )
                        ui.label("Face-visible").classes(
                            "text-xs uppercase text-slate-500"
                        )

                ui.separator().classes("my-2")
                ui.label("Bucket dağılım").classes(
                    "text-xs uppercase text-slate-500 tracking-wide"
                )
                buckets_panel = ui.column().classes("w-full gap-1 mt-1")

                ui.separator().classes("my-2")
                ui.label("Seçim önizleme (ilk 24)").classes(
                    "text-xs uppercase text-slate-500 tracking-wide"
                )
                preview_grid = ui.grid(columns=6).classes("w-full gap-2 mt-1")

        # ============= Action handlers =============

        def _do_run():
            src = (src_input.value or "").strip()
            out = (out_input.value or "").strip()
            rep = (rep_input.value or "").strip()
            if not src or not out or not rep:
                ui.notify("Source, Output ve Report gerekli", type="warning")
                return
            src_p = Path(src)
            out_p = Path(out)
            rep_p = Path(rep)
            if not src_p.is_dir():
                ui.notify(f"Source dizin değil: {src_p}", type="negative")
                return
            if not rep_p.is_file():
                ui.notify(f"Quality rapor bulunamadı: {rep_p}", type="negative")
                return

            try:
                distribution = golden_parse_distribution(distribution_input.value)
            except (ValueError, KeyError) as e:
                ui.notify(f"Distribution parse hatası: {e}", type="negative")
                return

            count = int(count_input.value or 0)
            if count <= 0:
                ui.notify("Count pozitif olmalı", type="warning")
                return

            character = (character_input.value or "").strip() or None
            face_target = int(face_target_input.value or 0)

            run_btn.disable()
            progress_label.text = "Seçim yapılıyor..."

            try:
                selection = golden_select(
                    source=src_p, report=rep_p,
                    count=count, distribution=distribution,
                    character=character, face_target=face_target,
                    recursive=bool(recursive_check.value),
                )
            except Exception as e:  # noqa: BLE001
                progress_label.text = f"Hata: {e}"
                run_btn.enable()
                ui.notify(f"Selection hatası: {e}", type="negative")
                return

            if not selection.selected:
                progress_label.text = "Boş seçim — filter sonrası asset kalmadı."
                run_btn.enable()
                ui.notify("Boş seçim — filter sonrası asset kalmadı", type="warning")
                return

            # Apply
            try:
                apply_result = golden_apply_selection(
                    selection.selected,
                    target_dir=out_p,
                    source_root=src_p if recursive_check.value else None,
                    force=bool(force_check.value),
                    dry_run=bool(dryrun_check.value),
                )
            except FileExistsError as e:
                progress_label.text = f"Hata: target dolu (force kullan)"
                run_btn.enable()
                ui.notify(str(e), type="negative")
                return
            except Exception as e:  # noqa: BLE001
                progress_label.text = f"Apply hatası: {e}"
                run_btn.enable()
                ui.notify(f"Apply hatası: {e}", type="negative")
                return

            # Rapor
            report_out = out_p / "selection_report.json"
            cfg = {
                "count": count,
                "distribution": distribution,
                "character": character,
                "face_target": face_target,
                "recursive": bool(recursive_check.value),
                "force": bool(force_check.value),
                "dry_run": bool(dryrun_check.value),
                "input": str(src_p.resolve()),
                "output": str(out_p.resolve()),
                "quality_report": str(rep_p.resolve()),
            }
            try:
                rp = golden_write_report(
                    report_path=report_out,
                    source_root=src_p,
                    config=cfg,
                    selection=selection,
                    apply_result=apply_result,
                )
            except Exception as e:  # noqa: BLE001
                ui.notify(f"Rapor yazma hatası: {e}", type="negative")
                rp = None

            # Sonuç güncelle
            tab_state["last_selection"] = selection
            sel_card.text = str(len(selection.selected))
            score_card.text = f"{selection.average_score:.3f}"
            face_card.text = str(selection.face_count)
            mode = "(DRY-RUN)" if dryrun_check.value else ""
            summary_label.text = (
                f"{len(selection.selected)} / {count} seçildi {mode}"
            )

            # Bucket dağılım
            buckets_panel.clear()
            with buckets_panel:
                for bucket, n in sorted(selection.selection_stats.items()):
                    avail = selection.buckets_available.get(bucket, 0)
                    goal = selection.goals.get(bucket, 0)
                    ui.label(
                        f"  {bucket}: {n} (hedef={goal}, havuz={avail})"
                    ).classes("text-xs text-slate-700")

            # Preview gallery
            preview_grid.clear()
            with preview_grid:
                for asset in selection.selected[:24]:
                    with ui.card().classes("p-1"):
                        ui.image(_path_to_url(str(asset.path))).classes(
                            "w-full h-24 object-cover rounded"
                        )
                        ui.label(asset.filename).classes(
                            "text-xs text-slate-600 truncate"
                        ).style("max-width: 100%")
                        ui.label(f"{asset.final_score:.2f}").classes(
                            "text-xs text-slate-400"
                        )

            if rp:
                STATE.last_report_paths[7] = str(rp)
                undo_input.value = str(rp)

            progress_label.text = f"✓ Tamam {mode}"
            run_btn.enable()
            ui.notify(
                f"Cherry-pick OK: {len(selection.selected)} asset {mode}",
                type="positive",
            )
            # Gerçek apply'da (dry-run değil) golden-set output pipeline'a
            # alternatif olarak sunulur. Dry-run'da gerçek dosya yok → skip.
            if not dryrun_check.value:
                STATE.register_output(7, str(out_p))

        def _do_undo():
            rp = (undo_input.value or "").strip()
            if not rp:
                ui.notify("Rapor yolu gerekli", type="warning")
                return
            rep_path = Path(rp)
            if not rep_path.is_file():
                ui.notify(f"Rapor bulunamadı: {rep_path}", type="negative")
                return
            try:
                removed, skipped = golden_undo_from_report(rep_path)
            except ValueError as e:
                ui.notify(f"Tool mismatch: {e}", type="negative")
                return
            except Exception as e:  # noqa: BLE001
                ui.notify(f"Undo hatası: {e}", type="negative")
                return
            ui.notify(
                f"Undo: removed={removed} skipped={skipped}",
                type="positive",
            )
            # Undo başarılı → golden-set output artık geçersiz
            STATE.clear_output(7)

        run_btn.on("click", _do_run)
        undo_btn.on("click", _do_undo)


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
