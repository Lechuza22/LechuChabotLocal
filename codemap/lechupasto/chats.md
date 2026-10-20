# lechupasto/chats.py

Conversaciones del chat de LechuPasto, guardadas en su propia base (`data/pasto_chats.db`) para que no aparezcan en el historial de Lechu.

- Tablas: `conversations` (título, abierta/cerrada, borrada) y `messages` (cada mensaje tal cual lo usa el loop del modelo, en JSON: usuario, asistente con tool_calls, tool). El mensaje de sistema no se guarda: se reconstruye en cada turno con la fecha actual.
- `create_chat`, `open_chats` (pestañas, en orden estable), `archived_chats` (cerradas con mensajes, más nuevas primero), `load_messages`, `append_messages`, `set_title_from` (el primer mensaje nombra la pestaña de inmediato), `set_auto_title` (aplica el resumen generado por el modelo salvo que el usuario ya haya puesto el suyo), `rename_chat` (título manual; marca `title_manual` y desde ahí el resumen automático nunca lo reemplaza), `close_chat`, `reopen_chat`, `delete_chat` (borrado lógico).

Cerrar una pestaña no borra la conversación: pasa al historial (botón de reloj) desde donde se reabre o se elimina.

Términos: [GLOSSARY](../GLOSSARY.md)
