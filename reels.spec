# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — Reels AI Editor

Produces a self-contained .app on macOS (universal2 if Python supports it) or
a single-folder bundle on Windows / Linux. ffmpeg is *not* embedded; users are
told to install it via brew/winget in the README, which keeps the download
under ~150 MB instead of ~600 MB.
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
ROOT = Path(SPECPATH)

datas = [
    (str(ROOT / "templates"), "templates"),
    (str(ROOT / "reels_memory.json"), "."),
    (str(ROOT / "reels_gui_pipeline.py"), "."),
]

# Faster-whisper bundles its own libs + tokenizer files
datas += collect_data_files("faster_whisper")
datas += collect_data_files("opencc", subdir="dictionary")
datas += collect_data_files("ctranslate2")

hiddenimports = (
    collect_submodules("faster_whisper")
    + collect_submodules("opencc")
    + ["PIL.Image", "PIL.ImageDraw", "PIL.ImageFont", "PIL.ImageEnhance", "PIL.ImageFilter", "PIL.ImageStat"]
)

a = Analysis(
    ["launch.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "scipy", "pandas", "tkinter", "test", "unittest"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ReelsAIEditor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI mode — the actual UI is the browser tab
    target_arch=None,  # let PyInstaller pick host arch
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ReelsAIEditor",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="ReelsAIEditor.app",
        icon=None,
        bundle_identifier="com.jessiedchang.reelsaieditor",
        info_plist={
            "CFBundleName": "Reels AI Editor",
            "CFBundleDisplayName": "Reels AI Editor",
            "CFBundleVersion": "1.0.0",
            "CFBundleShortVersionString": "1.0.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": "MIT — © 2026 Jessie D. Chang",
        },
    )
