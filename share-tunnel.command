#!/bin/zsh
# Reels AI Editor — share via Cloudflare Tunnel (macOS)
#
# Double-click this file to:
#   1. Start the local Flask app
#   2. Open a free Cloudflare Tunnel pointing at it
#   3. Print the public https://*.trycloudflare.com URL AND copy it to your
#      clipboard so you can paste it straight into IG bio / DM / Slack.

set -e
cd "$(dirname "$0")"

if ! command -v cloudflared >/dev/null 2>&1; then
  cat <<'EOF'

╭───────────────────────────────────────────────────────╮
│  cloudflared is not installed.                         │
│                                                        │
│  Run this in Terminal once:                            │
│      brew install cloudflared                          │
│                                                        │
│  Then double-click share-tunnel.command again.         │
╰───────────────────────────────────────────────────────╯

EOF
  read -r -k "?Press any key to close this window…"
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is missing. Run: brew install ffmpeg"
  exit 1
fi

PY=${PYTHON:-python3}

# Start Flask in the background
echo "→ Starting Reels AI Editor on http://127.0.0.1:5057 …"
"$PY" app.py >/tmp/reels_app.log 2>&1 &
APP_PID=$!
trap 'echo "→ Stopping app (pid $APP_PID)…"; kill $APP_PID 2>/dev/null; exit' INT TERM EXIT

# Wait for Flask to come up
for _ in {1..30}; do
  if curl -sf http://127.0.0.1:5057/ >/dev/null 2>&1; then break; fi
  sleep 0.5
done

# Start the tunnel and capture its public URL
TUNNEL_LOG=/tmp/reels_tunnel.log
echo "→ Opening Cloudflare Tunnel…"
cloudflared tunnel --url http://127.0.0.1:5057 --no-autoupdate \
  > "$TUNNEL_LOG" 2>&1 &
TUNNEL_PID=$!
trap 'echo "→ Stopping app + tunnel"; kill $APP_PID 2>/dev/null; kill $TUNNEL_PID 2>/dev/null; exit' INT TERM EXIT

# Cloudflared logs the URL within a few seconds
URL=""
for _ in {1..40}; do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" | head -1 || true)
  if [ -n "$URL" ]; then break; fi
  sleep 0.5
done

if [ -z "$URL" ]; then
  echo "Tunnel didn't print a URL in time. Tail of log:"
  tail -20 "$TUNNEL_LOG"
  wait $TUNNEL_PID
  exit 1
fi

echo "$URL" | tr -d '\n' | pbcopy

cat <<EOF

╭───────────────────────────────────────────────────────╮
│  Reels AI Editor is now live at:                       │
│                                                        │
│      $URL
│                                                        │
│  ↑ this URL is on your clipboard. Paste & share.       │
│  Files auto-delete 15 minutes after upload.            │
│                                                        │
│  Close this window to stop the tunnel.                 │
╰───────────────────────────────────────────────────────╯

EOF

# Stay alive until the user closes the window
wait $TUNNEL_PID
