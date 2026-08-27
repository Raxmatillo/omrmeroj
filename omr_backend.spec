# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[('venv/Lib/site-packages/pyzbar/libiconv.dll', 'pyzbar'), ('venv/Lib/site-packages/pyzbar/libzbar-64.dll', 'pyzbar')],
    datas=[('.env', '.'),      (os.path.join(SPECPATH, 'app', 'utils', 'katex_render.js'), 'app/utils'),
      (os.path.join(SPECPATH, 'app', 'utils', 'katex_assets'), 'app/utils/katex_assets'),
      (os.path.join(SPECPATH, '..', 'node_modules', 'katex'), 'node_modules/katex'),
],
    hiddenimports=['passlib.handlers.bcrypt', 'bcrypt', 'cv2', 'numpy', 'weasyprint', 'matplotlib', 'pyzbar'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='omr_backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
