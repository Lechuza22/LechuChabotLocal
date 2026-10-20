# lechupasto/steps.py, render.py, report.py

## steps.py
Catálogo de pasos disponibles para un pipeline: `calendar_events`, `emails` y `llm_summarize`. Los dos primeros traen datos con código (reutilizan `core/briefing.py`); solo `llm_summarize` usa el modelo local. Esta separación es deliberada: con qwen3:8b, que el código junte los datos y el modelo solo redacte es lo confiable.

## report.py
`build_report_html(title, subtitle, sections, footer)` arma un HTML de 480 px de ancho (se lee igual en el iframe de la app, en el navegador y como captura en el celular). `markdown_to_html` convierte las viñetas y negritas que escribe el modelo.

## render.py
Usa Google Chrome en modo headless, sin dependencias nuevas. Mide la altura real del contenido (un script del reporte la guarda en un atributo que `--dump-dom` devuelve) y después captura a esa altura, con escala 2. `fits_telegram_photo` indica si entra como foto (ancho + alto <= 10000 px) o si hay que mandarla como documento. Usa un perfil temporal para no chocar con el Chrome abierto del usuario.

Términos: [GLOSSARY](../GLOSSARY.md)
