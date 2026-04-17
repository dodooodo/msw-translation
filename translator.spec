# -*- mode: python ; coding: utf-8 -*-
import sys
import os

block_cipher = None

# Bundle the platform-specific translation helper binary
if sys.platform == "darwin":
    extra_datas = [("translate_apple", ".")]
elif sys.platform == "win32":
    extra_datas = [("translate_windows.exe", ".")]
else:
    extra_datas = []

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=extra_datas,
    hiddenimports=[
        "PyQt6",
        "PyQt6.QtWidgets",
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PIL",
        "capture.mac",
        "capture.cross",
        "ocr.mac",
        "ocr.windows",
        "ocr.tesseract",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if sys.platform == "darwin":
    # onedir mode — required for macOS .app bundles
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="MSW Translator",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
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
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="MSW Translator",
    )
    app = BUNDLE(
        coll,
        name="MSW Translator.app",
        icon=None,
        bundle_identifier="com.dodooodo.msw-translation",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSUIElement": True,  # no Dock icon (overlay app)
        },
    )
else:
    # Windows / Linux: single-file exe
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name="MSW Translator",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
