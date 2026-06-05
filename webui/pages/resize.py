"""05 — Resize: Lanczos aspect-preserving batch resize."""
from __future__ import annotations

from pathlib import Path
import os

from nicegui import ui
from resize_core import (  # noqa: E402
    resize_dataset,
    undo_from_report as resize_undo_from_report,
    write_report as resize_write_report,
    DEFAULT_REPORT_NAME as RESIZE_REPORT_NAME,
)

from webui.state import STATE
from webui.helpers import (
    _report_path,
    _append_manifest_from_report,
)
from webui.browse import _open_browse_dialog


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
                # Source dataset: header'dan implicit (tek truth source).

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

                def _suggest_out_dir(mode_val: str) -> None:
                    """Copy seçilince ve out_input boşsa
                    `{dataset_path}/resized` önerir."""
                    if mode_val == "copy" and not out_input.value and STATE.dataset_path:
                        out_input.set_value(
                            os.path.join(STATE.dataset_path, "resized")
                        )

                def _toggle_out(val: str):
                    out_row.visible = (val == "copy")
                    _suggest_out_dir(val)
                mode_select.on_value_change(lambda e: _toggle_out(e.value))
                # İlk render — default mode "copy" → ilk öneri
                _suggest_out_dir(mode_select.value)

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

                dryrun_check = ui.checkbox("Dry-run", value=True)

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
            if not STATE.is_valid_dataset():
                ui.notify(
                    "Dataset yolu geçerli değil (header'da doğrula)",
                    type="warning",
                )
                return
            input_dir = Path(STATE.dataset_path)

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

            # Rapor PROJE KÖKÜNDE (base_path) — aktif dataset_path/output değil.
            report_path = Path(_report_path(RESIZE_REPORT_NAME, STATE.base_path))
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
            if not dryrun_check.value:
                _append_manifest_from_report(5, report_path, output_dir=out_dir or str(input_dir))
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
