# Lechu 🦉 (Ollama + Streamlit)

Chatbot 100% offline: interfaz Streamlit, inferencia con Ollama local,
memoria persistente en SQLite, acceso a carpetas whitelisteadas, agentes con
roles/tools específicas y skills en Markdown para automatizar tareas.

Fase 1 (esta versión): chat + memoria + filesystem + agentes/tools + skills.
Fase 2 (futura): integraciones con Google Drive/Gmail/Calendar — requieren
su propio proyecto OAuth en Google Cloud y conexión a internet.

## Abrir la app

**Opción rápida:** doble click en `Lechu.app`. Arranca Ollama y el servidor
si hace falta (o reusa los que ya estén corriendo) y abre una ventana nativa
de Mac (vía `pywebview`, sin barra de navegador ni ventana de Terminal)
apuntando al servidor local. Podés arrastrarlo a `/Applications` o al Dock.
La primera vez que lo abras, macOS va a avisar que es de un desarrollador no
identificado (Gatekeeper) — hacé click derecho → Abrir para confirmar una
sola vez. Los logs quedan en `data/lechu_launcher.log`. Cerrar la ventana
cierra la app, pero el servidor Streamlit/Ollama siguen corriendo en
segundo plano (así la próxima apertura es instantánea).

**Setup manual / desarrollo:**

```bash
ollama serve  # si no está corriendo ya
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Configuración (`config.yaml`)

- `filesystem.whitelisted_folders`: carpetas a las que el chatbot puede leer
  y escribir. Por defecto: `/Users/lechu/ChatbotSandbox`. Agregá más rutas
  absolutas a la lista para habilitarlas.
- `max_tool_iterations`: tope de llamadas a herramientas por turno antes de
  cortar (evita loops infinitos).
- `default_agent`: id del agente que arranca por defecto.

## Agregar un agente

Creá un archivo `agents/mi_agente.yaml`:

```yaml
id: mi_agente
name: "Nombre visible"
model: mistral        # cualquier modelo que tengas en `ollama list`
system_prompt: |
  Instrucciones de rol para este agente.
tools:
  - list_dir
  - read_file
  - write_file
  - delete_file
  - remember_fact
  - recall_facts
```

Se recarga reiniciando la app.

## Agregar una skill

Ver [skills/README.md](skills/README.md). Las skills se recargan en caliente
con el botón "Recargar skills" en la sidebar, sin reiniciar la app.

## Agregar una tool nueva

Definí la función en `core/tools/`, registrala con `register(Tool(...))`
(ver `core/tools/filesystem.py` como referencia), y agregá su nombre a la
lista `tools:` de los agentes que deban usarla. Si la acción es destructiva
o irreversible, marcá `requires_confirmation=True` para que la UI pida
confirmación antes de ejecutarla.

## Memoria

- `data/memory.db` (SQLite, no versionado) guarda conversaciones, mensajes y
  hechos recordados (`facts`). Se puede inspeccionar y editar a mano desde
  la sidebar ("Memoria") o directamente con `sqlite3 data/memory.db`.
