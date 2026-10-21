# core/tools/drive_tools.py

Tools de Google Drive: buscar archivos, leerlos y escribirlos (esta última pide confirmación).

- `read_drive_file(file_id)`: acepta un id o **cualquier link** de Docs, Sheets, Slides o Drive (`extract_file_id`). Los Docs y Presentaciones se exportan como texto; los **Sheets se exportan como xlsx y se leen todas las pestañas** (`_spreadsheet_to_text`, bajo encabezados `## Hoja: nombre`; con el export CSV solo se veía la primera); los PDF se extraen con pypdf. El contenido se recorta a 12.000 caracteres (`MAX_READ_CHARS`) con una nota `truncated`, para no inundar el contexto del modelo local.
- `search_drive_files(query)`: búsqueda por nombre.
- `write_drive_file(...)`: crea o sobrescribe; requiere confirmación.

Términos: [GLOSSARY](../../GLOSSARY.md)
