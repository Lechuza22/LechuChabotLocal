from __future__ import annotations

import asyncio
import base64
import csv
import dataclasses
import io
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Optional

import httpx
import webview
from nicegui import app, run, ui

# ui.chat_message's `avatar` expects an image URL, not raw text - a bare "🦉"
# renders as a broken-image placeholder. Encode it as an inline SVG data URI instead.
_OWL_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<text x="50" y="78" font-size="72" text-anchor="middle">🦉</text></svg>'
)
OWL_AVATAR = "data:image/svg+xml;base64," + base64.b64encode(_OWL_SVG.encode("utf-8")).decode("ascii")

from config import AGENTS_DIR, CONFIG, SKILLS_DIR
from core import memory, projects
from core.agents import Agent, load_agents
from core.llm import OllamaClient
from core.skills import Skill, load_skills, match_skills
from core.tool_loop import Continue, FinalAnswer, PendingConfirmation, execute_tool, step_agent_stream
from core.tools.datetime_tools import get_current_time
from core.tools.filesystem import get_active_roots, read_file, set_active_roots
from core.tools.memory_tools import set_memory_scope

# mistral has a strong training bias toward claiming it "can't know the real
# time", which fights the get_current_time tool call even when instructed
# (empirically ~15-30% success). For this narrow, unambiguous, read-only
# query we skip relying on tool-calling and inject the real system clock
# straight into the system prompt instead - same keyword-injection mechanism
# as skills, just backed by live data instead of a markdown file.
_TIME_KEYWORDS = (
    "qué hora", "que hora", "hora es", "hora actual",
    "qué día es", "que dia es", "fecha de hoy", "fecha actual",
    "what time", "current time", "time is it",
    "today's date", "current date", "what's the date", "what is the date",
)

_LANG_BY_EXT = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".json": "json",
    ".yaml": "yaml", ".yml": "yaml", ".html": "html", ".css": "css",
    ".sh": "bash", ".sql": "sql", ".java": "java", ".go": "go", ".rs": "rust",
    ".c": "c", ".cpp": "cpp", ".rb": "ruby", ".php": "php", ".swift": "swift",
    ".toml": "toml", ".xml": "xml",
}


def _maybe_time_context(user_input: str) -> str | None:
    q = user_input.lower()
    if not any(kw in q for kw in _TIME_KEYWORDS):
        return None
    info = get_current_time()
    return (
        f"The user's local system time right now is {info['time']} on {info['date']} "
        f"({info['weekday']}). If asked about the current time or date, answer naturally "
        f"using this real value instead of saying you don't have access to it."
    )


def _guess_language(ext: str) -> str | None:
    return _LANG_BY_EXT.get(ext)


# --- shared singletons (read-only infra, not per-conversation state) ---------

_client: OllamaClient | None = None


def get_client() -> OllamaClient:
    global _client
    if _client is None:
        _client = OllamaClient(CONFIG.ollama_base_url)
    return _client


def get_agents() -> dict[str, Agent]:
    return load_agents(AGENTS_DIR)


# --- state -------------------------------------------------------------------

@dataclass
class AppState:
    agent_id: str
    active_model: str
    active_project_id: int | None = None
    conversation_id: int | None = None
    messages: list[dict] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)
    canvas: dict | None = None
    title_set: bool = False
    current_turn_task: Optional[asyncio.Task] = None


@dataclass
class UIRefs:
    chat_container: ui.column
    tree_container: ui.column
    canvas_container: ui.column
    input_box: ui.input
    send_btn: ui.button


def _effective_agent(state: AppState) -> Agent:
    agent = get_agents()[state.agent_id]
    return dataclasses.replace(agent, model=state.active_model)


def _active_project_row(state: AppState) -> sqlite3.Row | None:
    if state.active_project_id is None:
        return None
    return memory.get_project(state.active_project_id)


# --- folder-backed projects ---------------------------------------------------

