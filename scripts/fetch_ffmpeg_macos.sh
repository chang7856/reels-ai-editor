#!/bin/bash
# Fetch static ffmpeg + ffprobe binaries for the current macOS architecture
# and stage them under ./bin/ so PyInstaller can bundle them into the .app.
#
# This is what makes the app "drag and drop" — the user never has to
# `brew install ffmpeg` themselves.
#
# Source: https://evermeet.cx/ffmpeg/ — a community-maintained mirror of
# static, signed-by-author ffmpeg builds for macOS (both arm64 and x86_64).

set -eo pipefail
cd "$(dirname "$0")/.."

# Target arch can be overridden by the caller (build_macos.sh derives it from
# the Python interpreter, which is what actually matters). Fall back to the
# shell arch if not set.
ARCH="${TARGET_ARCH:-$(uname -m)}"
if [ "$ARCH" = "arm64" ]; then
  FFMPEG_URL="https://www.osxexperts.net/ffmpeg711arm.zip"
  FFPROBE_URL="https://www.osxexperts.net/ffprobe711arm.zip"
  LABEL="arm64"
elif [ "$ARCH" = "x86_64" ]; then
  # osxexperts.net does not publish a 7.1.1 Intel zip (only arm), so we
  # use 7.1 -- behavior is identical for what the pipeline does.
  FFMPEG_URL="https://www.osxexperts.net/ffmpeg71intel.zip"
  FFPROBE_URL="https://www.osxexperts.net/ffprobe71intel.zip"
  LABEL="intel"
else
  echo "Unsupported arch: $ARCH"
  exit 1
fi

mkdir -p bin
TMP=$(mktemp -d)
trap "rm -rf $TMP" EXIT

# Fallback to evermeet.cx if osxexperts is unreachable
fetch_one() {
  local name="$1"
  local primary="$2"
  local out="bin/$name"

  if [ -x "$out" ]; then
    echo "  $name already present, skipping download"
    return 0
  fi

  echo "  fetching $name ($LABEL)..."
  if curl -fsSL -o "$TMP/$name.zip" "$primary"; then
    unzip -q -o "$TMP/$name.zip" -d "$TMP/$name.d"
    # Find the binary inside the zip (it's usually just one file)
    found=$(find "$TMP/$name.d" -type f -name "$name" | head -1)
    if [ -z "$found" ]; then
      echo "    primary zip did not contain $name, trying evermeet..."
    else
      cp "$found" "$out"
      chmod +x "$out"
      echo "    OK: $out"
      return 0
    fi
  fi

  echo "  falling back to evermeet.cx for $name..."
  # evermeet.cx serves universal binaries
  curl -fsSL -o "$TMP/$name.zip" "https://evermeet.cx/ffmpeg/getrelease/$name/zip"
  unzip -q -o "$TMP/$name.zip" -d "$TMP/$name.d2"
  found=$(find "$TMP/$name.d2" -type f -name "$name" | head -1)
  if [ -z "$found" ]; then
    echo "    ERROR: could not find $name in evermeet zip either"
    exit 1
  fi
  cp "$found" "$out"
  chmod +x "$out"
  echo "    OK: $out (universal via evermeet)"
}

fetch_one ffmpeg "$FFMPEG_URL"
fetch_one ffprobe "$FFPROBE_URL"

echo ""
echo "Staged binaries:"
ls -lh bin/
file bin/ffmpeg bin/ffprobe
