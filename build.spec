import os
import shutil

BUILD_WITH_FFMPEG = os.environ.get("BUILD_WITH_FFMPEG", "false").lower() == "true"

block_cipher = None

datas = [
    ("src/koma/resources", "koma/resources"),
]
binaries = [
    ("src/koma/resources/7z/7z.exe", "koma/resources/7z"),
    ("src/koma/resources/7z/7z.dll", "koma/resources/7z"),
]
if BUILD_WITH_FFMPEG:
    ffmpeg_path = shutil.which("ffmpeg") or "ffmpeg.exe"
    if os.path.exists(ffmpeg_path):
        print(f"Found FFmpeg for bundling: {ffmpeg_path}")
        binaries.append((ffmpeg_path, "koma/resources/ffmpeg"))
    else:
        print("WARNING: BUILD_WITH_FFMPEG is True but ffmpeg not found!")

a = Analysis(
    ["src/koma/main.py"],
    pathex=[],
    binaries=binaries,
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
    icon="src/koma/resources/koma.ico",
)
