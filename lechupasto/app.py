"""LechuPasto: the task-oriented companion to Lechu. Each task is a tab with
its own folder of runs; the selected run's HTML report is shown inline.

Run:  python3 lechupasto/app.py   (LECHUPASTO_DEV=1 serves in a browser instead of a native window)
"""

from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nicegui import app, run, ui  # noqa: E402

from lechupasto import engine  # noqa: E402

PORT = 8001
ASSETS = Path(__file__).resolve().parent / "assets"
DAY_LABELS = {"mon": "lun", "tue": "mar", "wed": "mié", "thu": "jue", "fri": "vie", "sat": "sáb", "sun": "dom"}

app.add_static_files("/runs", engine.TASKS_DIR)
app.add_static_files("/assets", ASSETS)


def _schedule_text(task: engine.Task) -> str:
    sched = task.schedule
    if not sched:
        return "Solo manual"
    days = ", ".join(DAY_LABELS[d] for d in sched.get("days", []))
    return f"{days} · {sched.get('time', '')}"


def _run_label(task: engine.Task, run_id: str) -> str:
    meta = engine.run_meta(task, run_id)
    stamp = datetime.fromisoformat(meta["generated"]).strftime("%d/%m %H:%M") if meta.get("generated") else run_id
    kind = "programada" if meta.get("scheduled") else "manual"
    sent = " · enviada" if meta.get("delivered") else ""
    return f"{stamp}  ({kind}{sent})"


def _task_panel(task: engine.Task) -> None:
    state = {"run": None}

    @ui.refreshable
    def view() -> None:
        runs = engine.list_runs(task)
        if state["run"] not in runs:
            state["run"] = runs[0] if runs else None
        selected = state["run"]

        async def _run_now() -> None:
            ui.notify("Ejecutando la tarea…", type="info")
            try:
                result = await run.io_bound(engine.run_task, task)
            except Exception as exc:  # noqa: BLE001
                ui.notify(f"La tarea falló: {type(exc).__name__}: {exc}", type="negative", close_button=True)
                return
            state["run"] = result.run_id
            view.refresh()
            ui.notify("Listo", type="positive")

        async def _send() -> None:
            ok = await run.io_bound(engine.deliver, task, engine.result_from_run(task, selected))
            view.refresh()
            ui.notify("Enviada al bot" if ok else "No se pudo enviar", type="positive" if ok else "negative")

        with ui.row().classes("w-full items-center gap-3"):
            ui.label(task.description).classes("text-sm text-grey-7 grow")
            ui.chip(_schedule_text(task), icon="schedule").props("dense outline")

        with ui.row().classes("w-full no-wrap gap-4").style("height: calc(100vh - 190px)"):
            with ui.column().classes("shrink-0 gap-1 overflow-auto h-full").style("width: 230px"):
                ui.label("Corridas").classes("text-xs font-bold text-grey-7 uppercase")
                ui.button("Ejecutar ahora", icon="play_arrow", on_click=_run_now).props("dense unelevated color=primary").classes("w-full")
                ui.button("Abrir carpeta", icon="folder_open",
                          on_click=lambda: subprocess.Popen(["open", str(task.runs_dir)])).props("dense flat no-caps").classes("w-full")
                ui.separator()
                if not runs:
                    ui.label("Todavía no hay corridas.").classes("text-sm text-grey-6")
                for run_id in runs:
                    active = run_id == selected
                    ui.button(_run_label(task, run_id), on_click=lambda r=run_id: (state.update(run=r), view.refresh())) \
                        .props(f"dense no-caps align=left {'unelevated color=primary' if active else 'flat'}").classes("w-full text-xs")

            with ui.column().classes("grow h-full gap-2").style("min-width: 0"):
                if selected is None:
                    ui.label("Ejecutá la tarea para generar el primer reporte.").classes("text-grey-6")
                    return
                with ui.row().classes("items-center gap-2"):
                    ui.button("Abrir en el navegador", icon="open_in_new",
                              on_click=lambda: webbrowser.open(f"http://127.0.0.1:{PORT}/runs/{task.id}/runs/{selected}.html")) \
                        .props("dense flat no-caps")
                    ui.button("Enviar al bot", icon="send", on_click=_send).props("dense flat no-caps")
                mtime = int((task.runs_dir / f"{selected}.html").stat().st_mtime)
                with ui.element("div").classes("w-full grow flex justify-center").style("background:#ece3d6; border-radius:8px; overflow:auto"):
                    ui.element("iframe").props(f'src="/runs/{task.id}/runs/{selected}.html?v={mtime}"') \
                        .style("width: 500px; height: 100%; border: 0; background: #faf4ec")

    view()


@ui.page("/")
def index() -> None:
    ui.colors(primary="#a5693a", secondary="#e8a33d", accent="#c98f52")
    ui.query("body").style("background:#fbf8f3")
    tasks = engine.load_tasks()

    with ui.row().classes("w-full items-center gap-3"):
        ui.image("/assets/lechupasto_mark.svg").classes("w-10 h-10")
        ui.label("LechuPasto").classes("text-xl font-bold")

    if not tasks:
        ui.label(f"No hay tareas en {engine.TASKS_DIR}").classes("text-grey-6")
        return

    with ui.tabs().classes("w-full") as tabs:
        tab_refs = {tid: ui.tab(t.name) for tid, t in tasks.items()}
    with ui.tab_panels(tabs, value=tab_refs[next(iter(tasks))]).classes("w-full bg-transparent"):
        for tid, task in tasks.items():
            with ui.tab_panel(tab_refs[tid]).classes("p-0 pt-3"):
                _task_panel(task)


def main() -> None:
    dev = bool(os.environ.get("LECHUPASTO_DEV"))
    ui.run(native=not dev, window_size=(1100, 820), port=PORT, title="LechuPasto",
           favicon=str(ASSETS / "lechupasto_mark.svg"), reload=False, show=not dev)


if __name__ in {"__main__", "__mp_main__"}:
    main()
