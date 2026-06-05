"""04 — Watermark: YOLOv8 filigran tespiti + filtreleme."""
from __future__ import annotations

from pathlib import Path

from nicegui import ui
from watermark_core import (  # noqa: E402
    apply_action as watermark_apply_action,
    find_watermarks,
    undo_from_report as watermark_undo_from_report,
    write_report as watermark_write_report,
    DEFAULT_CONFIDENCE as WATERMARK_DEFAULT_CONFIDENCE,
    DEFAULT_MODEL_PATH as WATERMARK_DEFAULT_MODEL_PATH,
    DEFAULT_REPORT_NAME as WATERMARK_REPORT_NAME,
)

from webui.state import STATE
from webui.helpers import (
    _resolve_dataset_relative,
    _report_path,
    _reject_dir_for,
)
from webui.browse import _open_browse_dialog


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
                # Dataset path: header'dan implicit okunur (Step 01-04 paterni —
                # destructive değil, tek truth source header).

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
                        placeholder="move için zorunlu — çalışma klasörü DIŞINA ver (örn. ../_rejected)",
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

        def _on_action_change(value: str):
            """Move seçilince invalid_dir'i <base>/_rejected/<stage> (KARDEŞ) ile
            auto-doldur (kullanıcı boş bıraktıysa). Validate tab'ındaki patern."""
            if value == "move" and not invalid_dir_input.value and STATE.dataset_path:
                invalid_dir_input.value = _reject_dir_for("04-watermark")
                invalid_dir_input.update()

        action_select.on_value_change(lambda e: _on_action_change(e.value))

        def _do_run():
            if not STATE.is_valid_dataset():
                ui.notify(
                    "Dataset yolu geçerli değil (header'da doğrula)",
                    type="warning",
                )
                return
            input_dir = Path(STATE.dataset_path)

            action = action_select.value
            invalid_dir = (invalid_dir_input.value or "").strip()
            if action == "move" and not invalid_dir:
                ui.notify("Move için rejected klasörü gerekli", type="warning")
                return
            # Relative path → dataset bazlı (cwd yerine).
            invalid_dir = _resolve_dataset_relative(invalid_dir) or ""

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
            report_path = Path(_report_path(WATERMARK_REPORT_NAME, str(input_dir)))
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
