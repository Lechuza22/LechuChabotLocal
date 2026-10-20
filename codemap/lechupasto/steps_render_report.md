# lechupasto/steps.py, render.py, report.py

## steps.py
Catálogo de pasos disponibles para un pipeline: `calendar_events`, `emails`, `email_digest` (mensajes completos y documentos enlazados vía [core/mail_context](../core/mail_context.md)), `commented_docs`, `unread_older` (mails sin leer de los 7 días previos a la ventana, listados por código; no se marca nada como leído) y `llm_summarize_digest`. Los primeros traen datos con código; solo `llm_summarize_digest` usa el modelo local, con contexto de 8192 tokens, y los documentos sin comentarios abiertos entran solo con su título (el modelo de 8B presentaba el texto de un documento como si fueran comentarios). Esta separación es deliberada: con qwen3:8b, que el código junte los datos y el modelo solo redacte es lo confiable.

## report.py
`build_report_html(title, subtitle, sections, footer)` arma un HTML de 480 px de ancho (se lee igual en el iframe de la app, en el navegador y como captura en el celular). Las secciones `mails` y `docs` las arma el código: `mails` lista remitente, asunto y fecha (12 como máximo); `docs` lista los documentos con comentarios abiertos y las citas. `markdown_to_html` convierte las viñetas y negritas que escribe el modelo.

## render.py
Usa Google Chrome en modo headless, sin dependencias nuevas. Mide la altura real del contenido (un script del reporte la guarda en un atributo que `--dump-dom` devuelve) y después captura a esa altura, con escala 2. `fits_telegram_photo` indica si entra como foto (ancho + alto <= 10000 px) o si hay que mandarla como documento. Usa un perfil temporal para no chocar con el Chrome abierto del usuario.

Términos: [GLOSSARY](../GLOSSARY.md)
