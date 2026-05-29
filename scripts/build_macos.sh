#!/bin/bash
# Build the macOS .app bundle (run on the architecture you want to ship).
#
# Run this on:
#   * Apple Silicon Mac → produces ReelsAIEditor-macOS-arm64.dmg
#   * Intel Mac          → produces ReelsAIEditor-macOS-intel.dmg
#
# You can't cross-compile to the other arch from one machine without a CI.
# Use the GitHub Actions workflow (.github/workflows/release.yml) to get both
# from the same git tag.

set -euo pipefail
cd "$(dirname "$0")/.."

ARCH=$(uname -m)
if [ "$ARCH" = "arm64" ]; then
  SUFFIX="arm64"
elif [ "$ARCH" = "x86_64" ]; then
  SUFFIX="intel"
else
  echo "Unsupported arch: $ARCH"
  exit 1
fi

echo "→ Building Reels AI Editor for macOS $SUFFIX…"

python3 -m pip install --upgrade pyinstaller
python3 -m pip install -r requirements.txt

rm -rf build dist
python3 -m PyInstaller reels.spec --clean --noconfirm

APP="dist/ReelsAIEditor.app"
if [ ! -d "$APP" ]; then
  echo "Build failed — .app not produced"
  exit 1
fi

DMG="dist/ReelsAIEditor-macOS-${SUFFIX}.dmg"
rm -f "$DMG"

# Build a tiny DMG with a drag-to-Applications shortcut
echo "→ Packaging $DMG…"
mkdir -p dist/dmgroot
cp -R "$APP" dist/dmgroot/
ln -sf /Applications dist/dmgroot/Applications

hdiutil create -fs HFS+ -srcfolder dist/dmgroot \
  -format UDZO -imagekey zlib-level=9 \
  -volname "Reels AI Editor" "$DMG"

rm -rf dist/dmgroot
echo "✓ $DMG ready"
