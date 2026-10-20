# core/tools/reminder_tools.py

Expone recordatorios y notas al modelo como tools registradas en `TOOL_REGISTRY`.

- `set_reminder(message, when, repeat)`: valida formato, rechaza horarios pasados (salvo repetitivos) y guarda.
- `add_note(title, body)`: guarda una nota (sin fecha, nunca avisa).
- `list_reminders()`: devuelve `{"reminders": [...], "notes": [...]}` con ids; el contenido de las notas se recorta a 400 caracteres.
- `cancel_reminder(match=None, reminder_id=None)`: cancela o borra por palabras del texto (preferido) o por id. Si varias coinciden, devuelve la lista para que el modelo le pregunte al usuario; si ninguna, un error que lo manda a `list_reminders`.

Ninguna requiere confirmación: son acciones locales y reversibles. Las usan `agents/reminders.yaml` (Lechu) y el chat de LechuPasto.

Términos: [GLOSSARY](../../GLOSSARY.md)

## agenda_tools.py

`add_calendar_event(title, start, duration_minutes, location, notes)`: agenda un evento en Google Calendar e invita siempre al usuario (el modelo no puede indicar invitados). **Requiere confirmación**: el chat de LechuPasto muestra una tarjeta Confirmar/Cancelar antes de ejecutarla. Rechaza horarios pasados.
