from __future__ import annotations

import csv
import dataclasses
import io
import json
import sqlite3
import subprocess
from pathlib import Path

import httpx
import streamlit as st

from config import AGENTS_DIR, CONFIG, SKILLS_DIR
from core import memory, projects
from core.agents import Agent, load_agents
from core.llm import OllamaClient
from core.skills import Skill, load_skills, match_skills
from core.tool_loop import FinalAnswer, PendingConfirmation, execute_tool, step_agent_stream
from core.tools.datetime_tools import get_current_time
from core.tools.filesystem import read_file, set_active_roots
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


@st.cache_resource
def get_client() -> OllamaClient:
    return OllamaClient(CONFIG.ollama_base_url)


@st.cache_resource
def get_agents() -> dict[str, Agent]:
    return load_agents(AGENTS_DIR)


# --- folder-backed projects ---------------------------------------------------

def pick_folder_native() -> str | None:
    """Native macOS folder picker via AppleScript. Returns None on cancel/error."""
    script = 'POSIX path of (choose folder with prompt "Elegí una carpeta para abrir en Lechu")'
    try:
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=120
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None  # user cancelled, or automation permission denied
    path = result.stdout.strip()
    return path or None


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


def sync_project_scope(project_row) -> None:
    folder_path = project_row["folder_path"] if project_row else None
    set_active_roots(folder_path)
    set_memory_scope(folder_path)


# --- conversation lifecycle -------------------------------------------------

def start_new_conversation(agent: Agent) -> None:
    project_id = st.session_state.get("active_project_id")
    conv_id = memory.create_conversation(agent_id=agent.id, model=agent.model, project_id=project_id)
    memory.add_message(conv_id, "system", agent.system_prompt)
    st.session_state.conversation_id = conv_id
    st.session_state.messages = [{"role": "system", "content": agent.system_prompt}]
    st.session_state.pending_tool_call = None
    st.session_state.title_set = False
    st.session_state.canvas = None


def load_conversation(conv_row, agents: dict[str, Agent]) -> None:
    st.session_state.conversation_id = conv_row["id"]
    st.session_state.agent_id = conv_row["agent_id"] if conv_row["agent_id"] in agents else CONFIG.default_agent
    st.session_state.active_model = conv_row["model"]
    st.session_state.active_project_id = conv_row["project_id"]
    st.session_state.messages = memory.get_conversation_messages(conv_row["id"])
    st.session_state.pending_tool_call = None
    st.session_state.title_set = True
    st.session_state.canvas = None


def init_session_state(agents: dict[str, Agent]) -> None:
    if "active_project_id" not in st.session_state:
        st.session_state.active_project_id = None
    if "canvas" not in st.session_state:
        st.session_state.canvas = None
    if "agent_id" not in st.session_state:
        st.session_state.agent_id = CONFIG.default_agent if CONFIG.default_agent in agents else next(iter(agents))
    if "skills" not in st.session_state:
        st.session_state.skills = load_skills(SKILLS_DIR)
    if "conversation_id" not in st.session_state:
        start_new_conversation(agents[st.session_state.agent_id])
    if "pending_tool_call" not in st.session_state:
        st.session_state.pending_tool_call = None


# --- persistence helpers -----------------------------------------------------

def _lookup_tool_name(messages: list[dict], tool_call_id: str) -> str | None:
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for call in msg["tool_calls"]:
                if call.get("id") == tool_call_id:
                    return call["function"]["name"]
    return None


# --- canvas (document preview panel) -----------------------------------------

def _load_into_canvas(path: str) -> None:
    try:
        fresh = read_file(path)
        st.session_state.canvas = {"path": path, "content": fresh["content"]}
    except Exception as e:
        st.session_state.canvas = {"path": path, "error": str(e)}


def _scan_for_canvas_update(messages: list[dict], start_index: int) -> None:
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
            _load_into_canvas(path)


def persist_new_messages(conv_id: int, messages: list[dict], start_index: int) -> None:
    for msg in messages[start_index:]:
        role = msg["role"]
        tool_call_id = msg.get("tool_call_id")
        tool_name = _lookup_tool_name(messages, tool_call_id) if role == "tool" and tool_call_id else None
        memory.add_message(
            conv_id,
            role,
            msg.get("content"),
            tool_calls=msg.get("tool_calls"),
            tool_call_id=tool_call_id,
            tool_name=tool_name,
        )


