"""Background process: fires due reminders and runs LechuPasto's scheduled
tasks, even when no app is open. Run by launchd (see install_daemon.sh).

Reminders are model-free, so they can't be broken by Ollama being down.
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import reminders  # noqa: E402
from core.notify import notify  # noqa: E402
from lechupasto import engine  # noqa: E402

POLL_SECONDS = 20

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("lechu-daemon")


def tick() -> None:
    for item in reminders.pop_due(datetime.now()):
        logger.info("firing reminder #%s: %s", item["id"], item["message"])
        notify("Lechu 🦉 Recordatorio", item["message"])


def main() -> None:
    logger.info("daemon started")
    while True:
        try:
            tick()
            engine.run_due_tasks()
        except Exception:  # keep the loop alive no matter what
            logger.exception("tick failed")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
