# core/agenda.py

Capa de Google Calendar para la pantalla Agenda de LechuPasto y para la tool de agendar del chat: leer un mes, crear eventos (siempre invitando al usuario) y borrarlos.

- `invite_email()`: la dirección invitada se guarda en el Keychain (`calendar_invite_email`), no en el repo ni en un prompt, así el modelo no puede cambiarla.
- `build_event_body(...)`: arma el evento (hora local con offset, duración, lugar, notas y el invitado). Separado de `create_event` para poder probarlo sin enviar nada.
- `create_event(...)`: inserta en el calendario principal; con invitado manda la invitación (`sendUpdates=all`). Duración por defecto: 60 minutos.
- `delete_event(id)`: borra y avisa a los invitados de la cancelación.
- `month_events(first, last)`: eventos del rango normalizados para la grilla (datetimes locales; los de todo el día traen fechas simples). `days_of(event)` devuelve todos los días en que aparece (en los de todo el día, el fin es exclusivo).
- `NotConnected`: se lanza si Google no está conectado; la UI lo muestra como aviso.

Dependencias: `core.google_auth`, `core.secrets`, API de Calendar v3.

Términos: [GLOSSARY](../GLOSSARY.md)
