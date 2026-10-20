"""HTML report -> PNG using the already-installed Google Chrome in headless mode
(no extra dependency). The page height isn't known in advance, so it's
measured first (a tiny script in the report stores the body height in a
data attribute that --dump-dom echoes back), then captured at that height."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
REPORT_WIDTH = 480
SCALE = 2
# Telegram photos: width + height must stay <= 10000 px.
MAX_PHOTO_PX = 10000

HEIGHT_PROBE = "<script>document.documentElement.dataset.h = Math.ceil(document.body.getBoundingClientRect().height);</script>"


class RenderError(RuntimeError):
    pass


def _run_chrome(args: list[str], timeout: int = 45) -> subprocess.CompletedProcess:
    if not CHROME.exists():
        raise RenderError("Google Chrome no está instalado en /Applications")
    # Throwaway profile so this never collides with the user's open Chrome.
    with tempfile.TemporaryDirectory() as profile:
        cmd = [str(CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars",
               "--no-first-run", f"--user-data-dir={profile}", *args]
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise RenderError("Chrome tardó demasiado en renderizar") from exc


def measure_height(html_path: Path) -> int:
    result = _run_chrome(["--dump-dom", "--virtual-time-budget=3000",
                          f"--window-size={REPORT_WIDTH},800", html_path.resolve().as_uri()])
    match = re.search(r'data-h="(\d+)"', result.stdout)
    if not match:
        raise RenderError("no se pudo medir la altura del reporte")
    return int(match.group(1))


def screenshot(html_path: Path, png_path: Path) -> tuple[Path, int]:
    """Returns (png_path, pixel_height)."""
    height = measure_height(html_path)
    _run_chrome([f"--window-size={REPORT_WIDTH},{height}", f"--force-device-scale-factor={SCALE}",
                 f"--screenshot={png_path.resolve()}", html_path.resolve().as_uri()])
    if not png_path.exists() or png_path.stat().st_size == 0:
        raise RenderError("Chrome no generó la captura")
    return png_path, height * SCALE


def fits_telegram_photo(pixel_height: int) -> bool:
    return REPORT_WIDTH * SCALE + pixel_height <= MAX_PHOTO_PX
