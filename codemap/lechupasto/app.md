# lechupasto/app.py

La interfaz de LechuPasto (NiceGUI, ventana nativa, puerto 8001). Navegación por cuadros, en una sola página con una vista activa (`nav["view"]`):

- **Inicio:** cuatro cuadros: Chat, Tareas, Recordatorios y Agenda. Tocar el logo vuelve acá.
- **Tareas:** un cuadro por tarea (horario y última corrida) y "Crear nueva tarea".
- **Tarea:** lista de corridas a la izquierda; reporte embebido en un iframe a la derecha. Botones: Ejecutar ahora, Abrir carpeta, Abrir en el navegador, Enviar al bot.
- **Crear nueva tarea:** nombre y descripción; se guarda como pedido en `tasks/_pedidos/*.md` (ignorado por git). Las tareas nuevas se diseñan con Claude Code a partir de esos pedidos: la app no tiene diseñador propio.
- **Recordatorios:** dos pestañas, Recordatorios (formulario, lista con fecha y repetición, historial "Ya avisados") y Notas (tarjetas; clic abre un editor con título y contenido largo). Consulta `reminders.signature()` cada 3 s y se refresca sola cuando el chat o Lechu cambian algo.
- **Agenda:** calendario mensual navegable (anterior / siguiente / Hoy / sincronizar) con los eventos de Google Calendar (marrón) y tus recordatorios pendientes (amarillo, con campana). Tocar un día abre su detalle (abrir en Google, borrar con confirmación, agendar ese día); "Agendar evento" abre el formulario (título, fecha, hora, duración, lugar, notas) e invita siempre al mail guardado en el Keychain. Caché de 2 minutos por mes. La casilla "Agregar también al calendario" de Recordatorios crea además un evento de 30 minutos.
- **Chat:** pestañas de conversaciones (+ nueva, x cierra, reloj = historial), guardadas en `chats.py`; no se puede cambiar de pestaña mientras se responde. El título de cada pestaña se resume solo tras la primera respuesta (`_summarize_title`, modelo local sin razonamiento, 2 a 5 palabras) y se renombra tocando el título de la pestaña activa (el diálogo tiene "Resumir con IA"). La fecha del día va arriba a la derecha y se actualiza cada minuto. Asistente de `lechupasto/agents/chat.yaml` (10 tools: mails —incluida `find_email_details`, que busca y lee en un paso—, Drive, calendario, `set_reminder`, `add_note`, `list_reminders`, `cancel_reminder`, `add_calendar_event`). Las notas y recordatorios son locales y reversibles y no piden confirmación; **agendar sí**, porque manda una invitación por mail: el chat muestra una tarjeta Confirmar/Cancelar (`_confirm_in_chat`; sin respuesta en 10 minutos cuenta como rechazo). El prompt del sistema incluye la hora actual y una tabla de los próximos 14 días (`_system_context`): sin ella el modelo de 8B resolvía mal "el jueves". Reutiliza `step_agent_stream` de `core/tool_loop.py`. `_FastClient` apaga el modo de razonamiento de qwen3, que hacía tardar ~40 s una consulta simple.

Los reportes se sirven con `app.add_static_files("/runs", tasks_dir)`. Lanzador: `LechuPasto.app`; `LECHUPASTO_DEV=1` sirve en un navegador en vez de ventana nativa.

Términos: [GLOSSARY](../GLOSSARY.md)
