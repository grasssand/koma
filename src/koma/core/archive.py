import logging
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Literal

from koma.config import ExtensionsConfig

logger = logging.getLogger(__name__)

type CompressionLevel = Literal["normal", "store"]


class ArchiveHandler:
    def __init__(self, config: ExtensionsConfig):
        self.config = config
        self.seven_zip = self._find_7z()

        if not self.seven_zip:
            logger.warning(
                "未找到 7-Zip，将使用 Python 原生库 (仅支持 zip/cbz，不支持 .7z/.cb7 且打包速度较慢)"
            )

    def _find_7z(self) -> str | None:
        if path_in_env := shutil.which("7z"):
            return path_in_env
        try:
            if getattr(sys, "frozen", False):
                base_path = Path(sys._MEIPASS) / "koma"  # type: ignore
            else:
                base_path = Path(__file__).parent.parent
            local_7z = base_path / "resources" / "7z" / "7z.exe"
            if local_7z.exists():
                return str(local_7z)
        except Exception:
            pass
        return None

    def _get_creation_flags(self):
        return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    def _resolve_level(self, level: CompressionLevel = "normal") -> int:
        """
        解析压缩等级，根据当前使用的引擎返回对应的整数参数
        """
        is_store = level == "store"

        # 如果使用 7-Zip (0=Store, 5=Normal)
        if self.seven_zip:
            return 0 if is_store else 5

        # 如果使用 Python zipfile
        return zipfile.ZIP_STORED if is_store else zipfile.ZIP_DEFLATED

    def extract(self, archive_path: Path, output_root: Path) -> Path:
        """解压归档文件，返回内容根目录"""
        container_dir = output_root / archive_path.stem
        container_dir.mkdir(parents=True, exist_ok=True)

        success = False
        try:
            if self.seven_zip:
                success = self._extract_7z(archive_path, container_dir)
            elif archive_path.suffix.lower() in [".zip", ".cbz"]:
                success = self._extract_zipfile(archive_path, container_dir)
            else:
                logger.error(f"无法处理格式 {archive_path.suffix} (未找到 7-Zip)")
        except Exception as e:
            logger.error(f"解压异常 {archive_path.name}: {e}")

        if not success:
            raise RuntimeError(f"解压失败: {archive_path.name}")

        # 智能去嵌套：如果解压后只有一个文件夹，则返回该文件夹
        items = [
            x
            for x in container_dir.iterdir()
            if x.name.lower() not in self.config.system_junk
        ]
        if len(items) == 1 and items[0].is_dir():
            return items[0]

        return container_dir

    def pack(
        self,
        source_dir: Path,
        output_path: Path,
        fmt: str = "zip",
        level: CompressionLevel = "normal",
    ) -> bool:
        """
        打包目录
        Args:
            fmt: zip, cbz, 7z, cb7
            level: "store" (仅存储) 或 "normal" (标准压缩)
        """
        # 格式映射
        if fmt == "cbz":
            real_fmt = "zip"
        elif fmt == "cb7":
            real_fmt = "7z"
        else:
            real_fmt = fmt

        # 解析压缩等级参数
        compression_arg = self._resolve_level(level)

        # 执行打包
        if self.seven_zip:
            return self._pack_7z(source_dir, output_path, real_fmt, compression_arg)

        if real_fmt == "7z":
            logger.error("未找到 7-Zip，无法创建 .7z/.cb7 格式归档")
            return False

        logger.info(f"使用 Python 原生打包: {output_path.name} (Level: {level})")
        return self._pack_zipfile(source_dir, output_path, compression_arg)

    def _extract_7z(self, archive_path: Path, output_dir: Path) -> bool:
        cmd = [self.seven_zip, "x", str(archive_path), f"-o{output_dir}", "-y", "-aoa"]
        return self._run_subprocess(cmd)

    def _extract_zipfile(self, archive_path: Path, output_dir: Path) -> bool:
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(output_dir)
            return True
        except Exception as e:
            logger.error(f"Zipfile error: {e}")
            return False

    def _pack_7z(
        self, source_dir: Path, output_path: Path, fmt: str, mx_level: int
    ) -> bool:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        exclude_args = [f"-xr!{name}" for name in self.config.system_junk]

        cmd = [
            self.seven_zip,
            "a",
            str(output_path),
            ".",
            f"-t{fmt}",
            f"-mx={mx_level}",
            "-mmt=on",
            "-bsp0",
            "-bso0",
            *exclude_args,
        ]
        return self._run_subprocess(cmd, cwd=str(source_dir))

    def _pack_zipfile(
        self, source_dir: Path, output_path: Path, zip_method: int
    ) -> bool:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(output_path, "w", zip_method) as zf:
                for root, _, files in os.walk(source_dir):
                    for file in files:
                        if file.lower() in self.config.system_junk:
                            continue
                        file_path = Path(root) / file
                        arcname = file_path.relative_to(source_dir)
                        zf.write(file_path, arcname)
            return True
        except Exception as e:
            logger.error(f"Zip pack error: {e}")
            return False

    def _run_subprocess(self, cmd, cwd=None) -> bool:
        try:
            subprocess.run(
                cmd,
                cwd=cwd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=self._get_creation_flags(),
            )
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {e.stderr.decode(errors='ignore')}")
            return False