def open_folder_as_project(path: str) -> int:
    """Links an existing .lechu-marked folder to its project, or registers a new one."""
    folder = Path(path).expanduser().resolve(strict=False)
    marker = projects.read_marker(folder)
    if marker:
        existing = memory.get_project(marker.get("lechu_project_id", -1))
        if existing:
            return existing["id"]
    by_folder = memory.find_project_by_folder(str(folder))
    if by_folder:
        projects.write_marker(folder, by_folder["name"], by_folder["id"])
        return by_folder["id"]

    name = folder.name or str(folder)
    candidate = name
    suffix = 2
    while True:
        try:
            project_id = memory.create_project(candidate, folder_path=str(folder))
            break
        except sqlite3.IntegrityError:
            candidate = f"{name} ({suffix})"
            suffix += 1
    projects.write_marker(folder, candidate, project_id)
    return project_id


def sync_project_scope(project_row: sqlite3.Row | None) -> None:
    folder_path = project_row["folder_path"] if project_row else None
    set_active_roots(folder_path)
    set_memory_scope(folder_path)


async def _apply_active_project_scope(state: AppState) -> None:
    await run.io_bound(sync_project_scope, _active_project_row(state))


# --- conversation lifecycle -------------------------------------------------

async def start_new_conversation(state: AppState, agent: Agent) -> None:
    conv_id = await run.io_bound(
        memory.create_conversation, agent_id=agent.id, model=agent.model, project_id=state.active_project_id
    )
    await run.io_bound(memory.add_message, conv_id, "system", agent.system_prompt)
    state.conversation_id = conv_id
    state.messages = [{"role": "system", "content": agent.system_prompt}]
    state.title_set = False
    state.canvas = None


async def load_conversation(state: AppState, conv_row: sqlite3.Row, agents: dict[str, Agent]) -> None:
    state.conversation_id = conv_row["id"]
    state.agent_id = conv_row["agent_id"] if conv_row["agent_id"] in agents else CONFIG.default_agent
    state.active_model = conv_row["model"]
    state.active_project_id = conv_row["project_id"]
    state.messages = await run.io_bound(memory.get_conversation_messages, conv_row["id"])
    state.title_set = True
    state.canvas = None
    await _apply_active_project_scope(state)


# --- persistence helpers -----------------------------------------------------

def _lookup_tool_name(messages: list[dict], tool_call_id: str) -> str | None:
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for call in msg["tool_calls"]:
                if call.get("id") == tool_call_id:
                    return call["function"]["name"]
    return None


def persist_new_messages(conv_id: int, messages: list[dict], start_index: int) -> None:
    for msg in messages[start_index:]:
        role = msg["role"]
        tool_call_id = msg.get("tool_call_id")
        tool_name = _lookup_tool_name(messages, tool_call_id) if role == "tool" and tool_call_id else None
        memory.add_message(
            conv_id, role, msg.get("content"),
            tool_calls=msg.get("tool_calls"), tool_call_id=tool_call_id, tool_name=tool_name,
        )


def build_system_message(agent: Agent, user_input: str, skills: list[Skill]) -> dict:
    matched: list[Skill] = match_skills(user_input, skills)
    text = agent.system_prompt

    roots = get_active_roots()
    if roots:
        roots_str = ", ".join(str(r) for r in roots)
        text += (
            f"\n\nThe folder you can currently read/write is: {roots_str}. "
            "When the user refers to \"this folder\"/\"esta carpeta\" or gives no path, "
            "use exactly this folder."
        )

    time_context = _maybe_time_context(user_input)
    if time_context:
        text += "\n\n" + time_context
    if matched:
        text += "\n\n# Relevant skill instructions:\n" + "\n\n".join(
            f"## {s.name}\n{s.body}" for s in matched
        )
    return {"role": "system", "content": text}


# --- canvas (document preview panel) -----------------------------------------

def _load_into_canvas(state: AppState, path: str) -> None:
    try:
        fresh = read_file(path)
        state.canvas = {"path": path, "content": fresh["content"]}
    except Exception as e:
        state.canvas = {"path": path, "error": str(e)}


def _scan_for_canvas_update(state: AppState, messages: list[dict], start_index: int) -> None:
    for msg in messages[start_index:]:
        if msg.get("role") != "tool":
            continue
        tool_name = _lookup_tool_name(messages, msg.get("tool_call_id"))
        if tool_name not in ("read_file", "write_file"):
            continue
        try:
            result = json.loads(msg["content"])
        except (json.JSONDecodeError, TypeError):
            continue
        path = result.get("path")
        if path and "error" not in result:
            _load_into_canvas(state, path)


