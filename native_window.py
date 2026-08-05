import time
import urllib.request

import webview

URL = "http://localhost:8501"


def wait_until_up(url: str, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def main() -> None:
    wait_until_up(URL)
    webview.create_window("Lechu", URL, width=1100, height=800, min_size=(700, 500))
    webview.start()


if __name__ == "__main__":
    main()
