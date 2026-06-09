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

# Bundle ffmpeg + ffprobe so users never have to open Terminal to install
# anything. scripts/fetch_ffmpeg_*.{sh,bat} populates bin/ before build.
# On macOS the binary is plain "ffmpeg"; on Windows it's "ffmpeg.exe".
BIN = ROOT / "bin"
if BIN.is_dir():
    for entry in BIN.iterdir():
        if entry.is_file():
            datas.append((str(entry), "bin"))

# Bundle the CT2-quantised opus-mt-zh-en translator (~80 MB) so EN subs
# work fully offline with no first-run download. Populated by
# scripts/fetch_translator.sh before build.
TRANSLATOR = ROOT / "models" / "opus-mt-zh-en"
if TRANSLATOR.is_dir():
    for entry in TRANSLATOR.iterdir():
        if entry.is_file():
            datas.append((str(entry), "models/opus-mt-zh-en"))

# Faster-whisper bundles its own libs + tokenizer files
datas += collect_data_files("faster_whisper")
datas += collect_data_files("opencc", subdir="dictionary")
datas += collect_data_files("ctranslate2")

hiddenimports = (
    collect_submodules("faster_whisper")
    + collect_submodules("opencc")
    + collect_submodules("sentencepiece")
    + ["PIL.Image", "PIL.ImageDraw", "PIL.ImageFont", "PIL.ImageEnhance", "PIL.ImageFilter", "PIL.ImageStat",
       "ctranslate2", "sentencepiece"]
)

# mlx-whisper is the Apple Silicon transcription backend (Metal + ANE,
# 20-60x realtime). It only exists on macOS arm64; PyInstaller silently
# no-ops these on other platforms.
mlx_binaries = []
if sys.platform == "darwin":
    try:
        hiddenimports += collect_submodules("mlx_whisper")
        hiddenimports += collect_submodules("mlx")
        # mlx_whisper.timing imports scipy.signal -- without these explicitly
        # listed, PyInstaller silently misses scipy and the runtime falls
        # back to faster-whisper CPU (killing the 1-min budget).
        hiddenimports += collect_submodules("scipy")
        datas += collect_data_files("mlx_whisper")
        datas += collect_data_files("mlx")  # picks up mlx.metallib
        datas += collect_data_files("scipy")
        import mlx as _mlx_pkg
        _mlx_lib_dir = Path(_mlx_pkg.__file__).parent / "lib"
        if _mlx_lib_dir.is_dir():
            for entry in _mlx_lib_dir.iterdir():
                if entry.suffix in (".dylib", ".so", ".metallib"):
                    mlx_binaries.append((str(entry), "mlx/lib"))
    except Exception:
        pass

a = Analysis(
    ["launch.py"],
    pathex=[str(ROOT)],
    binaries=mlx_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # NOTE: scipy / unittest / test stay IN the bundle -- they get
        # imported transitively by mlx_whisper.timing -> scipy.signal ->
        # scipy._lib.array_api_compat which uses unittest at module load.
        # Dropping any of them silently kicks us onto the faster-whisper CPU
        # fallback (which kills our 1-min budget).
        "matplotlib", "pandas", "tkinter",
        "PyQt5", "PyQt6", "PySide2", "PySide6",  # GUI toolkits we don't use
        "IPython", "jupyter_client", "jupyter_core", "notebook",
        "sphinx", "pytest", "pip", "setuptools",  # dev tools
        "PIL.ImageQt",  # pulls Qt
        "torch", "tensorflow",  # heavy ML libs faster-whisper doesn't need
    ],
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

# Y2K pixel-scissors icon (regenerate with scripts/build_icon.sh).
_icon_path = ROOT / "assets" / "icon.icns"
_icon_arg = str(_icon_path) if _icon_path.is_file() else None

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="ReelsAIEditor.app",
        icon=_icon_arg,
        bundle_identifier="com.jessiedchang.reelsaieditor",
        info_plist={
            "CFBundleName": "Reels AI Editor",
            "CFBundleDisplayName": "Reels AI Editor",
            "CFBundleVersion": "1.1.0",
            "CFBundleShortVersionString": "1.1.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": "MIT — © 2026 Jessie D. Chang",
        },
    )
