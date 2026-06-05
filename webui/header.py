"""Global header: dataset seçimi + output banner."""
from __future__ import annotations

from pathlib import Path

from nicegui import ui

from webui.state import STATE, PIPELINE_STEPS
from webui.helpers import (
    _load_project_memory,
)
from webui.browse import _open_browse_dialog


def build_header():
    with ui.header().classes("items-center justify-between bg-slate-800 text-white"):
        ui.label("Media Dataset Prep").classes("text-xl font-semibold")

        with ui.row().classes("items-center gap-2"):
            ui.label("Dataset:").classes("text-sm")
            path_input = ui.input(
                placeholder="/path/to/dataset",
                value=STATE.base_path,
                on_change=lambda e: setattr(STATE, "base_path", e.value),
            ).props("dense outlined dark").classes("w-96")

            def _on_dataset_pick(chosen: str):
                STATE.base_path = chosen
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
                    mem = _load_project_memory(STATE.dataset_path)
                    if mem:
                        done = ",".join(f"{i:02d}" for i in mem["done"]) or "-"
                        af = mem.get("active_folder")
                        af_txt = f" · aktif: {af}" if af else ""
                        ui.notify(
                            f"📋 Hafıza yüklendi — son: {mem.get('last_stage')} "
                            f"({mem.get('last_time')}) · biten: {done}{af_txt}",
                            type="info",
                        )
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
