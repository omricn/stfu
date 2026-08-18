# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for S.TFU: one file, windowed, no console.

The .exe's own icon (Explorer, taskbar, the properties dialog, and now every
Tk window's title bar -- F7) is generated with Pillow in stfu/appicon.py
rather than checked into the repo as a binary asset -- the same choice
tray.py makes for the tray icon at runtime, for the same reason: one less
asset to keep in sync, path-resolve when frozen, or lose track of. This spec
just renders that same artwork into the .ico PyInstaller applies to the exe
itself. It is unrelated to the tray icon, which tray.py draws fresh every
time the app's state changes and deliberately keeps as a separate, simpler
piece of art (a plain coloured circle) because it carries live state a
static app icon cannot.

matplotlib, sounddevice, and pystray each carry non-Python payloads
(mpl-data, the PortAudio DLL, and a platform-specific backend chosen by
if/elif on sys.platform) that PyInstaller's default analysis can miss.
PyInstaller and pyinstaller-hooks-contrib both ship hooks that collect these
automatically, and this project's dependency check confirmed both hooks are
present -- but the imports and matplotlib data files are also declared
explicitly below, per the plan, as a second line of defence against a hook
version drifting or going missing.
"""

import sys
import tempfile
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

# The spec's own directory is not guaranteed to be on sys.path just because
# PyInstaller is invoked from there (build.ps1 does `cd` first, but nothing
# here should depend on that staying true) -- add it explicitly so `stfu` is
# importable before Analysis() below does its own, separate import discovery
# for what ships *inside* the exe. A spec file has no `__file__` of its own
# (it is exec()'d, not imported) -- SPECPATH is the name PyInstaller injects
# into this namespace for exactly this purpose.
sys.path.insert(0, str(Path(SPECPATH).resolve()))  # noqa: F821

from stfu.appicon import ICON_SIZES, draw_icon  # noqa: E402

_icon_image = draw_icon(max(ICON_SIZES))
_icon_path = str(Path(tempfile.gettempdir()) / "stfu_build_icon.ico")
_icon_image.save(_icon_path, sizes=[(size, size) for size in ICON_SIZES])

datas = collect_data_files("matplotlib")
# Bundled default sounds and pictures, preserving the tree so assets_dir()
# finds them under sys._MEIPASS at runtime.
datas += [("stfu/assets", "stfu/assets")]

a = Analysis(
    ["stfu/__main__.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "pystray",
        "pystray._win32",
        "PIL._tkinter_finder",
        "matplotlib.backends.backend_tkagg",
        "sounddevice",
        "miniaudio",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="stfu",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX-compressed executables are a common false-positive trigger for
    # antivirus/Defender heuristics; skipping it is worth the larger file for
    # a first build of a tool that already looks unusual (it watches a mic).
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon_path,
)
