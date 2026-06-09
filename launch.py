"""PyInstaller entry point.

A thin wrapper around ``app.py`` that auto-opens the user's default browser
at ``http://127.0.0.1:5057`` a moment after Flask starts. This file is the
entry the .app / .exe boots into.

Two modes:

  Default                 -> start Flask + open browser
  --pipeline ARGS...      -> run reels_gui_pipeline.main() directly with ARGS

The second mode exists because PyInstaller-frozen apps don't ship a separate
Python binary -- ``sys.executable`` is the bootloader itself. So when Flask
needs to spawn the heavy transcription/encode pipeline as a child process,
it re-invokes the bootloader with ``--pipeline``, which routes here instead
of starting another Flask server. This keeps the child process inside the
.app's bundled Python (with mlx-whisper, ctranslate2, etc.) instead of
silently falling through to whatever ``python3`` the user has on PATH.
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


def _setup_frozen_paths():
    """Chdir into _MEIPASS and prepend bundled bin/ to PATH. Shared by
    both Flask mode and pipeline mode so ffmpeg + relative file lookups
    work identically in both."""
    if getattr(sys, "frozen", False):
        bundle_dir = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        os.chdir(bundle_dir)
        bin_dir = bundle_dir / "bin"
        if bin_dir.exists():
            os.environ["PATH"] = (
                f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
            )


def _run_pipeline_mode(args):
    """Route to reels_gui_pipeline.main() as if this bootloader were
    `python3 reels_gui_pipeline.py ARGS...`. Used when Flask spawns a
    subprocess to do the heavy work.
    """
    _setup_frozen_paths()
    # The pipeline reads its CLI from sys.argv[1:], so massage argv to
    # look like it was invoked directly.
    sys.argv = ["reels_gui_pipeline.py"] + list(args)
    import reels_gui_pipeline
    reels_gui_pipeline.main()


def _is_app_already_running(host: str = "127.0.0.1", port: int = 5057) -> bool:
    """Return True iff something is already serving HTTP on the GUI port.

    Used to short-circuit second-instance launches: when the user
    double-clicks the .app icon while it's already running, this prevents
    a second Flask spawn and -- more importantly -- prevents the second
    bootloader from popping yet another browser tab pointing at the same
    URL. Without this guard, every repeat click adds another tab; the user
    reported ending up with 3 tabs during a single editing session.
    """
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        result = s.connect_ex((host, port))
        s.close()
        return result == 0
    except Exception:
        return False


def main() -> None:
    # Pipeline mode: re-entrant invocation from app.py's job spawner.
    if len(sys.argv) > 1 and sys.argv[1] == "--pipeline":
        _run_pipeline_mode(sys.argv[2:])
        return

    _setup_frozen_paths()

    # Single-instance guard: if Flask is already up on 5057, exit silently.
    # We deliberately do NOT call webbrowser.open() here -- every prior
    # launch would have added another tab pointing at the same URL, and
    # the user reported ending up with 3 tabs from a single editing session
    # while clicking the .app icon a few times. The existing tab is still
    # there; macOS will surface it when the user activates Safari/Chrome.
    if _is_app_already_running():
        sys.stderr.write(
            "Reels AI Editor is already running on http://127.0.0.1:5057/.\n"
            "Switch to your browser tab to use it.\n"
        )
        return

    threading.Thread(
        target=_open_browser_when_ready,
        args=("http://127.0.0.1:5057/",),
        daemon=True,
    ).start()

    from app import app  # imports run _preflight_check on the way in
    app.run(host="127.0.0.1", port=5057, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