def build_system_message(agent: Agent, user_input: str) -> dict:
    matched: list[Skill] = match_skills(user_input, st.session_state.skills)
    text = agent.system_prompt
    time_context = _maybe_time_context(user_input)
    if time_context:
        text += "\n\n" + time_context
    if matched:
        text += "\n\n# Relevant skill instructions:\n" + "\n\n".join(
            f"## {s.name}\n{s.body}" for s in matched
        )
    return {"role": "system", "content": text}


# --- turn driving --------------------------------------------------------

def _advance(client: OllamaClient, agent: Agent, conv_id: int) -> None:
    start_len = len(st.session_state.messages)
    try:
        result = None
        for _ in range(CONFIG.max_tool_iterations):
            chunks, box = step_agent_stream(client, agent, st.session_state.messages)
            with st.chat_message("assistant", avatar="🦉"):
                st.write_stream(chunks)
            result = box["result"]
            if isinstance(result, (FinalAnswer, PendingConfirmation)):
                break
        else:
            fallback = "Me detuve después de demasiadas llamadas a herramientas. Probá simplificar el pedido."
            st.session_state.messages.append({"role": "assistant", "content": fallback})
            result = FinalAnswer(fallback)

        persist_new_messages(conv_id, st.session_state.messages, start_len)
        _scan_for_canvas_update(st.session_state.messages, start_len)
        st.session_state.pending_tool_call = (
            result._asdict() if isinstance(result, PendingConfirmation) else None
        )
    except httpx.HTTPError as e:
        st.session_state.messages.append(
            {"role": "assistant", "content": f"No se pudo contactar a Ollama: {e}"}
        )
        persist_new_messages(conv_id, st.session_state.messages, start_len)
        st.session_state.pending_tool_call = None


def handle_user_turn(client: OllamaClient, agent: Agent, user_input: str) -> None:
    conv_id = st.session_state.conversation_id
    st.session_state.messages[0] = build_system_message(agent, user_input)
    st.session_state.messages.append({"role": "user", "content": user_input})
    memory.add_message(conv_id, "user", user_input)

    if not st.session_state.get("title_set"):
        memory.set_conversation_title(conv_id, user_input.strip().splitlines()[0][:60])
        st.session_state.title_set = True

    with st.chat_message("user"):
        st.markdown(user_input)

    _advance(client, agent, conv_id)


def _append_and_persist_tool_result(pc: dict, result: dict) -> None:
    st.session_state.messages.append(
        {"role": "tool", "tool_call_id": pc["tool_call_id"], "content": json.dumps(result)}
    )
    memory.add_message(
        st.session_state.conversation_id,
        "tool",
        json.dumps(result),
        tool_call_id=pc["tool_call_id"],
        tool_name=pc["tool_name"],
    )


# --- UI: sidebar -------------------------------------------------------------

