# lechupasto/app.py

La interfaz de LechuPasto (NiceGUI, ventana nativa, puerto 8001). Una pestaña por tarea; a la izquierda la lista de corridas y los botones, a la derecha el reporte embebido en un iframe.

- `_task_panel(task)`: vista refrescable. Botones: Ejecutar ahora (corre `engine.run_task` fuera del hilo de la UI), Abrir carpeta (Finder), Abrir en el navegador y Enviar al bot.
- Los reportes se sirven con `app.add_static_files("/runs", tasks_dir)`.
- Lanzador: `LechuPasto.app` (mismo esquema que `Lechu.app`). `LECHUPASTO_DEV=1` sirve en un navegador en vez de ventana nativa.
- Pendiente: pestaña de chat y diseñador de tareas por prompt.

Términos: [GLOSSARY](../GLOSSARY.md)