def render_canvas(state: AppState, container: ui.column) -> None:
    container.clear()
    with container:
        ui.label("📄 Documentos").classes("text-lg font-bold")

        docs = memory.list_project_documents(state.active_project_id)
        if docs:
            with ui.expansion("Recientes en este proyecto", value=state.canvas is None).classes("w-full"):
                for path in docs:
                    ui.button(
                        Path(path).name,
                        on_click=lambda p=path: asyncio.create_task(_open_recent_doc(state, container, p)),
                    ).props("flat align=left").classes("w-full justify-start")

        canvas = state.canvas
        if not canvas:
            ui.label("Acá vas a ver los archivos que Lechu lea o escriba durante la conversación.") \
                .classes("text-caption text-gray-500")
            return

        ui.label(canvas["path"]).classes("text-caption text-gray-500")
        if canvas.get("error"):
            ui.label(canvas["error"]).classes("text-red")
            return

        content = canvas["content"]
        ext = Path(canvas["path"]).suffix.lower()
        if ext in (".csv", ".tsv"):
            delimiter = "," if ext == ".csv" else "\t"
            try:
                rows = list(csv.DictReader(io.StringIO(content), delimiter=delimiter))
                if rows:
                    columns = [{"name": k, "label": k, "field": k} for k in rows[0].keys()]
                    ui.table(rows=rows, columns=columns, row_key=list(rows[0].keys())[0]).classes("w-full")
                else:
                    ui.label("(CSV vacío)")
            except csv.Error:
                ui.code(content)
        elif ext in (".md", ".markdown"):
            ui.markdown(content)
        else:
            ui.code(content, language=_guess_language(ext)).classes("w-full")


async def _open_recent_doc(state: AppState, container: ui.column, path: str) -> None:
    await run.io_bound(_load_into_canvas, state, path)
    render_canvas(state, container)


# --- explorer (file tree) -----------------------------------------------------

