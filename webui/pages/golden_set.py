"""07 — Golden Set: quality + caption-aware cherry-pick."""
from __future__ import annotations

from pathlib import Path

from nicegui import ui
from goldenset_core import (  # noqa: E402
    apply_selection as golden_apply_selection,
    parse_distribution as golden_parse_distribution,
    select as golden_select,
    undo_from_report as golden_undo_from_report,
    write_report as golden_write_report,
)

from webui.state import STATE
from webui.helpers import (
    _report_path,
    _append_manifest_from_report,
    _path_to_url,
)
from webui.browse import _open_browse_dialog


def build_golden_set_tab():
    """07 — Golden Set: quality+caption-aware cherry-pick form.

    Form: source dataset + quality_report + count + distribution +
    character + face-target + recursive + dry-run + force. Run sonucu:
    selection stats (avg score, face count, bucket dağılım) + apply
    sonucu (kaç kopyalandı). Tree-preserving copy (recursive aktifken).
    """
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

                # Source dataset: header'dan implicit (tek truth source).

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
            if not STATE.is_valid_dataset():
                ui.notify(
                    "Dataset yolu geçerli değil (header'da doğrula)",
                    type="warning",
                )
                return
            out = (out_input.value or "").strip()
            rep = (rep_input.value or "").strip()
            if not out or not rep:
                ui.notify("Output ve Report gerekli", type="warning")
                return
            src_p = Path(STATE.dataset_path)
            out_p = Path(out)
            rep_p = Path(rep)
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
                progress_label.text = "Hata: target dolu (force kullan)"
                run_btn.enable()
                ui.notify(str(e), type="negative")
                return
            except Exception as e:  # noqa: BLE001
                progress_label.text = f"Apply hatası: {e}"
                run_btn.enable()
                ui.notify(f"Apply hatası: {e}", type="negative")
                return

            # Rapor
            report_out = Path(_report_path("selection_report.json", str(out_p)))
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
                if not dryrun_check.value:
                    _append_manifest_from_report(7, rp, output_dir=str(out_p))

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
