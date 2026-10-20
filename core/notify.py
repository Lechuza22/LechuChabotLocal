from __future__ import annotations

import logging
import subprocess

import httpx

from core.secrets import get_secret

logger = logging.getLogger(__name__)

# httpx logs every request URL at INFO, and Telegram's URL embeds the bot
# token - keep it out of any log file (the launchd daemon writes one).
logging.getLogger("httpx").setLevel(logging.WARNING)

# Keychain keys (service "Lechu"). Set once with e.g.
#   python -c "from core.secrets import set_secret; set_secret('telegram_bot_token', input())"
TELEGRAM_TOKEN_KEY = "telegram_bot_token"
TELEGRAM_CHAT_KEY = "telegram_chat_id"


def _applescript_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify_macos(title: str, message: str) -> bool:
    script = f"display notification {_applescript_quote(message)} with title {_applescript_quote(title)} sound name \"Glass\""
    try:
        subprocess.run(["osascript", "-e", script], check=True, timeout=10, capture_output=True)
        return True
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("macOS notification failed: %s", exc)
        return False


def notify_telegram(message: str) -> bool:
    """Silently skipped (returns False) when no bot is configured."""
    token = get_secret(TELEGRAM_TOKEN_KEY)
    chat_id = get_secret(TELEGRAM_CHAT_KEY)
    if not token or not chat_id:
        return False
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=15.0,
        )
        resp.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        logger.warning("Telegram notification failed: %s", type(exc).__name__)
        return False


def notify(title: str, message: str) -> None:
    notify_macos(title, message)
    notify_telegram(f"{title}\n{message}")
