import io
import logging
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Literal

from natsort import natsorted
from PIL import Image

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
        """每次在独占工作区解压，保留归档和内层目录的逻辑名称。"""
        if any(self._is_link(p) for p in (output_root, *output_root.parents)):
            raise RuntimeError("解压工作区不能是链接目录")
        output_root.mkdir(parents=True, exist_ok=True)
        workspace = Path(tempfile.mkdtemp(prefix="koma_extract_", dir=output_root))
        container_dir = workspace / archive_path.stem
        try:
            if archive_path.stem in {"", ".", ".."}:
                raise ValueError("无效的归档名称")
            container_dir.mkdir()
            if archive_path.suffix.lower() in {".zip", ".cbz"}:
                success = self._extract_zipfile(archive_path, container_dir)
            elif self.seven_zip:
                success = self._extract_7z(archive_path, container_dir)
            else:
                success = False
            if not success:
                raise RuntimeError(f"解压失败: {archive_path.name}")
            # 不跟随链接，也不允许提取结果逃离独占工作区。
            for _ in self._iter_files(container_dir):
                pass
            items = [
                x
                for x in container_dir.iterdir()
                if x.name.lower() not in self.config.system_junk
            ]
            if len(items) == 1 and not self._is_link(items[0]) and items[0].is_dir():
                return items[0]
            return container_dir
        except Exception as e:
            shutil.rmtree(workspace)
            raise RuntimeError(f"解压失败: {archive_path.name}: {e}") from e

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

    def extract_cover(self, archive_path: Path) -> Image.Image | None:
        """从归档文件中提取封面"""
        if archive_path.suffix.lower() in [".zip", ".cbz"]:
            try:
                with zipfile.ZipFile(archive_path, "r") as zf:
                    images = natsorted(
                        [
                            name
                            for name in zf.namelist()
                            if not name.endswith("/")
                            and Path(name).suffix.lower()
                            in self.config.all_supported_img
                        ]
                    )
                    if images:
                        with zf.open(images[0]) as f:
                            return Image.open(f).copy()
            except Exception as e:
                logger.debug(f"原生 zipfile 提取封面失败 {archive_path.name}: {e}")

        if not self.seven_zip:
            return None

        try:
            list_cmd = [self.seven_zip, "l", "-slt", str(archive_path)]
            list_res = subprocess.run(
                list_cmd,
                capture_output=True,
                text=True,
                errors="ignore",
                creationflags=self._get_creation_flags(),
            )

            if list_res.returncode != 0:
                return None

            paths = []
            for line in list_res.stdout.splitlines():
                if line.startswith("Path = "):
                    paths.append(line.split(" = ", 1)[1])

            images = natsorted(
                [
                    n
                    for n in paths
                    if Path(n).suffix.lower() in self.config.all_supported_img
                ]
            )

            if not images:
                return None

            target_file = images[0]

            ext_cmd = [self.seven_zip, "e", str(archive_path), target_file, "-so"]
            ext_res = subprocess.run(
                ext_cmd, capture_output=True, creationflags=self._get_creation_flags()
            )

            if ext_res.returncode == 0 and ext_res.stdout:
                return Image.open(io.BytesIO(ext_res.stdout)).copy()

        except Exception as e:
            logger.debug(f"7-Zip 提取封面失败 {archive_path.name}: {e}")

        return None

    def _extract_7z(self, archive_path: Path, output_dir: Path) -> bool:
        # 先检查目录清单；拒绝链接条目，避免提取时通过链接写出工作区。
        result = subprocess.run(
            [
                self.seven_zip,
                "l",
                "-slt",
                "-ba",
                "-sccUTF-8",
                str(archive_path.resolve()),
            ],
            check=True,
            capture_output=True,
            creationflags=self._get_creation_flags(),
        )
        listing = result.stdout.decode("utf-8", errors="strict").replace("\r\n", "\n")
        for block in listing.split("\n\n"):
            fields = dict(
                line.split(" = ", 1) for line in block.splitlines() if " = " in line
            )
            name = fields.get("Path")
            if name is None:
                continue
            if (
                not self._is_safe_member(output_dir.resolve(), name.replace("\\", "/"))
                or "Symbolic Link" in fields
                or "Hard Link" in fields
                or "Reparse Point" in fields
                or "l" in fields.get("Attributes", "")
                or "L" in fields.get("Attributes", "")
                or fields.get("Mode", "").startswith("l")
            ):
                raise ValueError("压缩包含越界路径或链接")
        cmd = [
            self.seven_zip,
            "x",
            str(archive_path.resolve()),
            f"-o{output_dir.resolve()}",
            "-y",
            "-aoa",
        ]
        return self._run_subprocess(cmd)

    @staticmethod
    def _is_safe_member(base: Path, name: str) -> bool:
        """
        校验压缩包成员名不会写到解压目录之外（zip-slip）。

        zip 成员名一律用 "/" 分隔，因此按 POSIX 语义解析：
        拒绝绝对路径、上跳的 ".."、以及带盘符的写法（Windows 上
        `base / "C:/x"` 会直接跳出 base）。
        """
        if "\\" in name or "\x00" in name or ":" in name:
            return False
        member = PurePosixPath(name)

        if member.is_absolute() or ".." in member.parts:
            return False
        if ":" in name.split("/")[0]:
            return False

        try:
            target = (base / Path(*member.parts)).resolve()
        except (OSError, ValueError):
            return False

        return target == base or base in target.parents

    def _extract_zipfile(self, archive_path: Path, output_dir: Path) -> bool:
        try:
            base = output_dir.resolve()
            with zipfile.ZipFile(archive_path, "r") as zf:
                unsafe = [
                    info.filename
                    for info in zf.infolist()
                    if not self._is_safe_member(base, info.filename)
                    or stat.S_ISLNK(info.external_attr >> 16)
                ]
                if unsafe:
                    logger.error(
                        f"⛔ 压缩包 {archive_path.name} 含越界路径，已拒绝解压: "
                        f"{unsafe[:3]}"
                    )
                    return False
                zf.extractall(base)
            return True
        except Exception as e:
            logger.error(f"Zipfile error: {e}")
            return False

    def _pack_7z(
        self, source_dir: Path, output_path: Path, fmt: str, mx_level: int
    ) -> bool:
        output_path = output_path.resolve()
        try:
            for _ in self._iter_files(source_dir):
                pass
        except OSError as e:
            logger.error(f"无法完整读取打包目录: {e}")
            return False
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
                for file_path in self._iter_files(source_dir):
                    if any(
                        part.lower() in self.config.system_junk
                        for part in file_path.relative_to(source_dir).parts
                    ):
                        continue
                    zf.write(file_path, file_path.relative_to(source_dir))
            return True
        except Exception as e:
            logger.error(f"Zip pack error: {e}")
            return False

    @staticmethod
    def _is_link(path: Path) -> bool:
        return path.is_symlink() or path.is_junction()

    def _iter_files(self, source_dir: Path) -> Iterator[Path]:
        """完整遍历目录；读取失败或遇到链接时终止，不能静默打出残缺归档。"""

        def fail(error: OSError) -> None:
            raise error

        if self._is_link(source_dir):
            raise OSError(f"不允许链接目录: {source_dir}")
        base = source_dir.resolve(strict=True)
        for root, dirs, files in source_dir.walk(on_error=fail):
            for name in dirs + files:
                entry = root / name
                if self._is_link(entry) or not entry.resolve().is_relative_to(base):
                    raise OSError(f"目录含链接或越界路径: {entry}")
            for name in files:
                yield root / name

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
