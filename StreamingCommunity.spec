# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller bundle for the macOS app.

Three things here are not defaults and each one is a failure that only shows up
in the built app, never when running from source:

* ``imageio_ffmpeg`` is collected whole. It carries a static ffmpeg binary, and
  that binary is the whole reason the bundle works on a Mac with no Homebrew:
  ``ffmpeg_path.get_ffmpeg_exe()`` falls back to it. Collected as data, it is
  also the largest single thing in here.
* ``webview`` is collected whole. It injects its own JavaScript into every page
  from files that live beside the module, so a code-only import misses them and
  the window comes up blank.
* uvicorn's protocol, loop and lifespan implementations are imported by *name*
  at runtime. Nothing references them statically, so the analysis cannot see
  them and the server dies on its first request.

The icon is read from icon/AppIcon.icns, which is committed. Regenerate it with
``python icon/make_icon.py`` — that needs Pillow, a development dependency the
build itself must not require.
"""

from PyInstaller.utils.hooks import collect_all

datas = [("app/templates", "app/templates"), ("app/static", "app/static")]
binaries = []
hiddenimports = [
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan.on",
    "uvicorn.loops.asyncio",
    "uvicorn.loops.uvloop",
]

for package in ("imageio_ffmpeg", "webview"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    ["desktop.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Nothing in the app builds a UI with these, and tkinter in particular drags
    # in a whole framework the window does not use.
    excludes=["tkinter", "matplotlib", "pytest", "PIL"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StreamingCommunity",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="StreamingCommunity",
)

app = BUNDLE(
    coll,
    name="StreamingCommunity Downloader.app",
    icon="icon/AppIcon.icns",
    bundle_identifier="local.streamingcommunity.downloader",
    info_plist={
        "CFBundleName": "StreamingCommunity Downloader",
        "CFBundleDisplayName": "StreamingCommunity Downloader",
        "CFBundleShortVersionString": "3.0.0",
        "CFBundleVersion": "3.0.0",
        # Without this the window renders at 1x and every label looks soft.
        "NSHighResolutionCapable": True,
        # The panel talks to the source over plain HTTP in places, and to its
        # own loopback server always.
        "NSAppTransportSecurity": {"NSAllowsArbitraryLoads": True},
        # It is a window, not a menu-bar agent.
        "LSUIElement": False,
    },
)
