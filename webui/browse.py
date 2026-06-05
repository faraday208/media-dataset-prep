"""Dizin gözatma (browse) dialog'u."""
from __future__ import annotations

import os

from nicegui import ui

from webui.helpers import (
    _list_subdirs,
)


def _open_browse_dialog(target_input, *, title="Dizin seç", on_select=None):
    """
    Sunucu tarafı dizin tarayıcı dialog'u — kullanıcı tıklayarak gezer,
    "Bu dizini seç" ile target_input'a yazar.

    on_select: opsiyonel callback (path: str) -> None
        Seçim sonrası ek aksiyon (örn. STATE.dataset_path güncelleme).
        Verilmezse sadece input'a yazılır.
    """
    # Başlangıç noktası: mevcut input değeri varsa o, yoksa $HOME, o da yoksa /
    start = target_input.value or os.environ.get("HOME") or "/"
    if not os.path.isdir(start):
        start = os.environ.get("HOME") or "/"

    current = {"path": os.path.abspath(start)}

    with ui.dialog() as dialog, ui.card().classes("w-[800px]"):
        ui.label(title).classes("text-lg font-semibold")

        path_label = ui.label().classes("text-sm font-mono text-slate-700 break-all")
        subdirs_list = ui.column().classes("w-full gap-1 max-h-96 overflow-auto")

        def render():
            path_label.set_text("📁 " + current["path"])
            subdirs_list.clear()
            with subdirs_list:
                # Üst dizine git
                if current["path"] != "/":
                    parent = os.path.dirname(current["path"])
                    with ui.row().classes(
                        "items-center gap-2 cursor-pointer hover:bg-slate-100 p-2 rounded"
                    ).on("click", lambda: navigate(parent)):
                        ui.icon("arrow_upward").classes("text-slate-500")
                        ui.label("..  (üst dizin)").classes("text-sm")

                # Alt dizinler
                for name in _list_subdirs(current["path"]):
                    sub_path = os.path.join(current["path"], name)
                    with ui.row().classes(
                        "items-center gap-2 cursor-pointer hover:bg-slate-100 p-2 rounded"
                    ).on("click", lambda p=sub_path: navigate(p)):
                        ui.icon("folder").classes("text-amber-600")
                        ui.label(name).classes("text-sm")

                if not _list_subdirs(current["path"]):
                    ui.label("(alt klasör yok)").classes(
                        "text-xs italic text-slate-400 p-2"
                    )

        def navigate(new_path):
            current["path"] = new_path
            render()

        def select_current():
            chosen = current["path"]
            target_input.set_value(chosen)
            if on_select:
                on_select(chosen)
            dialog.close()
            ui.notify(f"Seçildi: {chosen}", type="positive")

        with ui.row().classes("w-full justify-between mt-4"):
            ui.button("Cancel", on_click=dialog.close).props(
                "flat color=grey no-caps"
            )
            ui.button("Bu dizini seç", on_click=select_current).props(
                "color=primary no-caps"
            )

        render()

    dialog.open()
