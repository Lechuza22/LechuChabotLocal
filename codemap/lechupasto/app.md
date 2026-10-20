# lechupasto/app.py

La interfaz de LechuPasto (NiceGUI, ventana nativa, puerto 8001). Navegación por cuadros, en una sola página con una vista activa (`nav["view"]`):

- **Inicio:** tres cuadros: Chat, Tareas y Recordatorios. Tocar el logo vuelve acá.
- **Tareas:** un cuadro por tarea (horario y última corrida) y "Crear nueva tarea".
- **Tarea:** lista de corridas a la izquierda; reporte embebido en un iframe a la derecha. Botones: Ejecutar ahora, Abrir carpeta, Abrir en el navegador, Enviar al bot.
- **Crear nueva tarea:** nombre y descripción; se guarda como pedido en `tasks/_pedidos/*.md` (ignorado por git). Las tareas nuevas se diseñan con Claude Code a partir de esos pedidos: la app no tiene diseñador propio.
- **Recordatorios:** dos pestañas, Recordatorios (formulario, lista con fecha y repetición, historial "Ya avisados") y Notas (tarjetas; clic abre un editor con título y contenido largo). Consulta `reminders.signature()` cada 3 s y se refresca sola cuando el chat o Lechu cambian algo.
- **Chat:** pestañas de conversaciones (+ nueva, x cierra, reloj = historial), guardadas en `chats.py`; no se puede cambiar de pestaña mientras se responde. Asistente de `lechupasto/agents/chat.yaml` (9 tools: mails —incluida `find_email_details`, que busca y lee en un paso—, Drive, calendario, `set_reminder`, `add_note`, `list_reminders`, `cancel_reminder`), sin confirmaciones porque lo que escribe es local y reversible. Reutiliza `step_agent_stream` de `core/tool_loop.py`. `_FastClient` apaga el modo de razonamiento de qwen3, que hacía tardar ~40 s una consulta simple.

Los reportes se sirven con `app.add_static_files("/runs", tasks_dir)`. Lanzador: `LechuPasto.app`; `LECHUPASTO_DEV=1` sirve en un navegador en vez de ventana nativa.

Términos: [GLOSSARY](../GLOSSARY.md)
