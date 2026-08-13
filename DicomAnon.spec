# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['DicomAnon.py'],
    pathex=[],
    binaries=[],
    datas=[],
    # No pydicom codec hidden imports: the app never reads or writes pixel data,
    # it passes it through as raw bytes. The old pydicom.encoders.* entries did
    # not exist in pydicom 3 anyway, which renamed that package to pydicom.pixels.
    hiddenimports=[],
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
    [],
    exclude_binaries=True,
    name='DicomAnon',
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
    icon=['DicomAnon.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DicomAnon',
)
app = BUNDLE(
    coll,
    name='DicomAnon.app',
    icon='DicomAnon.icns',
    bundle_identifier=None,
)
