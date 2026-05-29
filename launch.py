"""PyInstaller entry point.

A thin wrapper around ``app.py`` that auto-opens the user's default browser
at ``http://127.0.0.1:5057`` a moment after Flask starts. This file is the
entry the .app / .exe boots into.
"""
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _open_browser_when_ready(url: str, attempts: int = 30) -> None:
    import urllib.request
    for _ in range(attempts):
        try:
            urllib.request.urlopen(url, timeout=0.5)
            webbrowser.open(url)
            return
        except Exception:
            time.sleep(0.5)
    webbrowser.open(url)  # try anyway


def main() -> None:
    # When frozen by PyInstaller the working directory is the temporary
    # `_MEIPASS` extraction dir. Move into it so relative paths (templates/,
    # reels_memory.json) resolve.
    if getattr(sys, "frozen", False):
        os.chdir(Path(sys._MEIPASS))  # type: ignore[attr-defined]

    threading.Thread(
        target=_open_browser_when_ready,
        args=("http://127.0.0.1:5057/",),
        daemon=True,
    ).start()

    from app import app  # imports run _preflight_check on the way in
    app.run(host="127.0.0.1", port=5057, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
