"""LechuPasto: the task-oriented companion to Lechu.

Home = two cards (Chat, Tareas). Tareas = one card per task plus "Crear nueva
tarea". A task opens its folder of runs with the report shown inline. The chat
is a simple read-only assistant (Gmail/Drive/Calendar + reminders).

Run:  python3 lechupasto/app.py   (LECHUPASTO_DEV=1 serves in a browser instead of a native window)
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from nicegui import app, run, ui  # noqa: E402

import core.tools  # noqa: E402,F401  (registers every tool the chat agent can use)
from config import CONFIG  # noqa: E402
from core.agents import load_agents  # noqa: E402
from core.llm import OllamaClient  # noqa: E402
from core.tool_loop import Continue, PendingConfirmation, step_agent_stream  # noqa: E402
from lechupasto import engine  # noqa: E402

PORT = 8001
HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
REQUESTS_DIR = engine.TASKS_DIR / "_pedidos"
DAY_LABELS = {"mon": "lun", "tue": "mar", "wed": "mié", "thu": "jue", "fri": "vie", "sat": "sáb", "sun": "dom"}
MARK = "/assets/lechupasto_mark.svg"

app.add_static_files("/runs", engine.TASKS_DIR)
app.add_static_files("/assets", ASSETS)

class _FastClient(OllamaClient):
    """qwen3 "thinks" by default, which made a simple calendar question take
    ~40s. Thinking showed no routing gain in this project's benchmark, so the
    chat turns it off."""

    def chat_stream(self, model, messages, tools=None, think=None):
        return super().chat_stream(model, messages, tools, think=False)


_client: OllamaClient | None = None


def _ollama() -> OllamaClient:
    global _client
    if _client is None:
        _client = _FastClient(CONFIG.ollama_base_url)
    return _client


def _schedule_text(task: engine.Task) -> str:
    sched = task.schedule
    if not sched:
        return "Solo manual"
    return f"{', '.join(DAY_LABELS[d] for d in sched.get('days', []))} · {sched.get('time', '')}"


def _last_run_text(task: engine.Task) -> str:
    runs = engine.list_runs(task)
    if not runs:
        return "Sin corridas todavía"
    meta = engine.run_meta(task, runs[0])
    stamp = datetime.fromisoformat(meta["generated"]).strftime("%d/%m %H:%M") if meta.get("generated") else runs[0]
    return f"Última: {stamp}" + (" · enviada" if meta.get("delivered") else "")


def _run_label(task: engine.Task, run_id: str) -> str:
    meta = engine.run_meta(task, run_id)
    stamp = datetime.fromisoformat(meta["generated"]).strftime("%d/%m %H:%M") if meta.get("generated") else run_id
    return f"{stamp}  ({'programada' if meta.get('scheduled') else 'manual'}{' · enviada' if meta.get('delivered') else ''})"


# ---------------------------------------------------------------- cards

def _card(icon: str, title: str, subtitle: str, on_click, dashed: bool = False, big: bool = False) -> None:
    size = "width: 300px; height: 190px" if big else "width: 270px; height: 160px"
    border = "border: 2px dashed #c9b79c; background: transparent" if dashed else "background: #fff"
    with ui.card().classes("cursor-pointer items-center justify-center text-center gap-1 hover:shadow-lg transition-shadow") \
            .style(f"{size}; {border}; border-radius: 16px").on("click", on_click):
        ui.icon(icon, size="44px" if big else "36px", color="primary")
        ui.label(title).classes("text-lg font-bold")
        ui.label(subtitle).classes("text-xs text-grey-7").style("white-space: pre-line")


def _back_button(nav: dict, target: str, label: str) -> None:
    ui.button(label, icon="arrow_back", on_click=lambda: _go(nav, target)).props("flat dense no-caps")


def _go(nav: dict, view: str, task_id: str | None = None) -> None:
    nav["view"], nav["task"] = view, task_id
    nav["refresh"]()


# ---------------------------------------------------------------- screens

def _home(nav: dict) -> None:
    with ui.column().classes("w-full items-center gap-6").style("margin-top: 8vh"):
        ui.label("¿Qué hacemos hoy?").classes("text-2xl font-bold")
        with ui.row().classes("gap-6 justify-center"):
            _card("chat", "Chat", "Consultas sobre tus mails, agenda y Drive", lambda: _go(nav, "chat"), big=True)
            _card("task_alt", "Tareas", "Reportes programados y su historial", lambda: _go(nav, "tasks"), big=True)


def _tasks_menu(nav: dict) -> None:
    _back_button(nav, "home", "Inicio")
    ui.label("Tareas").classes("text-xl font-bold")
    with ui.row().classes("gap-5 flex-wrap"):
        for task in engine.load_tasks().values():
            _card("summarize", task.name, f"{_schedule_text(task)}\n{_last_run_text(task)}",
                  lambda t=task: _go(nav, "task", t.id))
        _card("add_circle_outline", "Crear nueva tarea", "Describí lo que querés automatizar",
              lambda: _go(nav, "new-task"), dashed=True)


def _new_task(nav: dict) -> None:
    _back_button(nav, "tasks", "Tareas")
    ui.label("Crear nueva tarea").classes("text-xl font-bold")
    ui.label("Contá qué querés que haga la tarea, cuándo y qué querés ver en el reporte. Se guarda como un pedido y la "
             "diseñamos juntos con Claude Code: ahí se arma su pipeline y aparece acá como una tarea más.") \
        .classes("text-sm text-grey-7").style("max-width: 640px")
    name = ui.input("Nombre corto", placeholder="Ej: Seguimiento de pagos").props("outlined dense").classes("w-96")
    prompt = ui.textarea("¿Qué debería hacer?", placeholder="Ej: Todos los viernes a las 18, revisar los mails con «factura» "
                         "de la semana y armarme una lista de lo que hay que pagar.").props("outlined").classes("w-full").style("max-width: 640px")

    @ui.refreshable
    def pending() -> None:
        files = sorted(REQUESTS_DIR.glob("*.md"), reverse=True) if REQUESTS_DIR.exists() else []
        if not files:
            return
        ui.separator().classes("my-2")
        ui.label("Pedidos guardados (esperando diseño)").classes("text-xs font-bold text-grey-7 uppercase")
        for path in files:
            first = path.read_text(encoding="utf-8").splitlines()[0].lstrip("# ")
            ui.label(f"• {first}").classes("text-sm")

    def _save() -> None:
        if not (name.value or "").strip() or not (prompt.value or "").strip():
            ui.notify("Completá el nombre y qué debería hacer", type="warning")
            return
        REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", name.value.lower()).strip("-") or "tarea"
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        (REQUESTS_DIR / f"{stamp}-{slug}.md").write_text(f"# {name.value.strip()}\n\n{prompt.value.strip()}\n", encoding="utf-8")
        name.value = prompt.value = ""
        pending.refresh()
        ui.notify("Pedido guardado. Pasámelo en Claude Code y lo armamos.", type="positive")

    ui.button("Guardar pedido", icon="save", on_click=_save).props("unelevated color=primary no-caps")
    pending()


def _task_screen(nav: dict, task: engine.Task) -> None:
    state = {"run": None}
    _back_button(nav, "tasks", "Tareas")

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
            ui.label(task.name).classes("text-xl font-bold")
            ui.chip(_schedule_text(task), icon="schedule").props("dense outline")
            ui.label(task.description).classes("text-sm text-grey-7 grow")

        with ui.row().classes("w-full no-wrap gap-4").style("height: calc(100vh - 170px)"):
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


def _chat_screen(nav: dict, chat: dict) -> None:
    agent = load_agents(HERE / "agents")["pasto_chat"]
    _back_button(nav, "home", "Inicio")

    with ui.column().classes("w-full gap-2").style("height: calc(100vh - 150px)"):
        scroll = ui.scroll_area().classes("w-full grow")
        with scroll:
            container = ui.column().classes("w-full gap-2")
            with container:
                if len(chat["messages"]) <= 1:
                    ui.label("Preguntame por tus mails, tu agenda o tu Drive. Por ejemplo: «¿qué eventos tengo esta semana?» "
                             "o «¿quién me escribió hoy?». También puedo dejarte recordatorios.").classes("text-grey-6 text-sm")
                for msg in chat["messages"]:
                    if msg["role"] == "user":
                        ui.chat_message(msg["content"], sent=True, name="Vos")
                    elif msg["role"] == "assistant" and msg.get("content"):
                        with ui.chat_message(name="Lechu", avatar=MARK):
                            ui.markdown(msg["content"])

        async def _send() -> None:
            text = (box.value or "").strip()
            if not text or chat["busy"]:
                return
            box.value = ""
            chat["busy"] = True
            send_btn.disable()
            now = datetime.now().astimezone()
            chat["messages"][0] = {"role": "system", "content":
                                   f"{agent.system_prompt}\n\nCurrent date and time: {now.strftime('%A %Y-%m-%d %H:%M')} ({now.tzname()})."}
            chat["messages"].append({"role": "user", "content": text})
            with container:
                ui.chat_message(text, sent=True, name="Vos")
                with ui.chat_message(name="Lechu", avatar=MARK):
                    md = ui.markdown("_Pensando…_")
            scroll.scroll_to(percent=1.0)
            failed: dict = {}
            answer = ""
            try:
                for _ in range(CONFIG.max_tool_iterations):
                    chunks, result_box = await step_agent_stream(_ollama(), agent, chat["messages"], failed)
                    async for piece in chunks:
                        answer += piece
                        md.set_content(answer)
                    result = result_box["result"]
                    if isinstance(result, Continue):
                        answer = ""
                        continue
                    if isinstance(result, PendingConfirmation):
                        answer = "Esa acción necesita confirmación y desde acá solo puedo consultar. Hacela desde Lechu."
                        chat["messages"].append({"role": "assistant", "content": answer})
                    break
                else:
                    answer = "Me detuve después de demasiadas consultas. Probá con un pedido más simple."
                    chat["messages"].append({"role": "assistant", "content": answer})
                md.set_content(answer or "_(sin respuesta)_")
            except httpx.HTTPError as exc:
                md.set_content(f"No pude contactar a Ollama: {exc}")
            except Exception as exc:  # noqa: BLE001
                md.set_content(f"Error inesperado: {type(exc).__name__}: {exc}")
            finally:
                chat["busy"] = False
                send_btn.enable()
                scroll.scroll_to(percent=1.0)

        with ui.row().classes("w-full no-wrap items-center gap-2"):
            box = ui.input(placeholder="Escribí tu consulta…").props("outlined dense").classes("grow").on("keydown.enter", _send)
            send_btn = ui.button(icon="send", on_click=_send).props("round dense unelevated color=primary")


# ---------------------------------------------------------------- page

@ui.page("/")
def index() -> None:
    ui.colors(primary="#a5693a", secondary="#e8a33d", accent="#c98f52")
    ui.add_css("""
    .q-message-text--received { background: #ffffff !important; color: #34363c !important; }
    .q-message-text--received:last-child:before { border-right-color: #ffffff !important; }
    .q-message-text--sent { background: #ead9c3 !important; color: #34363c !important; }
    .q-message-text--sent:last-child:before { border-left-color: #ead9c3 !important; }
    """)
    ui.query("body").style("background:#fbf8f3")
    nav: dict = {"view": "home", "task": None}
    chat: dict = {"messages": [{"role": "system", "content": ""}], "busy": False}

    with ui.row().classes("w-full items-center gap-3 cursor-pointer").on("click", lambda: _go(nav, "home")):
        ui.image(MARK).classes("w-10 h-10")
        ui.label("LechuPasto").classes("text-xl font-bold")

    @ui.refreshable
    def screen() -> None:
        view = nav["view"]
        if view == "tasks":
            _tasks_menu(nav)
        elif view == "new-task":
            _new_task(nav)
        elif view == "task":
            _task_screen(nav, engine.load_tasks()[nav["task"]])
        elif view == "chat":
            _chat_screen(nav, chat)
        else:
            _home(nav)

    nav["refresh"] = screen.refresh
    screen()


def main() -> None:
    dev = bool(os.environ.get("LECHUPASTO_DEV"))
    ui.run(native=not dev, window_size=(1100, 820), port=PORT, title="LechuPasto",
           favicon=str(ASSETS / "lechupasto_mark.svg"), reload=False, show=not dev)


if __name__ in {"__main__", "__mp_main__"}:
    main()
