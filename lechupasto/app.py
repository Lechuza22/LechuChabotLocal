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
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from nicegui import app, run, ui  # noqa: E402

import core.tools  # noqa: E402,F401  (registers every tool the chat agent can use)
from config import CONFIG  # noqa: E402
from core.agents import load_agents  # noqa: E402
from core.llm import OllamaClient  # noqa: E402
from core.tool_loop import Continue, PendingConfirmation, step_agent_stream  # noqa: E402
from core import reminders as reminder_store  # noqa: E402
from lechupasto import chats, engine  # noqa: E402

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
            _card("alarm", "Recordatorios", "Avisos programados y notas", lambda: _go(nav, "reminders"), big=True)


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


def _ignoring_deleted(fn, *args) -> None:
    """UI updates can target elements already destroyed (user navigated away
    while an answer was streaming); the turn must still finish and be saved."""
    try:
        fn(*args)
    except RuntimeError:
        pass


def _chat_messages(chat: dict, chat_id: int) -> list[dict]:
    """In-memory message list of a conversation (system slot first), loaded
    from the database the first time it's needed."""
    if chat_id not in chat["msgs"]:
        chat["msgs"][chat_id] = [{"role": "system", "content": ""}] + chats.load_messages(chat_id)
    return chat["msgs"][chat_id]


def _chat_screen(nav: dict, chat: dict) -> None:
    agent = load_agents(HERE / "agents")["pasto_chat"]
    open_tabs = chats.open_chats()
    if not open_tabs:
        chat["active"] = chats.create_chat()
        open_tabs = chats.open_chats()
    if chat.get("active") not in {c["id"] for c in open_tabs}:
        chat["active"] = open_tabs[-1]["id"]
    active = chat["active"]
    messages = _chat_messages(chat, active)

    def _guard_busy() -> bool:
        if chat["busy"]:
            ui.notify("Esperá a que termine la respuesta actual", type="warning")
        return chat["busy"]

    def _switch(chat_id: int) -> None:
        if not _guard_busy():
            chat["active"] = chat_id
            nav["refresh"]()

    def _new() -> None:
        if not _guard_busy():
            chat["active"] = chats.create_chat()
            nav["refresh"]()

    def _close(chat_id: int) -> None:
        if _guard_busy():
            return
        chats.close_chat(chat_id)
        chat["msgs"].pop(chat_id, None)
        nav["refresh"]()

    def _reopen(chat_id: int) -> None:
        if not _guard_busy():
            chats.reopen_chat(chat_id)
            chat["active"] = chat_id
            nav["refresh"]()

    def _forget(chat_id: int) -> None:
        chats.delete_chat(chat_id)
        chat["msgs"].pop(chat_id, None)
        nav["refresh"]()

    with ui.row().classes("w-full items-center gap-2"):
        _back_button(nav, "home", "Inicio")
        ui.element("div").classes("grow")
    tab_labels: dict[int, ui.label] = {}
    with ui.row().classes("w-full items-center gap-1 no-wrap").style("overflow-x: auto"):
        for tab in open_tabs:
            is_active = tab["id"] == active
            with ui.row().classes("items-center no-wrap gap-0").style(
                "border-radius: 8px 8px 0 0; padding: 0 2px 0 10px; "
                + ("background:#fff; border-bottom: 3px solid #a5693a" if is_active else "background:#f1e8da")
            ):
                tab_labels[tab["id"]] = ui.label(tab["title"]).classes("text-sm cursor-pointer whitespace-nowrap")                     .style("max-width: 190px; overflow: hidden; text-overflow: ellipsis")                     .on("click", lambda _e, c=tab["id"]: _switch(c))
                ui.button(icon="close", on_click=lambda c=tab["id"]: _close(c)).props("flat round dense size=xs")
        ui.button(icon="add", on_click=_new).props("flat round dense").tooltip("Nuevo chat")
        archived = chats.archived_chats()
        with ui.button(icon="history").props("flat round dense").tooltip("Chats anteriores"):
            with ui.menu():
                if not archived:
                    ui.menu_item("No hay chats anteriores").props("disable")
                for old in archived:
                    stamp = datetime.fromisoformat(old["updated_at"]).strftime("%d/%m")
                    with ui.menu_item(on_click=lambda c=old["id"]: _reopen(c)):
                        ui.label(f"{old['title']}  ·  {stamp}").classes("text-sm")
                        ui.space()
                        ui.button(icon="delete_outline", on_click=lambda c=old["id"]: _forget(c)).props("flat round dense size=xs") \
                            .on("click.stop", lambda: None)

    with ui.column().classes("w-full gap-2").style("height: calc(100vh - 190px)"):
        scroll = ui.scroll_area().classes("w-full grow")
        with scroll:
            container = ui.column().classes("w-full gap-2")
            with container:
                if len(messages) <= 1:
                    ui.label("Preguntame por tus mails, tu agenda o tu Drive. Por ejemplo: «¿qué eventos tengo esta semana?» "
                             "o «¿quién me escribió hoy?». También puedo dejarte recordatorios y guardar notas.").classes("text-grey-6 text-sm")
                for msg in messages:
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
            messages[0] = {"role": "system", "content":
                           f"{agent.system_prompt}\n\nCurrent date and time: {now.strftime('%A %Y-%m-%d %H:%M')} ({now.tzname()})."}
            turn_start = len(messages)
            messages.append({"role": "user", "content": text})
            if turn_start == 1:  # first message names the tab
                title = chats.set_title_from(active, text)
                _ignoring_deleted(tab_labels[active].set_text, title)
            with container:
                ui.chat_message(text, sent=True, name="Vos")
                with ui.chat_message(name="Lechu", avatar=MARK):
                    md = ui.markdown("_Pensando…_")
            scroll.scroll_to(percent=1.0)
            failed: dict = {}
            answer = ""
            try:
                for _ in range(CONFIG.max_tool_iterations):
                    chunks, result_box = await step_agent_stream(_ollama(), agent, messages, failed)
                    async for piece in chunks:
                        answer += piece
                        _ignoring_deleted(md.set_content, answer)
                    result = result_box["result"]
                    if isinstance(result, Continue):
                        answer = ""
                        continue
                    if isinstance(result, PendingConfirmation):
                        answer = "Esa acción necesita confirmación y desde acá no puedo hacerla. Hacela desde Lechu."
                        messages.append({"role": "assistant", "content": answer})
                    break
                else:
                    answer = "Me detuve después de demasiadas consultas. Probá con un pedido más simple."
                    messages.append({"role": "assistant", "content": answer})
                _ignoring_deleted(md.set_content, answer or "_(sin respuesta)_")
            except httpx.HTTPError as exc:
                _ignoring_deleted(md.set_content, f"No pude contactar a Ollama: {exc}")
            except Exception as exc:  # noqa: BLE001
                _ignoring_deleted(md.set_content, f"Error inesperado: {type(exc).__name__}: {exc}")
            finally:
                await run.io_bound(chats.append_messages, active, messages[turn_start:])
                chat["busy"] = False
                _ignoring_deleted(send_btn.enable)
                _ignoring_deleted(scroll.scroll_to, 1.0)

        with ui.row().classes("w-full no-wrap items-center gap-2"):
            box = ui.input(placeholder="Escribí tu consulta…").props("outlined dense").classes("grow").on("keydown.enter", _send)
            send_btn = ui.button(icon="send", on_click=_send).props("round dense unelevated color=primary")


