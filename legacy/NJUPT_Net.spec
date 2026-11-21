# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:/Users/50406/Documents/ChatGPT/chatgpt默认项目/NJUPT_NET/web2.3.py'],
    pathex=[],
    binaries=[],
    datas=[('C:/Users/50406/Documents/ChatGPT/chatgpt默认项目/NJUPT_NET/njupt.png', '.')],
    hiddenimports=[],
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
    name='NJUPT_Net',
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
    icon=['C:/Users/50406/Documents/ChatGPT/chatgpt默认项目/NJUPT_NET/njupt.ico'],
)
