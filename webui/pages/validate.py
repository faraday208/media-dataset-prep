"""01 — Validate: format/boyut/aspect/bütünlük + aksiyon + undo."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import asyncio
import json

from nicegui import ui
from validator_core.validators.file_validator import FileValidator
from validator_core.scanner import (  # noqa: E402
    collect_images as validate_collect_images,
    apply_action as validate_apply_action,
    undo_from_report as validate_undo_from_report,
    write_report as validate_write_report,
    DEFAULT_REPORT_NAME as VALIDATE_REPORT_NAME,
)

from webui.state import STATE
from webui.helpers import (
    _safe_call,
    _safe_set_value,
    _safe_set_text,
    _safe_set_visible,
    _safe_enable,
    _safe_disable,
    _safe_notify,
    _resolve_dataset_relative,
    _report_path,
    _append_manifest_from_report,
    _reject_dir_for,
)
from webui.browse import _open_browse_dialog


def build_validate_tab():
    """01 — Validate: format / boyut / aspect / bütünlük + opsiyonel move/delete + undo."""
    with ui.column().classes("w-full max-w-screen-xl mx-auto p-6 gap-4"):
        ui.label("01 — Validate").classes("text-2xl font-semibold")
        ui.label(
            "Hatalı görselleri tespit et: format / boyut / aspect / bütünlük. "
            "/rejected'a taşı veya sil — dry-run ile önce prova yap, undo destekli."
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
                        "move": "/rejected'a taşı (default, undoable)",
                        "delete": "Sil (irreversible)",
                    },
                    label="Hatalı dosyalar için aksiyon",
                    value="move",
                ).props("dense outlined").classes("w-full")

                with ui.row().classes("w-full items-center gap-1 no-wrap"):
                    invalid_dir_input = ui.input(
                        "Invalid dir",
                        placeholder="move için zorunlu — çalışma klasörü DIŞINA ver (örn. ../_rejected/01-validate)",
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
                    placeholder="(run sonrası otomatik dolar)",
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
            """Move seçilince invalid_dir input'u <base>/_rejected/<stage> (KARDEŞ) ile
            auto-doldur (kullanıcı boş bıraktıysa)."""
            if value == "move" and not invalid_dir_input.value and STATE.dataset_path:
                invalid_dir_input.value = _reject_dir_for("01-validate")
                invalid_dir_input.update()

        action_select.on_value_change(lambda e: _on_action_change(e.value))
        # Default action "move" olduğu için on_value_change load'da tetiklenmez;
        # dataset seçiliyse invalid_dir'i bir kez kuruluşta auto-doldur.
        _on_action_change(action_select.value)

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
                _safe_notify(
                    "⚠ %100 reddedildi — threshold'larınız çok sıkı olabilir. "
                    "Threshold ayarlarını gevşetmeyi deneyin.",
                    type="warning",
                    timeout=8000,
                )

        async def on_run():
            import threading

            err = _validate_inputs()
            if err:
                ui.notify(err, type="negative")
                return

            _safe_disable(run_btn)
            _safe_set_visible(progress_bar, True)
            _safe_set_value(progress_bar, 0)
            try:
                config = _build_config()
                validator = FileValidator(config)
                exts = {f".{f}" for f in config["file_validation"]["allowed_formats"]}
                exts |= {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}

                _safe_set_text(progress_label, "Tarama…")
                # Büyük dizinde collect_images de bloklayıcı — thread'e at.
                images = await asyncio.to_thread(
                    validate_collect_images,
                    STATE.dataset_path,
                    recursive=recursive_check.value,
                    allowed_exts=exts,
                )
                if not images:
                    _safe_notify("Hiç dosya bulunamadı", type="warning")
                    return

                total = len(images)
                results: list[dict] = []
                # Worker thread sayaçları paylaşır; main coroutine poll edip
                # UI'ı günceller. Bu sayede event loop bloklamaz, WebSocket
                # heartbeat sürekli akar.
                shared = {"i": 0, "valid": 0, "invalid": 0, "reasons": {}}
                lock = threading.Lock()

                def _worker():
                    for i, img in enumerate(images):
                        r = validator.validate(img)
                        d = r.to_dict()
                        with lock:
                            results.append(d)
                            if r.valid:
                                shared["valid"] += 1
                            else:
                                shared["invalid"] += 1
                                shared["reasons"][r.reason] = (
                                    shared["reasons"].get(r.reason, 0) + 1
                                )
                            shared["i"] = i + 1

                _safe_set_text(progress_label, f"0 / {total}")
                worker_task = asyncio.create_task(asyncio.to_thread(_worker))
                while not worker_task.done():
                    with lock:
                        i = shared["i"]
                    _safe_set_value(progress_bar, i / total if total else 0)
                    _safe_set_text(progress_label, f"{i} / {total}")
                    await asyncio.sleep(0.25)
                # Worker bittikten sonra exception varsa fırlat
                await worker_task

                with lock:
                    valid = shared["valid"]
                    invalid = shared["invalid"]
                    reasons = dict(shared["reasons"])
                _safe_set_value(progress_bar, 1.0)
                _safe_set_text(progress_label, f"{total} / {total}")

                summary = {
                    "total": total,
                    "valid": valid,
                    "invalid": invalid,
                    "reasons": reasons,
                }

                # Aksiyon her zaman move/delete (salt-rapor için dry-run kullanılır).
                action = action_select.value
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

            except Exception as e:
                _safe_notify(f"Validate hatası: {e}", type="negative")
            finally:
                _safe_set_visible(progress_bar, False)
                _safe_set_text(progress_label, "")
                _safe_enable(run_btn)

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
                # Relative path (örn. "./", "rejected") dataset bazlı çözülür;
                # absolute olduğu gibi geçer. cwd (media-dataset-prep) baz alınmaz.
                resolved_invalid_dir = _resolve_dataset_relative(invalid_dir_input.value)
                action_res = validate_apply_action(
                    results,
                    source_root=STATE.dataset_path,
                    action=action,
                    invalid_dir=resolved_invalid_dir,
                    dry_run=dryrun_check.value,
                )
                # Rapor
                # Rapor proje kökünde (base_path) — aktif dataset_path değil.
                report_path = Path(_report_path(VALIDATE_REPORT_NAME, STATE.base_path))
                _write_report_helper(
                    report_path,
                    summary=summary,
                    results=results,
                    action_result=action_res,
                    config=_build_config(),
                    exts=exts,
                )
                _safe_set_value(undo_input, str(report_path))
                STATE.last_report_paths[1] = str(report_path)
                if not dryrun_check.value:
                    # params: resume'da config formunu geri yüklemek için reçete
                    # (organize stage ile simetrik — bkz. _restore_config_from_memory).
                    _append_manifest_from_report(
                        1, report_path,
                        output_dir=invalid_dir_input.value or None,
                        params={
                            "recursive": recursive_check.value,
                            "action": action_select.value,
                            "invalid_dir": invalid_dir_input.value or None,
                            "allowed_formats": allowed_formats_input.value,
                            "min_short_edge": int(min_short_edge.value or 0),
                            "max_short_edge": int(max_short_edge.value or 8192),
                            "min_aspect": float(min_aspect.value or 0),
                            "max_aspect": float(max_aspect.value or 999),
                            "min_size_kb": float(min_size_kb.value or 0),
                            "max_size_mb": float(max_size_mb.value or 50),
                        },
                    )

                dryrun_tag = " (DRY-RUN)" if dryrun_check.value else ""
                if action == "move":
                    msg = f"Taşınan: {len(action_res.entries)}{dryrun_tag} → {action_res.invalid_dir}"
                else:
                    msg = f"Silinen: {len(action_res.entries)}{dryrun_tag}"
                _safe_call(
                    _populate_results,
                    results, summary,
                    action_msg=f"{msg}\nRapor: {report_path}",
                )
                _safe_notify(msg, type="positive" if not dryrun_check.value else "info")
                STATE.notify_change()
            except Exception as e:
                _safe_notify(f"Aksiyon hatası: {e}", type="negative")

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

        # ------ Resume (manifest'ten geri yükleme — organize stage ile simetrik) ------
        # Header'da dataset seçilince STATE.on_change tetiklenir; manifest zaten
        # last_report_paths[1] + last_stage_params[1]'i doldurmuş olur. Buradaki
        # restore'lar "kaldığımız yeri" forma + sonuç paneline taşır.

        def _restore_undo_from_memory():
            """Hafızadaki validate_report.json yolunu undo alanına doldur (boşsa)."""
            rp = STATE.last_report_paths.get(1)
            if rp and not undo_input.value:
                undo_input.set_value(rp)

        def _maybe_restore_number(widget, default, saved):
            """Widget hâlâ default'taysa ve kayıtlı değer varsa geri yükle —
            kullanıcının elle değiştirdiği threshold'u ezmez."""
            if saved is None:
                return
            try:
                if float(widget.value or 0) == float(default):
                    widget.set_value(saved)
            except (TypeError, ValueError):
                pass

        def _restore_config_from_memory():
            """Resume: önceki validate reçetesini forma geri yükle — yalnızca alan
            hâlâ default'taysa (aktif düzeni ezmez). Organize'ın
            _restore_config_from_memory'si ile simetrik."""
            prm = STATE.last_stage_params.get(1) or {}
            if not prm:
                return
            if recursive_check.value is True and isinstance(prm.get("recursive"), bool):
                recursive_check.set_value(prm["recursive"])
            if action_select.value == "move" and prm.get("action") in {"move", "delete"}:
                action_select.set_value(prm["action"])
            # invalid_dir action'dan SONRA — _on_action_change'in doldurduğu default
            # reject dir'i kayıtlı (custom olabilir) değerle ez.
            if prm.get("invalid_dir"):
                invalid_dir_input.set_value(prm["invalid_dir"])
            if (allowed_formats_input.value or "") == "jpg,jpeg,png,webp" and prm.get(
                "allowed_formats"
            ):
                allowed_formats_input.set_value(prm["allowed_formats"])
            _maybe_restore_number(min_short_edge, 512, prm.get("min_short_edge"))
            _maybe_restore_number(max_short_edge, 8192, prm.get("max_short_edge"))
            _maybe_restore_number(min_aspect, 0.5, prm.get("min_aspect"))
            _maybe_restore_number(max_aspect, 2.0, prm.get("max_aspect"))
            _maybe_restore_number(min_size_kb, 100, prm.get("min_size_kb"))
            _maybe_restore_number(max_size_mb, 50, prm.get("max_size_mb"))

        def _restore_results_from_memory():
            """Resume: önceki validate raporundan stat kartları + reason kırılımı +
            tabloyu geri yükle — yeniden tarama YOK. Canlı sonucu ezmez."""
            rp = STATE.last_report_paths.get(1)
            if not rp:
                return
            if "Henüz validate" not in (summary_label.text or ""):
                return
            try:
                data = json.loads(Path(rp).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return
            summary = data.get("summary")
            results = data.get("results")
            if isinstance(summary, dict) and isinstance(results, list):
                _populate_results(
                    results, summary,
                    action_msg=f"✓ Önceki validate raporu yüklendi:\n{rp}",
                )

        def _restore_all():
            _restore_undo_from_memory()
            _restore_config_from_memory()
            _restore_results_from_memory()

        STATE.on_change(_restore_all)
        _restore_all()

        run_btn.on("click", on_run)
        undo_preview_btn.on("click", lambda: _run_undo(dry_run=True))
        undo_btn.on("click", lambda: _run_undo(dry_run=False))
