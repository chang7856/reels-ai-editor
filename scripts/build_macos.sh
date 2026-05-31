#!/bin/bash
# Build the macOS .app bundle (run on the architecture you want to ship).
#
# Run this on:
#   * Apple Silicon Mac -> produces ReelsAIEditor-macOS-arm64.dmg
#   * Intel Mac          -> produces ReelsAIEditor-macOS-intel.dmg
#
# You can't cross-compile to the other arch from one machine without a CI.
# Use the GitHub Actions workflow (.github/workflows/release.yml) to get both
# from the same git tag.

set -eo pipefail
cd "$(dirname "$0")/.."

# Build arch comes from the Python interpreter, NOT the shell. On Apple
# Silicon you can run an Intel anaconda through Rosetta and uname will still
# say "arm64", but the produced .app would be x86_64. So ask Python directly.
PY="${PYTHON:-python3}"
ARCH=$("$PY" -c "import platform; print(platform.machine())")
if [ "$ARCH" = "arm64" ]; then
  SUFFIX="arm64"
elif [ "$ARCH" = "x86_64" ]; then
  SUFFIX="intel"
else
  echo "Unsupported arch: $ARCH"
  exit 1
fi

echo "Building Reels AI Editor for macOS ${SUFFIX} (interpreter: $PY)"

# Stage ffmpeg + ffprobe under bin/ so PyInstaller bundles them into the .app.
# This is the whole point of "drag and drop install" -- users never touch
# Terminal. We pass TARGET_ARCH so cross-arch builds (Intel anaconda on an
# Apple Silicon shell) get the correct ffmpeg flavor.
rm -rf bin
TARGET_ARCH="$ARCH" bash scripts/fetch_ffmpeg_macos.sh

# Stage the CT2-quantised opus-mt-zh-en translator. ~80 MB once converted.
# This is the big win that lets us skip a second Whisper pass for the EN
# subtitles (used to take ~75s on a 3-min clip).
PYTHON="$PY" bash scripts/fetch_translator.sh

"$PY" -m pip install --upgrade pyinstaller
"$PY" -m pip install -r requirements.txt

rm -rf build dist
"$PY" -m PyInstaller reels.spec --clean --noconfirm

APP="dist/ReelsAIEditor.app"
if [ ! -d "$APP" ]; then
  echo "Build failed -- .app not produced"
  exit 1
fi

DMG="dist/ReelsAIEditor-macOS-${SUFFIX}.dmg"
rm -f "$DMG"

# Build a tiny DMG with a drag-to-Applications shortcut
echo "Packaging ${DMG}"
mkdir -p dist/dmgroot
cp -R "$APP" dist/dmgroot/
ln -sf /Applications dist/dmgroot/Applications

hdiutil create -fs HFS+ -srcfolder dist/dmgroot \
  -format UDZO -imagekey zlib-level=9 \
  -volname "Reels AI Editor" "$DMG"

rm -rf dist/dmgroot
echo "OK: ${DMG} ready"
