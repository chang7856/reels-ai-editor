#!/usr/bin/env bash
# Build assets/icon.icns from the generator.
# Run from repo root.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ASSETS="$ROOT/assets"
PY="${PYTHON:-$ROOT/.venv-arm64/bin/python}"

if [[ ! -x "$PY" ]]; then
    # Fall back to whatever python3 is on PATH (CI / fresh checkouts).
    PY="$(command -v python3)"
fi

echo "Using python: $PY"

"$PY" "$ROOT/scripts/generate_icon.py"

if ! command -v iconutil >/dev/null 2>&1; then
    echo "iconutil not found -- skipping .icns build (non-mac host)."
    echo "Generated PNG is at $ASSETS/icon-1024.png"
    exit 0
fi

iconutil -c icns "$ASSETS/icon.iconset" -o "$ASSETS/icon.icns"
echo "Wrote $ASSETS/icon.icns"
ls -lh "$ASSETS/icon.icns"
