import os
import shutil

import tkinterdnd2

BUILD_WITH_FFMPEG = os.environ.get("BUILD_WITH_FFMPEG", "false").lower() == "true"

block_cipher = None

tkdnd_path = os.path.join(os.path.dirname(tkinterdnd2.__file__), "tkdnd")
datas = [
    ("src/koma/resources", "koma/resources"),
]
binaries = [
    (str(tkdnd_path), "tkinterdnd2/tkdnd"),
]

project_7z_exe = "src/koma/resources/7z/7z.exe"
project_7z_dll = "src/koma/resources/7z/7z.dll"
if os.path.exists(project_7z_exe) and os.path.exists(project_7z_dll):
    print("Found 7-Zip in project resources.")
    binaries.append((project_7z_exe, "koma/resources/7z"))
    binaries.append((project_7z_dll, "koma/resources/7z"))
else:
    sys_7z_exe = shutil.which("7z")

    if not sys_7z_exe and os.name == "nt":
        default_sys_path = r"C:\Program Files\7-Zip\7z.exe"
        if os.path.exists(default_sys_path):
            sys_7z_exe = default_sys_path

    if sys_7z_exe:
        print(f"Found 7-Zip on system: {sys_7z_exe}")
        sys_7z_dir = os.path.dirname(sys_7z_exe)
        binaries.append((sys_7z_exe, "koma/resources/7z"))

        sys_7z_dll = os.path.join(sys_7z_dir, "7z.dll")
        if os.path.exists(sys_7z_dll):
            binaries.append((sys_7z_dll, "koma/resources/7z"))
    else:
        print("WARNING: 7-Zip binaries not found! It will not be bundled.")

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
    hiddenimports=[],
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