def _note_dialog(note: dict | None, on_done) -> None:
    """Create (note=None) or edit a note: title + long body."""
    with ui.dialog() as dialog, ui.card().style("width: 640px; max-width: 92vw"):
        ui.label("Nueva nota" if note is None else "Editar nota").classes("text-lg font-bold")
        title = ui.input("Título", value=(note or {}).get("title", "")).props("outlined dense").classes("w-full")
        body = ui.textarea("Contenido", value=(note or {}).get("body", "")).props("outlined input-style='min-height: 220px'").classes("w-full")

        def _save() -> None:
            if not (title.value or "").strip():
                ui.notify("La nota necesita un título", type="warning")
                return
            if note is None:
                reminder_store.add_note(title.value.strip(), (body.value or "").strip())
            else:
                reminder_store.update_note(note["id"], title.value.strip(), (body.value or "").strip())
            dialog.close()
            on_done()

        def _delete() -> None:
            reminder_store.cancel_reminder(note["id"])
            dialog.close()
            on_done()

        with ui.row().classes("w-full justify-end gap-2"):
            if note is not None:
                ui.button("Borrar", icon="delete_outline", on_click=_delete).props("flat no-caps color=negative")
            ui.button("Cancelar", on_click=dialog.close).props("flat no-caps")
            ui.button("Guardar", icon="save", on_click=_save).props("unelevated no-caps color=primary")
    dialog.open()


_WEEKDAYS_ES = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _when_text(due_at: str) -> str:
    due = datetime.strptime(due_at, reminder_store.TIME_FORMAT)
    return f"{_WEEKDAYS_ES[due.weekday()]} {due.strftime('%d/%m %H:%M')}"


