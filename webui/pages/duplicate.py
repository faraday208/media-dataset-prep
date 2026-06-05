"""02 — Duplicate: exact (MD5) + similar (phash) tespit."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import asyncio

from nicegui import ui
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
    _path_to_url,
    _aspect_label,
    _bpp_label,
)
from webui.browse import _open_browse_dialog


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
                    placeholder="(run sonrası otomatik dolar)",
                ).props("dense outlined").classes("w-full")
                with ui.row().classes("gap-2"):
                    undo_preview_btn = ui.button("Preview Undo").props(
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
                invalid_dir_input.value = _reject_dir_for("02-duplicate")
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
                _safe_notify(err, type="negative")
                return

            cfg = _build_config()
            if cfg["mode"] == "similar" and not DupHasher.is_perceptual_hash_available():
                _safe_notify("imagehash kütüphanesi yüklü değil", type="negative")
                return

            _safe_disable(scan_btn)
            _safe_disable(apply_btn)
            _safe_set_visible(progress_bar, True)
            _safe_set_value(progress_bar, 0)
            _safe_set_text(progress_label, "Tarama…")

            # Progress callback worker thread'den çağrılır; safe-helper'lar
            # client öldüyse RuntimeError'u yutar.
            def _cb(current: int, total: int, msg: str):
                if total > 0:
                    _safe_set_value(progress_bar, current / total)
                _safe_set_text(progress_label, msg)

            try:
                # Hash hesaplama + grouping uzun süren CPU işidir — thread'e at,
                # event loop serbest kalsın, WebSocket heartbeat kesintisiz aksın.
                if cfg["mode"] == "exact":
                    sr = await asyncio.to_thread(
                        find_exact_duplicates,
                        STATE.dataset_path,
                        recursive=recursive_check.value,
                        progress_cb=_cb,
                    )
                else:
                    sr = await asyncio.to_thread(
                        find_similar_images,
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
                _safe_call(_bulk_set_keeper, keep_strategy_select.value)

                _safe_call(_refresh_stats)
                _safe_call(_refresh_gallery)

                if sr.has_duplicates:
                    _safe_enable(prev_btn)
                    _safe_enable(next_btn)
                    _safe_enable(apply_btn)
                else:
                    _safe_disable(prev_btn)
                    _safe_disable(next_btn)
                    _safe_disable(apply_btn)

                _safe_set_text(
                    summary_label,
                    f"Scan tamam: {len(sr.groups)} grup, "
                    f"{sr.removable_count} silinebilir, "
                    f"{dedup_humanize_bytes(sr.space_freeable_bytes)} kazanım",
                )
                _safe_notify(
                    f"{len(sr.groups)} grup bulundu" if sr.has_duplicates
                    else "Duplicate bulunamadı",
                    type="positive" if sr.has_duplicates else "info",
                )
            except Exception as e:
                _safe_notify(f"Scan hatası: {e}", type="negative")
            finally:
                _safe_set_visible(progress_bar, False)
                _safe_set_text(progress_label, "")
                _safe_enable(scan_btn)

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

        async def _do_apply():
            sr = tab_state["scan_result"]
            if sr is None:
                _safe_notify("Önce Scan çalıştır", type="negative")
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
                # Dialog confirm → coroutine başlat (NiceGUI sync callback'ten
                # async başlatmak için background_tasks.create kullanır).
                _confirm_delete_dialog(
                    sr.removable_count,
                    on_confirm=lambda: asyncio.create_task(_do_apply_inner()),
                )
                return
            await _do_apply_inner()

        async def _do_apply_inner():
            sr = tab_state["scan_result"]
            _safe_disable(apply_btn)
            _safe_set_visible(progress_bar, True)
            _safe_set_value(progress_bar, 0)
            _safe_set_text(progress_label, "Apply ediliyor…")
            try:
                # Relative path → dataset bazlı (cwd yerine).
                resolved_invalid_dir = _resolve_dataset_relative(invalid_dir_input.value)
                # Move/delete binlerce dosyada uzun sürer — thread'e at.
                ar = await asyncio.to_thread(
                    dedup_apply_action,
                    sr,
                    action=action_select.value,
                    invalid_dir=resolved_invalid_dir,
                    keep_strategy="first",  # zaten manuel keeper'ı başa aldık
                    dry_run=dryrun_check.value,
                )

                report_path = Path(_report_path(DEDUP_REPORT_NAME, STATE.dataset_path))

                _safe_set_text(progress_label, "Rapor yazılıyor…")
                cfg = _build_config()
                await asyncio.to_thread(
                    dedup_write_report,
                    report_path,
                    scan_result=sr,
                    action_result=ar,
                    recursive=recursive_check.value,
                    config=cfg,
                )
                _safe_set_value(undo_input, str(report_path))
                STATE.last_report_paths[2] = str(report_path)
                if action_select.value != "none" and not dryrun_check.value:
                    _append_manifest_from_report(2, report_path)

                dryrun_tag = " (DRY-RUN)" if dryrun_check.value else ""
                if action_select.value == "move":
                    msg = f"Taşınan: {len(ar.entries)}{dryrun_tag} → {ar.invalid_dir}"
                elif action_select.value == "delete":
                    msg = f"Silinen: {len(ar.entries)}{dryrun_tag}"
                else:
                    msg = f"Sadece raporlandı: {len(sr.groups)} grup"
                _safe_set_text(summary_label, f"{msg}\nRapor: {report_path}")
                _safe_notify(msg, type="positive" if not dryrun_check.value else "info")
                STATE.notify_change()
            except Exception as e:
                _safe_notify(f"Aksiyon hatası: {e}", type="negative")
            finally:
                _safe_set_visible(progress_bar, False)
                _safe_set_text(progress_label, "")
                _safe_enable(apply_btn)

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
