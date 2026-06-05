"""06 — Caption: Qwen3-VL multi-pass caption + onay/export."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import asyncio
import time

from nicegui import ui
from caption_core import batch_client as caption_batch_client
from caption_core.batch_client import (  # noqa: E402
    SUPPORTED_EXTENSIONS as CAPTION_SUPPORTED_EXTENSIONS,
    check_server_health as caption_check_server_health,
)
from caption_core.json_to_txt import extract_captions as caption_extract_captions

from webui.state import STATE
from webui.helpers import (
    _path_to_url,
)


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

                # Dataset path: header'dan implicit (tek truth source).

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
                    cancel_btn = ui.button("Cancel").props(
                        "outline color=negative no-caps"
                    )
                    cancel_btn.disable()
                pass_progress_label = ui.label("").classes(
                    "text-xs font-semibold text-slate-700"
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
            if not STATE.is_valid_dataset():
                return None
            return Path(STATE.dataset_path)

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

        def _format_eta(seconds: float) -> str:
            if seconds <= 0 or seconds != seconds:  # NaN/0
                return "—"
            seconds = int(seconds)
            h, rem = divmod(seconds, 3600)
            m, s = divmod(rem, 60)
            if h:
                return f"{h}h {m}m"
            if m:
                return f"{m}m {s}s"
            return f"{s}s"

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

            # Thread → UI bridge: callback worker thread'inden çağrılır,
            # async poll loop her 0.5s'de okur. Element update'leri ana
            # event loop tarafından yapılır → race yok.
            progress_state: dict = {
                "pass_idx": 0,
                "total_passes": len(pass_nums) if not export_only else 0,
                "current": 0,
                "total": 0,
                "msg": "Başlatılıyor…",
                "success": 0,
                "skipped": 0,
                "failed": 0,
            }

            def _progress_cb(pi: int, tp: int, c: int, t_: int, m: str, stats: dict | None = None):
                progress_state["pass_idx"] = pi
                progress_state["total_passes"] = tp
                progress_state["current"] = c
                progress_state["total"] = t_
                progress_state["msg"] = m
                if stats:
                    progress_state["success"] = stats.get("success", 0)
                    progress_state["skipped"] = stats.get("skipped", 0)
                    progress_state["failed"] = stats.get("failed", 0)

            cancel_event = threading.Event()
            tab_state["cancel"] = cancel_event

            run_btn.disable()
            export_btn.disable()
            cancel_btn.enable()
            progress_bar.visible = True
            progress_bar.set_value(0)
            pass_progress_label.text = ""
            progress_label.text = "Başlatılıyor…"
            start_time = time.time()
            # İlk gerçek inference'ı yakaladığımız an. Skipped'ler hızlı atılır,
            # rate hesabını ilk success'tan itibaren başlatırız ki başta 0/0 NaN
            # ve sonra suni patlamalı eğri olmasın.
            first_success_time: Optional[float] = None

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
                            progress_cb=_progress_cb,
                            cancel_event=cancel_event,
                        )
                    if not cancel_event.is_set():
                        caption_extract_captions(str(d), ctype, overwrite=False)
                except Exception as e:  # noqa: BLE001
                    error_holder["err"] = str(e)

            t = threading.Thread(target=_worker, daemon=True)
            tab_state["thread"] = t
            t.start()

            # Periyodik UI refresh — element update ana event loop'ta
            while t.is_alive():
                pi = progress_state["pass_idx"]
                tp = progress_state["total_passes"]
                cur = progress_state["current"]
                tot = progress_state["total"]
                msg = progress_state["msg"]
                succ = progress_state["success"]
                skip = progress_state["skipped"]
                fail = progress_state["failed"]

                # Pass-aware overall progress: tüm pass'lar boyunca toplam iş
                if tp > 0 and tot > 0 and pi > 0:
                    total_work = tp * tot
                    done_work = (pi - 1) * tot + cur
                    progress_bar.set_value(done_work / total_work)

                    # Rate hesabı sadece "gerçek inference" (success) üzerinden.
                    # Skipped'ler milisaniyede dönüyor; bunları paya koyarsak rate
                    # uçar, sonra çöker → kullanıcı için yanıltıcı ETA.
                    if succ > 0:
                        if first_success_time is None:
                            first_success_time = time.time()
                        # İlk success'a kadar geçen skipped süresini at: rate ilk
                        # success'tan itibaren bizimle, daha kararlı.
                        inference_elapsed = time.time() - first_success_time
                        rate = succ / inference_elapsed if inference_elapsed > 0 else 0
                    else:
                        rate = 0

                    # ETA: kalan işin tahmini gerçek inference kısmını rate'e böl.
                    # Şu ana kadar gördüğümüz skipped oranını gelecek işe extrapolate
                    # ediyoruz — overwrite=False ile sık görülen rerun senaryosunda
                    # tutarlı tahmin verir.
                    total_done = succ + skip + fail
                    skipped_ratio = (skip / total_done) if total_done > 0 else 0
                    remaining_total = total_work - done_work
                    projected_real_remaining = remaining_total * (1 - skipped_ratio)
                    eta = projected_real_remaining / rate if rate > 0 else 0

                    rate_str = f"{rate:.2f} img/s" if rate > 0 else "—"
                    skipped_str = f" • {skip} atlandı" if skip > 0 else ""
                    pass_progress_label.text = (
                        f"Pass {pi}/{tp} • {cur}/{tot} img{skipped_str} • "
                        f"{rate_str} • ETA {_format_eta(eta)}"
                    )
                else:
                    pass_progress_label.text = ""
                progress_label.text = msg
                if cancel_event.is_set():
                    progress_label.text = msg + "  (iptal isteği gönderildi…)"
                await asyncio.sleep(0.5)

            t.join()

            progress_bar.visible = False
            cancel_btn.disable()
            run_btn.enable()
            export_btn.enable()

            if cancel_event.is_set():
                progress_label.text = "İptal edildi"
                pass_progress_label.text = ""
                ui.notify("Captioning iptal edildi", type="warning")
                _refresh_gallery()
                return

            if error_holder["err"]:
                progress_label.text = f"Hata: {error_holder['err']}"
                ui.notify(f"Captioning hatası: {error_holder['err']}", type="negative")
                return

            elapsed_total = time.time() - start_time
            progress_label.text = f"✓ Tamam — {_format_eta(elapsed_total)}"
            pass_progress_label.text = ""
            # Rapor yolu otomatik undo'ya doldur
            STATE.last_report_paths[6] = str(d / "caption_report.json")
            undo_input.value = STATE.last_report_paths[6]
            ui.notify("Caption + export tamamlandı", type="positive")

        def _do_cancel():
            ev = tab_state.get("cancel")
            if ev is None or not isinstance(ev, threading.Event):
                ui.notify("Aktif iş yok", type="warning")
                return
            if ev.is_set():
                ui.notify("İptal zaten gönderildi", type="info")
                return
            ev.set()
            cancel_btn.disable()
            ui.notify(
                "İptal sinyali gönderildi — mevcut görseller bitince durur",
                type="info",
            )
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
        cancel_btn.on("click", _do_cancel)
        refresh_btn.on("click", _refresh_gallery)
        undo_btn.on("click", _do_undo)

        # Tab açılınca / state değişince mevcut caption'ları göster
        STATE.on_change(_refresh_gallery)
        _refresh_gallery()