def render_file_tree(folder: Path, depth: int = 0, max_entries: int = 300) -> None:
    if depth > 6:
        return
    try:
        entries = sorted(folder.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError as e:
        st.caption(f"No se pudo leer {folder.name}: {e}")
        return
    entries = [e for e in entries if not e.name.startswith(".")][:max_entries]
    for entry in entries:
        if entry.is_dir():
            with st.expander(f"📁 {entry.name}", expanded=False):
                render_file_tree(entry, depth + 1, max_entries)
        else:
            if st.button(f"📄 {entry.name}", key=f"tree_{entry}", use_container_width=True):
                _load_into_canvas(str(entry))
                st.rerun()


def render_sidebar(agents: dict[str, Agent], client: OllamaClient) -> Agent:
    st.sidebar.title("🦉 Lechu")

    st.sidebar.subheader("Proyectos")
    project_rows = memory.list_projects()
    options = ["Sin proyecto"] + [p["name"] for p in project_rows]
    name_to_id = {p["name"]: p["id"] for p in project_rows}
    current_name = next(
        (p["name"] for p in project_rows if p["id"] == st.session_state.active_project_id),
        "Sin proyecto",
    )
    selected_name = st.sidebar.selectbox("Proyecto activo", options, index=options.index(current_name))
    selected_project_id = name_to_id.get(selected_name)
    if selected_project_id != st.session_state.active_project_id:
        st.session_state.active_project_id = selected_project_id
        start_new_conversation(agents[st.session_state.agent_id])
        st.rerun()

    active_project_row = next((p for p in project_rows if p["id"] == st.session_state.active_project_id), None)
    sync_project_scope(active_project_row)

    if st.sidebar.button("📂 Abrir carpeta...", use_container_width=True):
        picked = pick_folder_native()
        if picked:
            new_id = open_folder_as_project(picked)
            st.session_state.active_project_id = new_id
            start_new_conversation(agents[st.session_state.agent_id])
            st.rerun()

    with st.sidebar.form("new_project_form", clear_on_submit=True):
        new_project_name = st.text_input("Nuevo proyecto (sin carpeta)")
        if st.form_submit_button("Crear proyecto") and new_project_name.strip():
            try:
                new_id = memory.create_project(new_project_name.strip())
                st.session_state.active_project_id = new_id
                st.rerun()
            except sqlite3.IntegrityError:
                st.sidebar.error(f"Ya existe un proyecto llamado '{new_project_name.strip()}'.")

    if active_project_row and active_project_row["folder_path"]:
        st.sidebar.caption(f"📁 {active_project_row['folder_path']}")
        with st.sidebar.expander("Archivos", expanded=True):
            render_file_tree(Path(active_project_row["folder_path"]))

    agent_ids = list(agents.keys())
    selected_id = st.sidebar.selectbox(
        "Agente",
        agent_ids,
        index=agent_ids.index(st.session_state.agent_id),
        format_func=lambda i: agents[i].name,
    )
    if selected_id != st.session_state.agent_id:
        st.session_state.agent_id = selected_id
        start_new_conversation(agents[selected_id])
        st.rerun()

    agent = agents[st.session_state.agent_id]

    try:
        available_models = client.list_models()
    except httpx.HTTPError:
        available_models = []
        st.sidebar.error(
            f"No se pudo conectar con Ollama en {CONFIG.ollama_base_url}. "
            "¿Está corriendo `ollama serve`?"
        )

    if agent.model not in available_models and available_models:
        st.sidebar.warning(f"El modelo '{agent.model}' de este agente no está descargado localmente.")

    if available_models:
        default_model = st.session_state.get("active_model", agent.model)
        if default_model not in available_models:
            default_model = agent.model if agent.model in available_models else available_models[0]
        selected_model = st.sidebar.selectbox(
            "Modelo", available_models, index=available_models.index(default_model)
        )
        st.session_state.active_model = selected_model
    else:
        selected_model = st.session_state.get("active_model", agent.model)

    if st.sidebar.button("Nueva conversación"):
        start_new_conversation(agent)
        st.rerun()

    with st.sidebar.expander("Historial", expanded=True):
        conversations = memory.list_conversations(st.session_state.active_project_id)
        if not conversations:
            st.caption("Sin conversaciones todavía en este proyecto.")
        for conv in conversations:
            label = conv["title"] or f"Conversación #{conv['id']} ({conv['agent_id']})"
            if st.button(label, key=f"conv_{conv['id']}"):
                load_conversation(conv, agents)
                st.rerun()

    with st.sidebar.expander("Memoria"):
        facts = memory.recall_facts()
        if facts:
            st.dataframe(
                [{"categoría": f["category"], "clave": f["key"], "valor": f["value"]} for f in facts],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("Todavía no hay hechos guardados.")
        with st.form("add_fact_form", clear_on_submit=True):
            c_cat = st.text_input("Categoría")
            c_key = st.text_input("Clave")
            c_val = st.text_input("Valor")
            if st.form_submit_button("Guardar") and c_cat and c_key and c_val:
                memory.remember_fact(c_cat, c_key, c_val, source="user")
                st.rerun()
        if facts:
            options = ["-"] + [f"{f['id']}: {f['category']}/{f['key']}" for f in facts]
            to_delete = st.selectbox("Borrar hecho", options)
            if to_delete != "-" and st.button("Borrar hecho"):
                fact_id = int(to_delete.split(":")[0])
                memory.delete_fact(fact_id)
                st.rerun()

    with st.sidebar.expander("Skills"):
        for skill in st.session_state.skills:
            st.markdown(f"**{skill.name}** — {skill.description}")
        if st.button("Recargar skills"):
            st.session_state.skills = load_skills(SKILLS_DIR)
            st.rerun()

    with st.sidebar.expander("Carpetas habilitadas"):
        for folder in CONFIG.filesystem.whitelisted_folders:
            st.code(str(folder))

    return dataclasses.replace(agent, model=selected_model)


# --- UI: chat -----------------------------------------------------------------

def render_chat() -> None:
    pending_tool_activity: list[dict] = []
    for msg in st.session_state.messages:
        role = msg["role"]
        if role in ("system",):
            continue
        if role == "user":
            pending_tool_activity = []
            with st.chat_message("user"):
                st.markdown(msg["content"])
        elif role == "assistant":
            if msg.get("tool_calls"):
                for call in msg["tool_calls"]:
                    pending_tool_activity.append({
                        "type": "call",
                        "name": call["function"]["name"],
                        "args": call["function"]["arguments"],
                    })
                continue
            with st.chat_message("assistant", avatar="🦉"):
                if pending_tool_activity:
                    with st.expander("Actividad de herramientas", expanded=False):
                        for item in pending_tool_activity:
                            if item["type"] == "call":
                                st.markdown(f"**{item['name']}**")
                                st.code(json.dumps(item["args"], ensure_ascii=False), language="json")
                            else:
                                st.code(item["result"], language="json")
                    pending_tool_activity = []
                st.markdown(msg["content"])
        elif role == "tool":
            pending_tool_activity.append({"type": "result", "result": msg["content"]})


def render_confirmation_card(client: OllamaClient, agent: Agent) -> None:
    pc = st.session_state.pending_tool_call
    with st.chat_message("assistant", avatar="🦉"):
        st.warning(f"El asistente quiere ejecutar **{pc['tool_name']}** con estos argumentos:")
        st.code(json.dumps(pc["args"], indent=2, ensure_ascii=False), language="json")
        col1, col2 = st.columns(2)
        confirm = col1.button("Confirmar", key=f"confirm_{pc['tool_call_id']}", type="primary")
        cancel = col2.button("Cancelar", key=f"cancel_{pc['tool_call_id']}")

    if confirm:
        result = execute_tool(pc["tool_name"], pc["args"])
        _append_and_persist_tool_result(pc, result)
        if pc["tool_name"] in ("read_file", "write_file") and "error" not in result:
            _load_into_canvas(result["path"])
        st.session_state.pending_tool_call = None
        _advance(client, agent, st.session_state.conversation_id)
        st.rerun()
    elif cancel:
        _append_and_persist_tool_result(pc, {"error": "El usuario rechazó esta acción."})
        st.session_state.pending_tool_call = None
        _advance(client, agent, st.session_state.conversation_id)
        st.rerun()


# --- UI: canvas (document preview panel) --------------------------------------

def render_canvas_panel() -> None:
    st.subheader("📄 Documentos")

    docs = memory.list_project_documents(st.session_state.active_project_id)
    if docs:
        with st.expander("Recientes en este proyecto", expanded=st.session_state.canvas is None):
            for path in docs:
                if st.button(Path(path).name, key=f"doc_{path}", use_container_width=True):
                    _load_into_canvas(path)
                    st.rerun()

    canvas = st.session_state.canvas
    if not canvas:
        st.caption("Acá vas a ver los archivos que Lechu lea o escriba durante la conversación.")
        return

    st.caption(canvas["path"])
    if canvas.get("error"):
        st.error(canvas["error"])
        return

    content = canvas["content"]
    ext = Path(canvas["path"]).suffix.lower()
    if ext in (".csv", ".tsv"):
        delimiter = "," if ext == ".csv" else "\t"
        try:
            rows = list(csv.DictReader(io.StringIO(content), delimiter=delimiter))
            st.dataframe(rows, use_container_width=True)
        except csv.Error:
            st.code(content)
    elif ext in (".md", ".markdown"):
        st.markdown(content)
    else:
        st.code(content, language=None)


# --- main ----------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="Lechu", page_icon="🦉", layout="wide")
    st.markdown(
        "<style>[data-testid='stStatusWidget'] {visibility: hidden;}</style>",
        unsafe_allow_html=True,
    )
    memory.init_db()

    client = get_client()
    agents = get_agents()
    if not agents:
        st.error(f"No hay agentes definidos en {AGENTS_DIR}. Agregá al menos un archivo .yaml.")
        st.stop()
    init_session_state(agents)

    agent = render_sidebar(agents, client)

    chat_col, canvas_col = st.columns([3, 2])

    with chat_col:
        st.title("🦉 Lechu")
        st.caption(f"Agente: {agent.name} · Modelo: {agent.model} · 100% offline vía Ollama")

        render_chat()

        if st.session_state.pending_tool_call:
            render_confirmation_card(client, agent)
        else:
            user_input = st.chat_input("Escribí un mensaje...")
            if user_input:
                handle_user_turn(client, agent, user_input)
                st.rerun()

    with canvas_col:
        render_canvas_panel()


if __name__ == "__main__":
    main()
