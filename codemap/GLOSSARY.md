# Glosario

### daemon
Programa que corre en segundo plano sin ventana, esperando trabajo.

**En este proyecto:** `daemon/lechu_daemon.py` revisa cada 20 segundos si hay recordatorios vencidos.

### launchd
El gestor de procesos de macOS: arranca y reinicia programas automáticamente.

**En este proyecto:** `install_daemon.sh` registra el daemon como "launch agent" para que arranque al iniciar sesión.

### Keychain
Almacén cifrado de contraseñas del sistema operativo.

**En este proyecto:** `core/secrets.py` guarda ahí el token y el chat id de Telegram, nunca en archivos.

### tool
Función que el modelo puede pedir ejecutar, descrita con un nombre y parámetros.

**En este proyecto:** `set_reminder` es una tool registrada en `TOOL_REGISTRY`.

### agente
Un modelo más un prompt y una lista acotada de tools.

**En este proyecto:** cada `agents/*.yaml`; `reminders` tiene 4 tools.

### recordatorio repetitivo
Recordatorio con `repeat` diario o semanal que se reprograma solo al dispararse.

**En este proyecto:** `reminders.pop_due` calcula el próximo horario futuro.

### pipeline
Secuencia de pasos que se ejecutan en orden, donde cada uno recibe lo que produjeron los anteriores.

**En este proyecto:** una tarea de LechuPasto declara sus pasos en `task.yaml` (traer agenda, traer mails, resumir).

### headless
Un programa con interfaz gráfica que corre sin mostrar ventana.

**En este proyecto:** `render.py` usa Chrome headless para convertir el reporte HTML en una imagen.
