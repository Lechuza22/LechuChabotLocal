"""Tool-routing regression cases: one prompt, one expected first tool call.

Not exhaustive integration tests - just "does the model call the right tool
for an unambiguous request", the same question answered by hand (direct
OllamaClient.chat_stream calls, no benchmark harness) throughout this
project's Conexiones work. Seeded from those exact prompts so the results
already validated manually aren't lost as one-off terminal scripts.

Each case only checks the FIRST tool call the model makes for a fresh
conversation (agent.system_prompt as-is, no app.py-level extras like the
live time/folder context) - deliberately narrow in scope, see run_bench.py.
"""

from __future__ import annotations

CASES: list[dict] = [
    # --- general: filesystem/memory (pre-existing tools) ---
    {
        "name": "general_read_file",
        "agent_id": "general",
        "prompt": "Leé el archivo notas.txt",
        "expected_tool": "read_file",
    },
    {
        "name": "general_remember_fact",
        "agent_id": "general",
        "prompt": "Recordá que mi color favorito es el verde",
        "expected_tool": "remember_fact",
    },
    {
        "name": "general_create_folder",
        "agent_id": "general",
        "prompt": "Creá una carpeta nueva llamada borradores",
        "expected_tool": "create_folder",
    },
    # --- general: Clima/Maps (Conexiones fase 1) ---
    {
        "name": "general_weather",
        "agent_id": "general",
        "prompt": "¿Qué tiempo hace en Buenos Aires ahora mismo?",
        "expected_tool": "get_weather",
    },
    {
        "name": "general_directions",
        "agent_id": "general",
        "prompt": "¿Cuánto se tarda en auto de Palermo a Tigre?",
        "expected_tool": "get_directions",
    },
    # --- search: búsqueda web/Wikipedia (agente dedicado, separado de
    # general porque el benchmark encontró 2/5 confusiones entre
    # search_web/search_wikipedia cuando competían con las otras 9 tools) ---
    {
        "name": "search_web_horarios",
        "agent_id": "search",
        "prompt": "Buscá en internet los horarios del Museo del Prado",
        "expected_tool": "search_web",
    },
    {
        "name": "search_web_capital",
        "agent_id": "search",
        "prompt": "Buscá en Google cuál es la capital de Mongolia",
        "expected_tool": "search_web",
    },
    {
        "name": "search_wikipedia_ornitorrinco",
        "agent_id": "search",
        "prompt": "¿Qué es un ornitorrinco? Buscalo en Wikipedia",
        "expected_tool": "search_wikipedia",
    },
    {
        "name": "search_wikipedia_bolivar",
        "agent_id": "search",
        "prompt": "¿Quién fue Simón Bolívar? Buscalo en Wikipedia",
        "expected_tool": "search_wikipedia",
    },
    # --- google: Gmail/Drive/Calendar (Conexiones fase 2) ---
    {
        "name": "google_search_emails",
        "agent_id": "google",
        "prompt": "Buscá mis últimos mails de LinkedIn",
        "expected_tool": "search_emails",
    },
    {
        "name": "google_send_email",
        "agent_id": "google",
        "prompt": "Mandale un mail a juan@ejemplo.com contándole que llego tarde",
        "expected_tool": "send_email",
    },
    {
        "name": "google_search_drive",
        "agent_id": "google",
        "prompt": "Buscá en mi Drive archivos que tengan DNI en el nombre",
        "expected_tool": "search_drive_files",
    },
    {
        "name": "google_calendar_event",
        "agent_id": "google",
        "prompt": "Creame un evento de calendario mañana a las 10 llamado Dentista",
        "expected_tool": "manage_calendar_event",
    },
    {
        # First step of a legitimate two-step chain: resolving "esta semana"
        # needs "today" before list_calendar_events can compute a range.
        # Confirmed correct behavior (not a routing failure) when this was
        # tested manually - see the Conexiones fase 2 work.
        "name": "google_calendar_relative_date",
        "agent_id": "google",
        "prompt": "¿Qué tengo en el calendario esta semana?",
        "expected_tool": "get_current_time",
    },
]
