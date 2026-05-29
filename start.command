#!/bin/zsh
# Reels AI Editor — local launcher (macOS)
#
# Double-click this file to start the app. It will:
#   1. Move into the project directory
#   2. Check ffmpeg + Python dependencies
#   3. Launch the Flask server on http://127.0.0.1:5057
#   4. Open your default browser at that URL

set -e
cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  cat <<'EOF'

╭───────────────────────────────────────────────────────╮
│  ffmpeg is not installed.                              │
│                                                        │
│  Run this in Terminal once:                            │
│      brew install ffmpeg                               │
│                                                        │
│  Then double-click start.command again.                │
╰───────────────────────────────────────────────────────╯

EOF
  read -r -k "?Press any key to close this window…"
  exit 1
fi

PY=${PYTHON:-python3}

if ! "$PY" -c "import flask, faster_whisper, opencc, PIL" >/dev/null 2>&1; then
  echo "Installing Python dependencies (one-time, ~1 min)…"
  "$PY" -m pip install -r requirements.txt
fi

# Open the browser a moment after Flask boots so the page is ready when it opens
( sleep 1.5 ; open "http://127.0.0.1:5057" ) &

echo "→ Reels AI Editor running at http://127.0.0.1:5057"
echo "  (close this window when you're done to stop the app)"
exec "$PY" app.py
