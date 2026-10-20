"""Background process: fires due reminders even when the Lechu app is closed.

Run by launchd (see install_daemon.sh). Deliberately tiny and model-free -
no Ollama needed for reminders, so it can't be broken by the LLM being down.
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import briefing, reminders  # noqa: E402
from core.notify import notify, notify_telegram  # noqa: E402

POLL_SECONDS = 20
BRIEFING_RETRY = timedelta(minutes=10)
_briefing_retry_at: datetime | None = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("lechu-daemon")


def tick() -> None:
    for item in reminders.pop_due(datetime.now()):
        logger.info("firing reminder #%s: %s", item["id"], item["message"])
        notify("Lechu 🦉 Recordatorio", item["message"])


def briefing_tick() -> None:
    """Morning summary: Mon-Fri from 09:00, once a day; a Mac that was off or
    asleep at 09:00 sends it as soon as the daemon is running again."""
    global _briefing_retry_at
    now = datetime.now()
    if not briefing.is_due(now) or (_briefing_retry_at and now < _briefing_retry_at):
        return
    logger.info("building morning briefing")
    if notify_telegram(briefing.build_briefing(now)):
        briefing.mark_sent(now)
        _briefing_retry_at = None
        logger.info("morning briefing sent")
    else:
        _briefing_retry_at = now + BRIEFING_RETRY
        logger.warning("briefing not delivered, retrying at %s", _briefing_retry_at.strftime("%H:%M"))


def main() -> None:
    logger.info("daemon started")
    while True:
        try:
            tick()
            briefing_tick()
        except Exception:  # keep the loop alive no matter what
            logger.exception("tick failed")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
