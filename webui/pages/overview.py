"""Overview sekmesi — pipeline durumu özeti."""
from __future__ import annotations

from nicegui import ui

from webui.state import STATE, PIPELINE_STEPS
from webui.helpers import (
    step_status,
    scan_dataset_stats,
    humanize_bytes,
)


def build_overview_tab():
    with ui.column().classes("w-full max-w-screen-xl mx-auto p-6 gap-4"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("Pipeline Overview").classes("text-2xl font-semibold")
            refresh_btn = ui.button("Refresh").props("flat color=primary no-caps")

        # 🎯 Başlangıç rehberi — yalnızca geçerli dataset seçili DEĞİLken görünür
        onboarding = ui.card().classes(
            "w-full bg-sky-50 border border-sky-300"
        )
        with onboarding:
            ui.label(
                "🎯 Başla buradan — ilk ve en önemli adım: dataset seç"
            ).classes("text-base font-semibold text-sky-900")
            ui.label(
                "1. Üstteki Dataset kutusuna işleyeceğin klasörün yolunu yaz "
                "(📁 ile gözat) ve Validate'e bas.\n"
                "2. İlk kez mi? Ham görsel klasörünü ver; sonra 00 Organize ile temiz "
                "bir organized/ çalışma klasörü üret ve HEP onun üstünde ilerle "
                "(ham/ana klasörde çalışma).\n"
                "3. Devam mı? Proje klasörünü (ya da organized/) ver → report/ "
                "hafızasından kaldığın yer otomatik yüklenir (Overview ✓ + özet)."
            ).classes(
                "text-sm text-sky-900 whitespace-pre-wrap mt-1 leading-relaxed"
            )

        # ⚠️ Çalışma klasörü disiplini — reject'in geri-yutulması tuzağı
        with ui.card().classes("w-full bg-amber-50 border border-amber-300"):
            ui.label("⚠️  Çalışma klasörü disiplini").classes(
                "text-sm font-semibold text-amber-800"
            )
            ui.label(
                "• Ham/ana klasörde ÇALIŞMA. Önce 00 Organize ile ayrı bir çalışma "
                "klasörü üret (örn. organized/) ve hep onun üstünde ilerle.\n"
                "• Reject/duplicates klasörünü çalışma klasörünün İÇİNE değil, DIŞINA "
                "(kardeş klasöre) ver — örn. ../_rejected/02-dup. Recursive default "
                "AÇIK olduğu için içeride kalan reject'i bir sonraki scan GERİ YUTAR.\n"
                "• Her stage'den sonra amber \"Switch\" bandıyla yeni çıktıya geç."
            ).classes(
                "text-sm text-amber-900 whitespace-pre-wrap mt-1 leading-relaxed"
            )

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
            valid = STATE.is_valid_dataset()
            onboarding.set_visibility(not valid)
            stats = scan_dataset_stats(STATE.dataset_path)
            if not valid:
                stats_label.set_text("(henüz seçilmedi — yukarıdaki rehberi izle)")
                ext_label.set_text("—")
            else:
                base = STATE.base_path
                active = STATE.dataset_path
                aktif_line = f"Aktif    : {active}  (manifest)\n" if active != base else ""
                stats_label.set_text(
                    f"Proje    : {base}\n"
                    f"{aktif_line}"
                    f"Toplam   : {stats['total']} medya dosyası (aktif klasör)\n"
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
