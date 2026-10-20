# agents/reminders.yaml

Agente dedicado de 4 tools (`set_reminder`, `list_reminders`, `cancel_reminder`, `get_current_time`) con `qwen3:8b`.

Se separó de `google.yaml` para respetar el límite de tools por agente (ver [project-lechu-tool-count-reliability]). El prompt le exige llamar a `get_current_time` antes de `set_reminder` para resolver expresiones como "mañana".

Selección: `core/router.py` tiene una regla `reminders` con las palabras recordatorio, recordame, avisame y alarma. "Recordá que..." sigue yendo a `general` (memoria de datos).

Benchmark: casos `reminders_set`, `reminders_list`, `reminders_cancel` en `benchmark/cases.py`; 9/9 con 3 corridas (2026-10-20).

Términos: [GLOSSARY](../GLOSSARY.md)
