import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Literal

from koma.config import SYSTEM_JUNK_FILES
from koma.utils import logger


class ArchiveHandler:
    def __init__(self):
        self.seven_zip = shutil.which("7z")
        if not self.seven_zip:
            local_7z = Path(__file__).parent.parent / "resources" / "7z.exe"
            if local_7z.exists():
                self.seven_zip = str(local_7z)

        if not self.seven_zip:
            logger.warning(
                "未找到 7-Zip，将使用 Python 原生库 (仅支持 zip/cbz，不支持 .7z 且速度较慢)"
            )

    def _get_creation_flags(self):
        """Windows 下隐藏 subprocess 黑框"""
        if os.name == "nt":
            return subprocess.CREATE_NO_WINDOW
        return 0

    def _extract_7z(self, archive_path: Path, output_dir: Path) -> bool:
        """7z 解压"""
        try:
            cmd = [
                self.seven_zip,
                "x",
                str(archive_path),
                f"-o{str(output_dir)}",
                "-y",
                "-aoa",
            ]
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=self._get_creation_flags(),
            )
            return True
        except Exception as e:
            logger.error(f"7-Zip 解压失败: {e}")
            return False

    def _extract_zipfile(self, archive_path: Path, output_dir: Path) -> bool:
        """Python 原生解压"""
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(output_dir)
            return True
        except Exception as e:
            logger.error(f"Zipfile 解压失败: {e}")
            return False

    def _pack_7z(
        self, source_dir: Path, output_path: Path, fmt: str, level: int
    ) -> bool:
        """7z 压缩"""
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)

            exclude_args = [f"-xr!{name}" for name in SYSTEM_JUNK_FILES]

            cmd = [
                self.seven_zip,
                "a",  # 添加文件
                str(output_path),
                ".",  # 添加当前目录下的所有内容 (配合 cwd 使用)
                f"-t{fmt}",  # 格式: -tzip, -t7z
                f"-mx={level}",  # 压缩等级: -mx=0 ~ -mx=9
                "-mmt=on",  # 开启多线程
                "-bsp0",  # 禁用进度输出
                "-bso0",  # 禁用标准输出
            ] + exclude_args

            subprocess.run(
                cmd,
                cwd=str(source_dir),
                check=True,
                creationflags=self._get_creation_flags(),
            )
            return True
        except Exception as e:
            logger.error(f"7-Zip 打包失败: {e}")
            return False

    def _pack_zipfile(self, source_dir: Path, output_path: Path, level: int) -> bool:
        """Python 原生打包"""
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            compression = zipfile.ZIP_STORED if level == 0 else zipfile.ZIP_DEFLATED

            with zipfile.ZipFile(output_path, "w", compression) as zf:
                for root, _, files in os.walk(source_dir):
                    for file in files:
                        if file.lower() in SYSTEM_JUNK_FILES:
                            continue

                        file_path = Path(root) / file
                        arcname = file_path.relative_to(source_dir)
                        zf.write(file_path, arcname)
            return True
        except Exception as e:
            logger.error(f"Zipfile 打包失败: {e}")
            return False

    def extract(self, archive_path: Path, temp_root: Path) -> Path:
        """智能解压逻辑"""
        container_dir = temp_root / archive_path.stem
        container_dir.mkdir(parents=True, exist_ok=True)

        success = False
        if self.seven_zip:
            success = self._extract_7z(archive_path, container_dir)
        elif archive_path.suffix.lower() in [".zip", ".cbz"]:
            success = self._extract_zipfile(archive_path, container_dir)
        else:
            logger.error(f"无法处理格式 {archive_path.suffix} (未找到 7-Zip)")
            raise RuntimeError(f"缺少解压工具: {archive_path.name}")

        if not success:
            raise RuntimeError(f"解压过程出错: {archive_path.name}")

        # 智能判断文件夹封装
        items = [
            x
            for x in container_dir.iterdir()
            if x.name.lower() not in SYSTEM_JUNK_FILES
        ]

        if len(items) == 1 and items[0].is_dir():
            return items[0]

        return container_dir

    def pack(
        self,
        source_dir: Path,
        output_path: Path,
        fmt: Literal["zip", "7z", "cbz"] = "cbz",
        level: int = 0,
    ) -> bool:
        """
        通用打包函数

        Args:
            source_dir: 要打包的文件夹路径
            output_path: 输出文件路径
            fmt: 格式 'zip', '7z', 'cbz' (默认 cbz)
            level: 压缩等级 0-9 (0=存储/无压缩, 5=标准, 9=极限)。
                   对于漫画图片，建议使用 0，因为图片已经是压缩格式，再次压缩只会浪费 CPU。
        """
        real_fmt = "zip" if fmt == "cbz" else fmt

        if self.seven_zip:
            return self._pack_7z(source_dir, output_path, real_fmt, level)

        if real_fmt == "7z":
            logger.error("未找到 7-Zip，无法创建 .7z 格式归档")
            return False

        logger.info("未找到 7-Zip，将使用 Python 原生打包")
        return self._pack_zipfile(source_dir, output_path, level)