def _build_tree_nodes(folder: Path, depth: int = 0, max_entries: int = 300, max_depth: int = 8) -> list[dict]:
    if depth > max_depth:
        return []
    try:
        entries = sorted(folder.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        return []
    entries = [e for e in entries if not e.name.startswith(".")][:max_entries]
    nodes = []
    for entry in entries:
        node: dict = {"id": str(entry), "label": entry.name}
        if entry.is_dir():
            node["children"] = _build_tree_nodes(entry, depth + 1, max_entries, max_depth)
        nodes.append(node)
    return nodes


def render_explorer(state: AppState, refs: UIRefs) -> None:
    container = refs.tree_container
    container.clear()
    with container:
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("🗂️ Explorer").classes("text-lg font-bold")
            ui.button(icon="refresh", on_click=lambda: render_explorer(state, refs)).props("flat dense")

        project = _active_project_row(state)
        if not (project and project["folder_path"]):
            ui.label("Abrí una carpeta desde la sidebar para ver sus archivos acá.") \
                .classes("text-caption text-gray-500")
            return

        folder = Path(project["folder_path"])
        ui.label(folder.name).classes("text-caption text-gray-500")
        nodes = _build_tree_nodes(folder)
        if not nodes:
            ui.label("(carpeta vacía)").classes("text-caption text-gray-500")
            return
        ui.tree(nodes, node_key="id", label_key="label",
                on_select=lambda e: _on_tree_select(state, refs, e.value))


def _on_tree_select(state: AppState, refs: UIRefs, node_id: str | None) -> None:
    if not node_id:
        return
    if Path(node_id).is_file():
        asyncio.create_task(_open_recent_doc(state, refs.canvas_container, node_id))


# --- chat rendering -----------------------------------------------------------

def render_chat_history(state: AppState, container: ui.column) -> None:
    """Full replay of a conversation. Tool-call/tool-result messages are internal
    plumbing, not shown - only real user/assistant text bubbles are rendered."""
    container.clear()
    with container:
        for msg in state.messages:
            role = msg["role"]
            if role == "user":
                with ui.chat_message(sent=True):
                    ui.markdown(msg["content"])
            elif role == "assistant" and not msg.get("tool_calls"):
                with ui.chat_message(name="Lechu", avatar=OWL_AVATAR):
                    ui.markdown(msg["content"])


def _new_thinking_bubble(container: ui.column, agent: Agent) -> tuple[ui.element, ui.row, ui.markdown]:
    """Creates one chat bubble for the whole turn, showing an animated 'Pensando...'
    placeholder that gets swapped for real content once it starts streaming in."""
    with container:
        with ui.chat_message(name=agent.name, avatar=OWL_AVATAR) as bubble:
            thinking = ui.row().classes("items-center gap-2")
            with thinking:
                ui.html('<span class="lechu-thinking-owl">🦉</span>')
                ui.label("Pensando...").classes("italic text-gray-500")
            md = ui.markdown("")
            md.set_visibility(False)
    return bubble, thinking, md


async def _stream_into_chat(
    md: ui.markdown, thinking: ui.row, chunks: AsyncIterator[str],
    min_interval: float = 0.08, min_chars: int = 24,
) -> bool:
    """Fills `md` with streamed content, swapping out the `thinking` placeholder
    the moment real content starts arriving. Returns True if any content streamed
    (tool-only turns yield no content at all)."""
    buf: list[str] = []
    total_len = flushed_len = 0
    loop = asyncio.get_event_loop()
    last_flush = loop.time()
    started = False

    async for piece in chunks:
        if not started:
            started = True
            thinking.set_visibility(False)
            md.set_visibility(True)
        buf.append(piece)
        total_len += len(piece)
        now = loop.time()
        if total_len - flushed_len >= min_chars or now - last_flush >= min_interval:
            md.set_content("".join(buf))
            flushed_len, last_flush = total_len, now

    if started:
        md.set_content("".join(buf))
    return started


# --- turn driving --------------------------------------------------------

async def _ask_confirmation(container: ui.column, agent: Agent, pc: PendingConfirmation) -> dict:
    future: asyncio.Future = asyncio.get_event_loop().create_future()
    holder: dict = {}

    def _resolve(approved: bool) -> None:
        if future.done():
            return
        row = holder["row"]
        row.clear()
        with row:
            ui.label("✅ Confirmado" if approved else "❌ Cancelado").classes("text-xs text-gray-500")
        future.set_result(approved)

    with container:
        with ui.chat_message(name=agent.name, avatar=OWL_AVATAR):
            ui.label(f"Quiero ejecutar {pc.tool_name} con estos argumentos:").classes("text-orange-700 font-medium")
            ui.code(json.dumps(pc.args, indent=2, ensure_ascii=False), language="json")
            with ui.row() as btn_row:
                ui.button("Confirmar", on_click=lambda: _resolve(True), color="primary")
                ui.button("Cancelar", on_click=lambda: _resolve(False))
            holder["row"] = btn_row

    approved = await future

    if approved:
        result = await run.io_bound(execute_tool, pc.tool_name, pc.args)
    else:
        result = {"error": "El usuario rechazó esta acción."}
    return result if result is not None else {"error": "cancelled"}


async def _advance(state: AppState, refs: UIRefs, agent: Agent) -> None:
    start_len = len(state.messages)
    bubble, thinking, md = _new_thinking_bubble(refs.chat_container, agent)
    try:
        result = None
        content_started = False
        for _ in range(CONFIG.max_tool_iterations):
            chunks, box = await step_agent_stream(get_client(), agent, state.messages)
            if await _stream_into_chat(md, thinking, chunks):
                content_started = True
            result = box["result"]
            if isinstance(result, Continue):
                continue
            break
        else:
            fallback = "Me detuve después de demasiadas llamadas a herramientas. Probá simplificar el pedido."
            state.messages.append({"role": "assistant", "content": fallback})
            thinking.set_visibility(False)
            md.set_visibility(True)
            md.set_content(fallback)
            content_started = True
            result = FinalAnswer(fallback)

        if isinstance(result, PendingConfirmation) and not content_started:
            bubble.delete()

        await run.io_bound(persist_new_messages, state.conversation_id, state.messages, start_len)
        _scan_for_canvas_update(state, state.messages, start_len)
        render_canvas(state, refs.canvas_container)

        if isinstance(result, PendingConfirmation):
            tool_result = await _ask_confirmation(refs.chat_container, agent, result)
            pre_append_len = len(state.messages)
            state.messages.append({
                "role": "tool", "tool_call_id": result.tool_call_id, "content": json.dumps(tool_result),
            })
            await run.io_bound(persist_new_messages, state.conversation_id, state.messages, pre_append_len)
            if result.tool_name in ("read_file", "write_file") and "error" not in tool_result:
                await run.io_bound(_load_into_canvas, state, tool_result["path"])
                render_canvas(state, refs.canvas_container)
                render_explorer(state, refs)
            await _advance(state, refs, agent)

    except httpx.HTTPError as e:
        msg = f"No se pudo contactar a Ollama: {e}"
        state.messages.append({"role": "assistant", "content": msg})
        thinking.set_visibility(False)
        md.set_visibility(True)
        md.set_content(msg)
        await run.io_bound(persist_new_messages, state.conversation_id, state.messages, start_len)


async def handle_user_turn(state: AppState, refs: UIRefs, agent: Agent, user_input: str) -> None:
    state.messages[0] = build_system_message(agent, user_input, state.skills)
    state.messages.append({"role": "user", "content": user_input})
    await run.io_bound(memory.add_message, state.conversation_id, "user", user_input)

    if not state.title_set:
        title = user_input.strip().splitlines()[0][:60]
        await run.io_bound(memory.set_conversation_title, state.conversation_id, title)
        state.title_set = True

    with refs.chat_container:
        with ui.chat_message(sent=True):
            ui.markdown(user_input)

    await _advance(state, refs, agent)


async def _on_submit(state: AppState, refs: UIRefs) -> None:
    text = (refs.input_box.value or "").strip()
    if not text or (state.current_turn_task and not state.current_turn_task.done()):
        return
    refs.input_box.value = ""
    refs.input_box.disable()
    refs.send_btn.disable()
    agent = _effective_agent(state)
    task = asyncio.create_task(handle_user_turn(state, refs, agent, text))
    state.current_turn_task = task
    try:
        await task
    except asyncio.CancelledError:
        pass
    finally:
        state.current_turn_task = None
        refs.input_box.enable()
        refs.send_btn.enable()


# --- main page -----------------------------------------------------------------

def build_page() -> None:
    @ui.page("/")
    async def main_page() -> None:
        ui.colors(primary="#a5693a", secondary="#e8a33d", accent="#c98f52")
        ui.query("body").classes("bg-[#faf9f6]")
        ui.add_head_html("""
            <style>
            @keyframes lechu-wiggle {
                0%, 100% { transform: rotate(-12deg); }
                50% { transform: rotate(12deg); }
            }
            .lechu-thinking-owl {
                display: inline-block;
                font-size: 1.3em;
                transform-origin: 50% 80%;
                animation: lechu-wiggle 0.8s ease-in-out infinite;
            }
            /* Quasar's chat bubble uses `background: currentColor`, so overriding
               `color` here repaints the bubble itself to match the brandbook
               instead of Quasar's default light-green for received messages. */
            .q-message-text--received {
                color: #f2f1ef;
            }
            .q-message-text-content--received {
                color: #2b2925;
            }
            </style>
        """)

        agents = get_agents()
        if not agents:
            ui.label(f"No hay agentes definidos en {AGENTS_DIR}. Agregá al menos un archivo .yaml.").classes("text-red")
            return

        default_agent_id = CONFIG.default_agent if CONFIG.default_agent in agents else next(iter(agents))
        state = AppState(agent_id=default_agent_id, active_model=agents[default_agent_id].model)
        state.skills = await run.io_bound(load_skills, SKILLS_DIR)
        await start_new_conversation(state, agents[state.agent_id])
        await _apply_active_project_scope(state)

        try:
            available_models = await get_client().list_models()
        except httpx.HTTPError:
            available_models = []
        if available_models and state.active_model not in available_models:
            state.active_model = available_models[0]

        with ui.header().classes("items-center justify-between bg-[#a5693a]"):
            ui.label("🦉 Lechu").classes("text-xl font-bold")

        with ui.left_drawer(value=True, bordered=True).classes("bg-[#f2f1ef]") as drawer:
            refs_holder: dict = {}
            render_sidebar(state, agents, available_models, refs_holder)

        with ui.splitter(value=19).classes("w-full") \
                .style("height: calc(100vh - 64px)") as outer:
            with outer.before:
                tree_container = ui.column().classes("w-full h-full overflow-auto p-2")
            with outer.after:
                with ui.splitter(value=62).classes("w-full h-full") as inner:
                    with inner.before:
                        with ui.column().classes("w-full h-full p-2"):
                            chat_container = ui.column().classes("w-full flex-grow overflow-auto")
                            with ui.row().classes("w-full items-center"):
                                input_box = ui.input(placeholder="Escribí un mensaje...").classes("flex-grow")
                                send_btn = ui.button(icon="send")
                    with inner.after:
                        canvas_container = ui.column().classes("w-full h-full overflow-auto p-2")

        refs = UIRefs(
            chat_container=chat_container,
            tree_container=tree_container,
            canvas_container=canvas_container,
            input_box=input_box,
            send_btn=send_btn,
        )
        refs_holder["refs"] = refs

        input_box.on("keydown.enter", lambda: asyncio.create_task(_on_submit(state, refs)))
        send_btn.on_click(lambda: asyncio.create_task(_on_submit(state, refs)))

        render_chat_history(state, chat_container)
        render_explorer(state, refs)
        render_canvas(state, canvas_container)


# --- sidebar -------------------------------------------------------------------

def render_sidebar(state: AppState, agents: dict[str, Agent], available_models: list[str], refs_holder: dict) -> None:
    ui.label("Proyectos").classes("font-bold")

    @ui.refreshable
    def project_selector() -> None:
        project_rows = memory.list_projects()
        options = {None: "Sin proyecto"}
        for p in project_rows:
            options[p["id"]] = p["name"]
        ui.select(options, value=state.active_project_id, label="Proyecto activo",
                  on_change=lambda e: asyncio.create_task(_on_project_change(e.value))) \
            .classes("w-full")

    project_selector()

    async def _on_project_change(project_id: int | None) -> None:
        state.active_project_id = project_id
        await _apply_active_project_scope(state)
        await start_new_conversation(state, _effective_agent(state))
        refs = refs_holder["refs"]
        render_chat_history(state, refs.chat_container)
        render_explorer(state, refs)
        render_canvas(state, refs.canvas_container)
        history_panel.refresh()
        folder_caption.refresh()

    async def _open_folder() -> None:
        result = await app.native.main_window.create_file_dialog(dialog_type=webview.FileDialog.FOLDER)
        if not result:
            return
        path = result[0] if isinstance(result, (list, tuple)) else result
        project_id = await run.io_bound(open_folder_as_project, path)
        state.active_project_id = project_id
        await _apply_active_project_scope(state)
        await start_new_conversation(state, _effective_agent(state))
        refs = refs_holder["refs"]
        project_selector.refresh()
        render_chat_history(state, refs.chat_container)
        render_explorer(state, refs)
        render_canvas(state, refs.canvas_container)
        history_panel.refresh()
        folder_caption.refresh()

    ui.button("📂 Abrir carpeta...", on_click=_open_folder).classes("w-full")

    @ui.refreshable
    def folder_caption() -> None:
        project = _active_project_row(state)
        if project and project["folder_path"]:
            ui.label(f"📁 {project['folder_path']}").classes("text-caption text-gray-500 break-all")

    folder_caption()

    ui.separator()
    ui.label("Agente").classes("font-bold")

    async def _on_agent_change(agent_id: str) -> None:
        state.agent_id = agent_id
        state.active_model = agents[agent_id].model
        await start_new_conversation(state, _effective_agent(state))
        refs = refs_holder["refs"]
        render_chat_history(state, refs.chat_container)
        history_panel.refresh()
        model_select.value = state.active_model

    ui.select({aid: a.name for aid, a in agents.items()}, value=state.agent_id,
              on_change=lambda e: asyncio.create_task(_on_agent_change(e.value))).classes("w-full")

    def _on_model_change(model: str) -> None:
        state.active_model = model

    model_options = available_models if available_models else [state.active_model]
    model_select = ui.select(model_options, value=state.active_model,
                              on_change=lambda e: _on_model_change(e.value)).classes("w-full")
    if not available_models:
        ui.label(f"No se pudo conectar con Ollama en {CONFIG.ollama_base_url}.").classes("text-red text-caption")

    async def _new_conversation() -> None:
        await start_new_conversation(state, _effective_agent(state))
        refs = refs_holder["refs"]
        render_chat_history(state, refs.chat_container)
        render_canvas(state, refs.canvas_container)
        history_panel.refresh()

    ui.button("Nueva conversación", on_click=_new_conversation).classes("w-full")

    ui.separator()
    with ui.expansion("Historial", value=True).classes("w-full"):
        @ui.refreshable
        def history_panel() -> None:
            conversations = memory.list_conversations(state.active_project_id)
            if not conversations:
                ui.label("Sin conversaciones todavía en este proyecto.").classes("text-caption text-gray-500")
                return
            for conv in conversations:
                label = conv["title"] or f"Conversación #{conv['id']} ({conv['agent_id']})"
                ui.button(label, on_click=lambda c=conv: asyncio.create_task(_load_history(c))) \
                    .props("flat align=left").classes("w-full justify-start")

        async def _load_history(conv_row: sqlite3.Row) -> None:
            await load_conversation(state, conv_row, agents)
            refs = refs_holder["refs"]
            render_chat_history(state, refs.chat_container)
            render_explorer(state, refs)
            render_canvas(state, refs.canvas_container)
            project_selector.refresh()
            folder_caption.refresh()
            history_panel.refresh()

        history_panel()

    with ui.expansion("Memoria").classes("w-full"):
        @ui.refreshable
        def memory_panel() -> None:
            facts = memory.recall_facts()
            if facts:
                rows = [{"category": f["category"], "key": f["key"], "value": f["value"]} for f in facts]
                columns = [
                    {"name": "category", "label": "Categoría", "field": "category"},
                    {"name": "key", "label": "Clave", "field": "key"},
                    {"name": "value", "label": "Valor", "field": "value"},
                ]
                ui.table(rows=rows, columns=columns, row_key="key").classes("w-full")
            else:
                ui.label("Todavía no hay hechos guardados.").classes("text-caption text-gray-500")

            cat_input = ui.input("Categoría")
            key_input = ui.input("Clave")
            val_input = ui.input("Valor")

            def _add_fact() -> None:
                if cat_input.value and key_input.value and val_input.value:
                    memory.remember_fact(cat_input.value, key_input.value, val_input.value, source="user")
                    cat_input.value = ""
                    key_input.value = ""
                    val_input.value = ""
                    memory_panel.refresh()

            ui.button("Guardar", on_click=_add_fact)

            if facts:
                del_options = {f["id"]: f"{f['category']}/{f['key']}" for f in facts}
                del_select = ui.select(del_options, label="Borrar hecho")

                def _delete_fact() -> None:
                    if del_select.value is not None:
                        memory.delete_fact(del_select.value)
                        memory_panel.refresh()

                ui.button("Borrar hecho", on_click=_delete_fact)

        memory_panel()

    with ui.expansion("Skills").classes("w-full"):
        @ui.refreshable
        def skills_panel() -> None:
            for skill in state.skills:
                ui.label(f"{skill.name} — {skill.description}").classes("text-sm")

            def _reload_skills() -> None:
                state.skills = load_skills(SKILLS_DIR)
                skills_panel.refresh()

            ui.button("Recargar skills", on_click=_reload_skills)

        skills_panel()

    with ui.expansion("Carpetas habilitadas").classes("w-full"):
        for folder in CONFIG.filesystem.whitelisted_folders:
            ui.code(str(folder))


def main() -> None:
    build_page()
    app.on_shutdown(get_client().aclose)
    ui.run(
        native=True,
        window_size=(1400, 900),
        title="Lechu",
        reload=False,
        show=True,
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
