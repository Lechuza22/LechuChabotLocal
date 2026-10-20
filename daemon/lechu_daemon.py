"""Background process: fires due reminders even when the Lechu app is closed.

Run by launchd (see install_daemon.sh). Deliberately tiny and model-free -
no Ollama needed for reminders, so it can't be broken by the LLM being down.
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
        except Exception:  # keep the loop alive no matter what
            logger.exception("tick failed")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
