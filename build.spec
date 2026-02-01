block_cipher = None

datas = [
    ("src/koma/resources", "koma/resources"),
]

a = Analysis(
    ["src/koma/main.py"],
    pathex=[],
    binaries=[
        ('src/koma/resources/7z/7z.exe', 'resources'),
        ('src/koma/resources/7z/7z.dll', 'resources')
    ],
    datas=datas,
    hiddenimports=["koma.utils.logger"],
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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Koma",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="koma.ico",
)