def _reminders_screen(nav: dict) -> None:
    _back_button(nav, "home", "Inicio")
    ui.label("Recordatorios y notas").classes("text-xl font-bold")
    ui.label("Lo que cargues acá lo ve el chat, y lo que el chat cree aparece acá. Los recordatorios avisan por notificación "
             "y Telegram aunque la app esté cerrada.").classes("text-sm text-grey-7")

    with ui.tabs().classes("w-full") as tabs:
        tab_rem = ui.tab("Recordatorios")
        tab_notes = ui.tab("Notas")

    @ui.refreshable
    def reminder_list() -> None:
        pending = reminder_store.list_pending()
        if not pending:
            ui.label("No hay recordatorios pendientes.").classes("text-grey-6 text-sm")
        repeat_text = {"daily": "todos los días", "weekly": "todas las semanas"}
        for item in pending:
            with ui.row().classes("w-full items-center no-wrap gap-3").style("background:#fff; border-radius:10px; padding:8px 12px"):
                ui.label(_when_text(item["due_at"])) \
                    .classes("font-bold text-sm").style("min-width: 120px; color:#774c2a")
                ui.label(item["message"]).classes("grow")
                if item["repeat"] in repeat_text:
                    ui.chip(repeat_text[item["repeat"]], icon="repeat").props("dense outline")
                ui.button(icon="delete_outline", on_click=lambda i=item["id"]: (reminder_store.cancel_reminder(i), refresh_all())) \
                    .props("flat round dense").tooltip("Borrar")
        fired = reminder_store.list_fired(8)
        if fired:
            with ui.expansion("Ya avisados", icon="history").classes("w-full text-grey-7"):
                for item in fired:
                    ui.label(f"{item['due_at'][5:16].replace('-', '/', 1)} · {item['message']}").classes("text-sm text-grey-7")

    @ui.refreshable
    def notes_list() -> None:
        notes = reminder_store.list_notes()
        if not notes:
            ui.label("Todavía no hay notas.").classes("text-grey-6 text-sm")
        with ui.row().classes("gap-4 flex-wrap"):
            for note in notes:
                with ui.card().classes("cursor-pointer hover:shadow-lg").style("width: 300px; min-height: 120px; border-radius: 12px; background:#fff") \
                        .on("click", lambda n=note: _note_dialog(n, refresh_all)):
                    ui.label(note["title"]).classes("font-bold")
                    ui.label(note["body"] or "(sin contenido)").classes("text-sm text-grey-7") \
                        .style("display:-webkit-box; -webkit-line-clamp:4; -webkit-box-orient:vertical; overflow:hidden; white-space:pre-line")
                    ui.label(note["updated_at"][:16]).classes("text-xs text-grey-5")

    def refresh_all() -> None:
        reminder_list.refresh()
        notes_list.refresh()

    with ui.tab_panels(tabs, value=tab_rem).classes("w-full bg-transparent"):
        with ui.tab_panel(tab_rem).classes("p-0 pt-3"):
            with ui.row().classes("w-full items-end gap-3").style("background:#fff; border-radius:12px; padding:12px"):
                message = ui.input("Recordame…", placeholder="Ej: llamar al contador").props("outlined dense").classes("grow").style("min-width: 240px")
                soon = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                date = ui.input("Fecha", value=soon.strftime("%Y-%m-%d")).props("outlined dense type=date")
                time_in = ui.input("Hora", value=soon.strftime("%H:%M")).props("outlined dense type=time")
                repeat = ui.select({"none": "No se repite", "daily": "Todos los días", "weekly": "Todas las semanas"}, value="none") \
                    .props("outlined dense")

                def _add() -> None:
                    if not (message.value or "").strip():
                        ui.notify("Escribí qué querés que te recuerde", type="warning")
                        return
                    try:
                        due = reminder_store.parse_when(f"{date.value} {time_in.value}")
                    except ValueError:
                        ui.notify("Fecha u hora inválida", type="warning")
                        return
                    if due <= datetime.now() and repeat.value == "none":
                        ui.notify("Esa fecha y hora ya pasaron", type="warning")
                        return
                    reminder_store.add_reminder(message.value.strip(), due, repeat.value)
                    message.value = ""
                    refresh_all()
                    ui.notify("Recordatorio guardado", type="positive")

                ui.button("Agregar", icon="add", on_click=_add).props("unelevated no-caps color=primary")
            ui.space().classes("h-3")
            reminder_list()
        with ui.tab_panel(tab_notes).classes("p-0 pt-3"):
            ui.button("Nueva nota", icon="note_add", on_click=lambda: _note_dialog(None, refresh_all)).props("unelevated no-caps color=primary")
            ui.space().classes("h-3")
            notes_list()

    # The chat (or Lechu) can add/remove items while this screen is open.
    seen = {"sig": reminder_store.signature()}

    def _poll() -> None:
        current = reminder_store.signature()
        if current != seen["sig"]:
            seen["sig"] = current
            refresh_all()

    ui.timer(3.0, _poll)


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
    chat: dict = {"msgs": {}, "active": None, "busy": False}

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
        elif view == "reminders":
            _reminders_screen(nav)
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
