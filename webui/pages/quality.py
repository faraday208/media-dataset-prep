"""03 — Quality: blur/brightness/contrast/BPP metrikleri."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import asyncio

from nicegui import ui
from quality_core import (  # noqa: E402
    apply_action as quality_apply_action,
    find_quality_issues,
    undo_from_report as quality_undo_from_report,
    write_report as quality_write_report,
    DEFAULT_REPORT_NAME as QUALITY_REPORT_NAME,
)

from webui.state import STATE
from webui.helpers import (
    _resolve_dataset_relative,
    _report_path,
    _append_manifest_from_report,
    _reject_dir_for,
    _path_to_url,
    _aspect_label,
    _bpp_label,
)
from webui.browse import _open_browse_dialog


def build_quality_tab():
    """03 — Quality: 4 metric (blur/brightness/contrast/bpp) + composite scan
    + action (move/delete) + undo. Tablo + thumbnail gallery + lightbox."""
    # Tab-local — lightbox carousel invalid'ler arasında gezsin diye saklanır
    q_state: dict = {"invalid": []}
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

                # Threshold ayarları
                with ui.expansion("Threshold ayarları (advanced)", icon="tune").classes(
                    "w-full mt-2"
                ):
                    with ui.column().classes("w-full gap-2 p-2"):
                        ui.label("Blur (Laplacian variance — düşük=bulanık)").classes(
                            "text-xs text-slate-500"
                        )
                        with ui.grid(columns="1fr 1fr").classes("w-full gap-3"):
                            blur_threshold = ui.number(
                                "Min blur score", value=100, min=0, step=10,
                            ).props("dense outlined")
                            blur_method_select = ui.select(
                                {
                                    "tile": "Tile (en keskin bölge)",
                                    "global": "Global (tüm görsel)",
                                },
                                label="Blur yöntemi",
                                value="tile",
                            ).props("dense outlined").tooltip(
                                "Tile (önerilen): görseli grid'e böler, en keskin "
                                "bölgeyi baz alır — bokeh/DoF arkaplan keskin özneyi "
                                "'blurry' damgalamaz.\n"
                                "Global: tüm görselin ortalaması — bulanık arkaplan "
                                "skoru düşürür (bokeh portreleri yanlış eleyebilir)."
                            )

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

                ui.separator().classes("my-2")
                ui.label("Görsel önizleme (invalid)").classes(
                    "text-xs uppercase text-slate-500 tracking-wide"
                )
                gallery_panel = ui.column().classes("w-full gap-2 mt-1")
                with gallery_panel:
                    ui.label("Run sonrası düşük-quality görseller burada gösterilir.").classes(
                        "text-sm text-slate-500 italic"
                    )

        # ------ Action handlers ------

        def _build_config() -> dict:
            return {
                "quality": {
                    "blur_threshold": float(blur_threshold.value or 100),
                    "blur_method": blur_method_select.value,
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
                invalid_dir_input.value = _reject_dir_for("03-quality")
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

        def _metric_parts(r: dict) -> str:
            parts = []
            if r.get("blur_score") is not None:
                parts.append(f"blur {_fmt(r['blur_score'])}")
            if r.get("brightness_score") is not None:
                parts.append(f"br {_fmt(r['brightness_score'])}")
            if r.get("contrast_score") is not None:
                parts.append(f"ct {_fmt(r['contrast_score'])}")
            if r.get("bpp_score") is not None:
                parts.append(f"bpp {_fmt(r['bpp_score'])}")
            return " · ".join(parts)

        def _refresh_gallery():
            gallery_panel.clear()
            invalid = q_state["invalid"]
            if not invalid:
                with gallery_panel:
                    ui.label("Düşük-quality görsel yok.").classes(
                        "text-sm text-slate-500 italic"
                    )
                return
            with gallery_panel:
                ui.label(
                    f"{len(invalid)} düşük-quality görsel — büyütmek için tıkla"
                ).classes("text-xs text-slate-500")
                with ui.grid(columns="repeat(4, 1fr)").classes("w-full gap-3"):
                    for i, r in enumerate(invalid):
                        path = r.get("path", "")
                        with ui.column().classes(
                            "p-2 rounded border border-slate-200 gap-1"
                        ):
                            try:
                                img = ui.image(_path_to_url(path)).classes(
                                    "w-full h-40 object-contain bg-slate-100 "
                                    "cursor-pointer hover:opacity-90 transition"
                                )
                                img.on("click", lambda _e, k=i: _open_lightbox(k))
                                img.tooltip("Büyütmek için tıkla")
                            except Exception:
                                ui.label("(önizleme yok)").classes(
                                    "text-xs text-slate-400"
                                )
                            ui.label(Path(path).name).classes(
                                "text-xs font-mono truncate"
                            ).tooltip(path)
                            ui.label(r.get("reason", "")).classes(
                                "text-xs text-red-600 truncate"
                            ).tooltip(r.get("reason", ""))
                            ui.label(_metric_parts(r)).classes(
                                "text-xs text-slate-600 font-mono"
                            )

        def _open_lightbox(start_idx: int):
            """Tam ekran lightbox + carousel (invalid'ler arası ←/→) + zoom.
            Duplicate sayfasının lightbox'ından uyarlandı."""
            invalid = q_state["invalid"]
            if not invalid:
                return
            lb = {"idx": max(0, min(start_idx, len(invalid) - 1)), "zoom": "fit"}
            ZOOM_LEVELS = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]

            with ui.dialog().props("maximized") as dlg, ui.card().classes(
                "w-full h-screen p-0 bg-black overflow-hidden"
            ):
                with ui.column().classes(
                    "w-full h-full overflow-auto relative bg-black "
                    "items-center justify-center"
                ):
                    img_html = ui.html("")
                    with ui.row().classes(
                        "absolute top-2 left-2 right-2 items-center gap-2 z-10 flex-wrap"
                    ):
                        title_label = ui.label("").classes(
                            "text-white text-sm bg-black/60 px-3 py-1 rounded font-mono"
                        )
                        reason_label = ui.label("").classes(
                            "text-white text-xs bg-red-600/80 px-2 py-1 rounded"
                        )
                        metric_label = ui.label("").classes(
                            "text-white text-xs bg-black/60 px-2 py-1 rounded font-mono"
                        )
                        bpp_label_w = ui.label("").classes(
                            "text-xs px-2 py-1 rounded bg-black/60"
                        )
                        ui.space()
                        with ui.row().classes("items-center gap-1 bg-black/60 rounded px-1"):
                            ui.button(icon="remove").props(
                                "flat dense color=white size=sm"
                            ).on("click", lambda: _zoom_step(-1))
                            zoom_btn = ui.button("Fit").props(
                                "flat dense color=white size=sm no-caps"
                            )
                            zoom_btn.on("click", lambda: _zoom_toggle())
                            ui.button(icon="add").props(
                                "flat dense color=white size=sm"
                            ).on("click", lambda: _zoom_step(1))
                        ui.button(icon="close", on_click=dlg.close).props(
                            "flat round color=white"
                        ).tooltip("Kapat (Esc)")

                    if len(invalid) > 1:
                        ui.button(icon="chevron_left").props(
                            "fab-mini color=white text-color=black"
                        ).classes(
                            "absolute left-4 top-1/2 -translate-y-1/2 z-10 opacity-80"
                        ).on("click", lambda: _step(-1))
                        ui.button(icon="chevron_right").props(
                            "fab-mini color=white text-color=black"
                        ).classes(
                            "absolute right-4 top-1/2 -translate-y-1/2 z-10 opacity-80"
                        ).on("click", lambda: _step(1))

                    with ui.row().classes(
                        "absolute bottom-2 left-1/2 -translate-x-1/2 items-center gap-2 z-10"
                    ):
                        counter_label = ui.label("").classes(
                            "text-white text-sm bg-black/60 px-3 py-1 rounded font-mono"
                        )
                        hint = (["← →"] if len(invalid) > 1 else []) + ["+ −", "0=Fit", "1=100%"]
                        ui.label(" · ".join(hint)).classes(
                            "text-white text-xs bg-black/40 px-2 py-1 rounded"
                        )

                    def _render():
                        r = invalid[lb["idx"]]
                        path = r.get("path", "")
                        url = _path_to_url(path)
                        w, h = r.get("width", 0), r.get("height", 0)
                        sz = r.get("size_bytes", 0)
                        title_label.set_text(Path(path).name)
                        reason_label.set_text(r.get("reason", ""))
                        metric_label.set_text(_metric_parts(r))
                        bpp_info = _bpp_label(w, h, sz)
                        if bpp_info:
                            bt, bc = bpp_info
                            bpp_label_w.set_text(bt)
                            bpp_label_w.classes(
                                replace=f"{bc} bg-white/90 text-xs px-2 py-1 rounded font-mono font-semibold"
                            )
                        else:
                            bpp_label_w.set_text("")
                        z = lb["zoom"]
                        if z == "fit" or not (w and h):
                            style = ("max-width: 100vw; max-height: 100vh; width: auto; "
                                     "height: auto; object-fit: contain; display: block; margin: auto;")
                            zoom_btn.set_text("Fit")
                        else:
                            style = (f"width: {int(w*z)}px; height: {int(h*z)}px; "
                                     "max-width: none; max-height: none; display: block; margin: auto;")
                            zoom_btn.set_text(f"{int(z*100)}%")
                        counter_label.set_text(f"{lb['idx']+1} / {len(invalid)}")
                        img_html.set_content(f'<img src="{url}" style="{style}">')

                    def _step(d):
                        lb["idx"] = (lb["idx"] + d) % len(invalid)
                        _render()

                    def _zoom_step(d):
                        z = lb["zoom"]
                        if z == "fit":
                            lb["zoom"] = 1.0 if d > 0 else "fit"
                        else:
                            try:
                                i = ZOOM_LEVELS.index(z)
                            except ValueError:
                                i = min(range(len(ZOOM_LEVELS)),
                                        key=lambda k: abs(ZOOM_LEVELS[k] - z))
                            lb["zoom"] = ZOOM_LEVELS[max(0, min(len(ZOOM_LEVELS)-1, i + d))]
                        _render()

                    def _zoom_toggle():
                        lb["zoom"] = 1.0 if lb["zoom"] == "fit" else "fit"
                        _render()

                    def _zoom_set(v):
                        lb["zoom"] = v
                        _render()

                    def _on_key(e):
                        if not e.action.keydown:
                            return
                        if e.key.arrow_left:
                            _step(-1)
                        elif e.key.arrow_right:
                            _step(1)
                        elif str(e.key) in {"+", "="}:
                            _zoom_step(1)
                        elif str(e.key) == "-":
                            _zoom_step(-1)
                        elif str(e.key) == "0":
                            _zoom_set("fit")
                        elif str(e.key) == "1":
                            _zoom_set(1.0)

                    kb = ui.keyboard(on_key=_on_key, active=True)
                    dlg.on("hide", lambda: setattr(kb, "active", False))
                    _render()
            dlg.open()

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

            # Thumbnail gallery — invalid görseller (lightbox carousel için sakla)
            q_state["invalid"] = [r for r in sr.results if not r.get("valid")]
            _refresh_gallery()

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
                # Relative path → dataset bazlı (cwd yerine).
                resolved_invalid_dir = _resolve_dataset_relative(invalid_dir_input.value)
                ar = quality_apply_action(
                    sr.results,
                    source_root=STATE.dataset_path,
                    action=action,
                    invalid_dir=resolved_invalid_dir,
                    dry_run=dryrun_check.value,
                )
                # Rapor proje kökünde (base_path) — aktif dataset_path değil.
                report_path = Path(_report_path(QUALITY_REPORT_NAME, STATE.base_path))

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
                if action != "none" and not dryrun_check.value:
                    _append_manifest_from_report(3, report_path)

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
