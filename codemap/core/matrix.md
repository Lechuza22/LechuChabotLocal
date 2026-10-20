# core/matrix.py

Ítems de la matriz de prioridades (LechuPasto > Recordatorios > Matriz). Se guardan en el mismo archivo que recordatorios y notas (`data/reminders.db`, tabla `matrix_items`), así hay un solo lugar para respaldar.

- Cuadrantes (`QUADRANTS`): `inbox` ("Sin clasificar", la bandeja donde caen los ítems nuevos), `urgent` (Urgente), `not_urgent` (No urgente), `postpone` (Postergar), `late` (Retrasado).
- `add_item(text, quadrant="inbox")`: agrega al final del cuadrante.
- `list_open()`: ítems abiertos agrupados por cuadrante, en el orden en que se acomodaron.
- `set_order(quadrant, item_ids)`: deja exactamente esos ítems, en ese orden, dentro del cuadrante; es lo que se llama después de cada arrastre (sirve para mover entre cuadrantes y para reordenar).
- `update_text`, `complete` (hecho: queda en la base pero se oculta del tablero) y `delete` (marca `deleted`).

Términos: [GLOSSARY](../GLOSSARY.md)
