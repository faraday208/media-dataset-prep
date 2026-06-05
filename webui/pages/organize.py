"""00 — Organize: tip-bazlı rename + relocate + undo."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Optional
import asyncio
import json
import os

from nicegui import ui
import media_organizer

from webui.state import STATE
from webui.helpers import (
    _safe_call,
    _safe_set_value,
    _safe_set_text,
    _safe_set_visible,
    _safe_enable,
    _safe_disable,
    _safe_notify,
    _report_path,
    _append_manifest_from_report,
)
from webui.browse import _open_browse_dialog


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

                def _restore_prefix_from_memory():
                    """Resume: hafızadaki son organize prefix'ini doldur (alan boşsa)."""
                    p = (STATE.last_stage_params.get(0) or {}).get("prefix")
                    if p and not prefix_input.value:
                        prefix_input.set_value(p)
                STATE.on_change(_restore_prefix_from_memory)
                _restore_prefix_from_memory()

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

                # Resume restore sırasında _sync_mode_options'ın auto-switch +
                # notify yan etkilerini bastırmak için bayrak.
                _restoring = {"active": False}

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
                        if mode_select.value == "rename" and not _restoring["active"]:
                            mode_select.value = "copy"
                            ui.notify(
                                "Flat mod in-place'i desteklemiyor — Copy'ye geçildi",
                                type="info",
                            )
                    else:
                        mode_select.options = MODE_OPTIONS_ALL
                        # Off: "tek klasörde topla" akışı için boş output'ta Copy'ye
                        # geçip 'organized' öner (flat ile tutarlı UX). In-place hâlâ
                        # elle seçilebilir.
                        if (
                            recursive_value == "none"
                            and mode_select.value == "rename"
                            and not output_input.value
                            and not _restoring["active"]
                        ):
                            mode_select.value = "copy"
                            ui.notify(
                                "Off + Copy → 'organized' klasörüne toplanır",
                                type="info",
                            )
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

                def _restore_config_from_memory():
                    """Resume: önceki organize reçetesini forma geri yükle —
                    recursive / mode / output_dir / include_ext. Yalnızca alan
                    default'taysa uygulanır (kullanıcının aktif düzenini ezmez);
                    prefix ayrı restore ediliyor. _sync_mode_options'ın auto-switch'i
                    _restoring bayrağıyla bastırılır."""
                    prm = STATE.last_stage_params.get(0) or {}
                    if not prm:
                        return
                    _restoring["active"] = True
                    try:
                        out = prm.get("output_dir")
                        if out and not output_input.value:
                            output_input.set_value(out)
                        if prm.get("include_ext") and not include_ext.value:
                            include_ext.set_value(True)
                        rec = prm.get("recursive")
                        if (
                            rec in {"none", "flat", "tree"}
                            and recursive_select.value == "none"
                        ):
                            recursive_select.set_value(rec)
                            _sync_mode_options(rec)  # mode options sync (auto-switch bastırılı)
                        mode = prm.get("mode")
                        if (
                            mode
                            and mode_select.value == "rename"
                            and mode in mode_select.options
                        ):
                            mode_select.set_value(mode)
                    finally:
                        _restoring["active"] = False

                STATE.on_change(_restore_config_from_memory)
                _restore_config_from_memory()

                with ui.row().classes("gap-2 mt-2 w-full items-center"):
                    run_btn = ui.button("Organize").props("color=primary no-caps")
                    dryrun_check = ui.checkbox("Dry-run", value=True)
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
                    "rename_report.json yolu",
                    placeholder="(run sonrası otomatik dolar)",
                ).props("dense outlined").classes("w-full")

                def _restore_undo_from_memory():
                    """Resume: hafızadaki rename_report.json yolunu undo alanına doldur
                    (alan boşsa). Rapor diskte + manifest'te kayıtlı."""
                    rp = STATE.last_report_paths.get(0)
                    if rp and not undo_input.value:
                        undo_input.set_value(rp)
                STATE.on_change(_restore_undo_from_memory)
                _restore_undo_from_memory()

                cleanup_check = ui.checkbox("Cleanup empty dirs", value=False)
                with ui.row().classes("gap-2"):
                    undo_preview_btn = ui.button("Preview Undo").props(
                        "outline color=primary no-caps"
                    )
                    undo_btn = ui.button("Undo").props(
                        "outline color=grey-7 no-caps"
                    )

            # Sağ kolon: özet + preview tablosu
            with ui.card().classes("w-full"):
                with ui.row().classes("items-center justify-between w-full"):
                    ui.label("Preview").classes(
                        "text-sm uppercase text-slate-500 tracking-wide"
                    )
                summary_label = ui.label(
                    "Henüz preview üretilmedi — sol panelde Dry-run açıkken Organize'a tıkla."
                ).classes("text-sm text-slate-600 italic mt-1")

                # Stat kartları — işlem sonucu: Total / Başarı / Error. Başarı+Error
                # ancak gerçek Organize (execute) sonrası dolar; dry-run preview'da
                # "—" kalır (henüz dosya işlenmedi). execute_rename sayaçları döndürür.
                with ui.row().classes("w-full justify-around mt-2"):
                    with ui.column().classes("items-center gap-0"):
                        total_card = ui.label("—").classes(
                            "text-3xl font-bold text-slate-700"
                        )
                        ui.label("Total").classes(
                            "text-xs uppercase text-slate-500 tracking-wide"
                        )
                    with ui.column().classes("items-center gap-0"):
                        ok_card = ui.label("—").classes(
                            "text-3xl font-bold text-green-600"
                        )
                        ui.label("Başarı").classes(
                            "text-xs uppercase text-slate-500 tracking-wide"
                        )
                    with ui.column().classes("items-center gap-0"):
                        err_card = ui.label("—").classes(
                            "text-3xl font-bold text-red-600"
                        )
                        ui.label("Error").classes(
                            "text-xs uppercase text-slate-500 tracking-wide"
                        )

                ui.separator().classes("my-2")

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
            # .get → hem canlı plan hem kaydedilmiş rapordaki renames için dayanıklı.
            preview_table.rows = [
                {
                    "ext": p.get("extension", "—"),
                    "old": p.get("old_filename", "—"),
                    "new": p.get("new_filename", "—"),
                    "src": p.get("time_source", "—"),
                    "subdir": p.get("subdir", "—"),
                }
                for p in plan
            ]
            preview_table.update()
            # Total = planlanan dosya. Başarı/Error işlem sonucu olduğundan burada
            # "—"ye sıfırlanır; _set_result_cards (execute/resume sonrası) doldurur.
            total_card.set_text(str(len(plan)))
            ok_card.set_text("—")
            err_card.set_text("—")

        def _set_result_cards(success, error) -> None:
            """Gerçek Organize (execute) veya resume sonrası başarı/error kartlarını
            doldur. None → '—' (sonuç bilinmiyor, ör. eski rapor)."""
            ok_card.set_text("—" if success is None else str(success))
            err_card.set_text("—" if error is None else str(error))

        def _restore_preview_from_memory():
            """Resume: organize zaten yapılmışsa kaydedilmiş rapordan preview
            TABLOSUNU + stat kartlarını + '✓ tamamlandı' özetini (son organize
            zamanıyla) geri yükle — yeniden tarama YOK. Canlı dry-run sonucunu ezmez."""
            rp = STATE.last_report_paths.get(0)
            if not rp:
                return
            cur = summary_label.text or ""
            if "Henüz preview" not in cur and not cur.startswith("✓ Organize"):
                return
            try:
                data = json.loads(Path(rp).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return
            renames = data.get("renames")
            if isinstance(renames, list) and renames:
                _populate_preview(renames)  # tablo + kartları kaydedilmiş rapordan doldur
                count = len(renames)
            else:
                count = data.get("total_files")
            prm = STATE.last_stage_params.get(0) or {}
            # Başarı/Error manifest params'tan (eski raporlarda yoksa "—" kalır)
            _set_result_cards(prm.get("success"), prm.get("error"))
            parts = []
            if count is not None:
                parts.append(f"{count} dosya")
            if prm.get("prefix"):
                parts.append(f"prefix={prm['prefix']}")
            if prm.get("mode"):
                parts.append(f"mode={prm['mode']}")
            detail = " · ".join(parts) if parts else "kayıt mevcut"
            ts = data.get("timestamp")
            when = f"\nSon organize: {str(ts)[:19].replace('T', ' ')}" if ts else ""
            summary_label.set_text(f"✓ Organize tamamlandı — {detail}{when}")

        STATE.on_change(_restore_preview_from_memory)
        _restore_preview_from_memory()

        def _summarize_plan(plan, *, executed: bool, mode: str = "") -> str:
            """Plan üzerine özet — dosya sayısı + sort-time kaynak dağılımı."""
            src_counts = Counter(p.get("time_source", "?") for p in plan)
            src_breakdown = ", ".join(
                f"{c} via {s}" for s, c in sorted(src_counts.items())
            )
            verb = f"✓ {len(plan)} dosya işlendi (mode={mode})" if executed else \
                   f"Preview: {len(plan)} dosya planlandı (henüz uygulanmadı)"
            return f"{verb}\nSort-time: {src_breakdown}"

        async def on_preview():
            err = _validate_inputs()
            if err:
                ui.notify(err, type="negative")
                return
            # Büyük dizinlerde scan_directory + generate_*_plan main thread'i
            # blok edip WebSocket heartbeat'i öldürüyordu — thread'e at.
            run_btn.disable()
            try:
                _safe_set_text(summary_label, "Plan oluşturuluyor…")
                plan = await asyncio.to_thread(_build_plan)
                _populate_preview(plan)
                _safe_set_text(summary_label, _summarize_plan(plan, executed=False))
                _safe_notify(f"{len(plan)} dosya için plan oluşturuldu", type="info")
            except Exception as e:
                _safe_notify(f"Hata: {e}", type="negative")
            finally:
                _safe_enable(run_btn)

        async def _do_execute(plan):
            """Asıl execute mantığı — conflict onayı sonrası burada toplanır.

            Blocking I/O (rename/copy/move + report yazımı) `asyncio.to_thread` ile
            arka plana atılır; UI thread serbest kalır, WebSocket heartbeat kesilmez.
            """
            mode = mode_select.value
            _safe_disable(run_btn)
            _safe_set_value(progress_bar, 0)
            _safe_set_visible(progress_bar, True)
            _safe_set_text(progress_label, "Hazırlanıyor…")
            try:
                def _cb(current: int, total: int, msg: str):
                    # Worker thread → UI: NiceGUI element update'leri thread-safe
                    # değil ama set_value/set_text basit attribute set'i; kritik
                    # senaryolarda zaten _safe wrapper RuntimeError'u yutuyor.
                    if total > 0:
                        _safe_set_value(progress_bar, current / total)
                    _safe_set_text(progress_label, msg)

                await asyncio.sleep(0)
                result = await asyncio.to_thread(
                    media_organizer.execute_rename,
                    plan,
                    dry_run=False,
                    mode=mode,
                    progress_cb=_cb,
                )
                result = result or {}
                success = result.get("success")
                error = result.get("error")
                _safe_call(_set_result_cards, success, error)

                # Rapor PROJE KÖKÜNDE toplanır (base_path) — aktif dataset_path
                # (organized) değil; tüm stage'lerle ortak report/ klasörü.
                report_path = _report_path("rename_report.json", STATE.base_path)
                _safe_set_text(progress_label, "Rapor yazılıyor…")
                await asyncio.to_thread(
                    media_organizer.save_report, plan, report_path, mode=mode
                )
                STATE.last_report_paths[0] = report_path
                _append_manifest_from_report(
                    0, report_path,
                    output_dir=output_input.value or STATE.dataset_path,
                    params={"prefix": prefix_input.value,
                            "recursive": recursive_select.value, "mode": mode,
                            "include_ext": include_ext.value,
                            "output_dir": output_input.value or None,
                            "success": success, "error": error},
                )
                _safe_set_value(undo_input, report_path)
                _safe_set_text(
                    summary_label,
                    _summarize_plan(plan, executed=True, mode=mode)
                    + f"\nRapor: {report_path}",
                )
                _safe_notify(f"{len(plan)} dosya işlendi", type="positive")
                # Copy/move modunda yeni output klasörü pipeline'a "alternatif dataset"
                # olarak sunulur — banner üzerinden kullanıcı isterse switch eder.
                if mode in ("copy", "move") and output_input.value:
                    STATE.register_output(0, output_input.value)
                else:
                    STATE.notify_change()  # Overview'da step 00 ✓ olur
            except Exception as e:
                _safe_notify(f"Execute hatası: {e}", type="negative")
            finally:
                _safe_set_visible(progress_bar, False)
                _safe_set_text(progress_label, "")
                _safe_enable(run_btn)

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

        async def on_execute():
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
                    # Dialog kapanınca _do_execute() coroutine'ini task'a sar:
                    # dialog event handler async-context'i propagate etmez.
                    _show_conflict_dialog(
                        conflicts,
                        lambda: asyncio.create_task(_do_execute(plan)),
                    )
                else:
                    await _do_execute(plan)
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

        async def on_run():
            # Dry-run → plan + preview (dosyaya dokunmaz); kapalı → conflict + execute.
            if dryrun_check.value:
                await on_preview()
            else:
                await on_execute()

        run_btn.on("click", on_run)
        undo_preview_btn.on("click", on_undo_preview)
        undo_btn.on("click", on_undo)
