import logging
import os
import shutil
import tempfile
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from natsort import natsorted

from koma.config import ExtensionsConfig
from koma.core.archive import ArchiveHandler
from koma.core.image_processor import ImageProcessor

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    to_convert: list[Path] = field(default_factory=list)
    to_copy: list[Path] = field(default_factory=list)
    ads: list[Path] = field(default_factory=list)
    junk: list[Path] = field(default_factory=list)
    processed_archives: int = 0


class Scanner:
    def __init__(
        self,
        input_dir: Path,
        ext_config: ExtensionsConfig,
        image_processor: ImageProcessor,
    ):
        """
        初始化扫描器

        Args:
            input_dir: 扫描根目录
            ext_config: 扩展名配置
            image_processor: 图像处理器
        """
        self.input_dir = Path(input_dir)
        self.ext_config = ext_config
        self.image_processor = image_processor
        self.archive_handler = ArchiveHandler(self.ext_config)

        self.supported_img = self.ext_config.all_supported_img
        self.valid_extensions = (
            self.supported_img | self.ext_config.archive | self.ext_config.document
        )

    def run(
        self,
        options: dict[str, Any] | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> Generator[tuple[Path, ScanResult], None, None]:
        options = options or {}
        enable_ad_scan = options.get("enable_ad_scan", False)
        enable_archive_scan = options.get("enable_archive_scan", False)
        out_dir_str = options.get("archive_out_path")
        exclude_path = Path(out_dir_str).resolve() if out_dir_str else None

        try:
            for root, dirs, files in os.walk(self.input_dir):
                root_path = Path(root).resolve()
                if exclude_path:
                    try:
                        if root_path == exclude_path or root_path.is_relative_to(
                            exclude_path
                        ):
                            dirs[:] = []
                            continue
                    except ValueError:
                        pass

                # 排除隐藏文件夹
                dirs[:] = [d for d in dirs if not d.startswith(".")]

                root_path = Path(root)
                result = ScanResult()
                files = natsorted(files)

                image_candidates = []

                for f in files:
                    f_path = root_path / f

                    # 压缩包扫描
                    if enable_archive_scan and self._is_archive(f_path):
                        if self._process_archive(f_path, options):
                            result.processed_archives += 1
                        continue

                    # 常规文件扫描
                    is_junk_file = self._is_junk(f_path)

                    if is_junk_file:
                        result.junk.append(f_path)
                        continue

                    if f_path.suffix.lower() in self.supported_img:
                        image_candidates.append(f)

                # 广告检测
                confirmed_ads = set()
                if image_candidates and enable_ad_scan:
                    confirmed_ads = self._detect_ads_in_folder(
                        root_path, image_candidates
                    )

                # 结果归类
                self._categorize_files(
                    root_path, image_candidates, confirmed_ads, result
                )

                if (
                    result.to_convert
                    or result.to_copy
                    or result.ads
                    or result.junk
                    or result.processed_archives > 0
                ):
                    yield root_path, result

        finally:
            if progress_callback:
                progress_callback(1, 1, "扫描分析完成")

    def _process_archive(self, archive_path: Path, options: dict) -> bool:
        """处理单个压缩包：检查空间 -> 解压 -> 清理 -> 重打包"""
        output_dir = options.get("archive_out_path")
        if not output_dir:
            return False

        try:
            required_space = archive_path.stat().st_size * 2.5
            temp_base = Path(tempfile.gettempdir())
            free_space = shutil.disk_usage(temp_base).free

            if free_space < required_space:
                logger.error(
                    f"❌ 跳过压缩包 {archive_path.name}: 磁盘空间不足 "
                    f"(需要 {required_space / 1024 / 1024:.1f}MB, 剩余 {free_space / 1024 / 1024:.1f}MB)"
                )
                return False
        except Exception:
            pass

        try:
            with tempfile.TemporaryDirectory(prefix="koma_extract_") as temp_dir:
                temp_root = Path(temp_dir)

                # 解压
                content_root = self.archive_handler.extract(archive_path, temp_root)

                # 清理
                deleted_count = self._clean_directory_recursive(
                    content_root, check_ads=options.get("enable_ad_scan", False)
                )
                if deleted_count == 0:
                    logger.info(f"⏩ 跳过干净压缩包: {archive_path.name}")
                    return False

                logger.info(f"🚫 发现杂项或广告: {archive_path.name}")

                # 重打包 或 复制
                dest_base = Path(output_dir) / archive_path.stem

                if options.get("repack", True):
                    fmt = options.get("pack_format", "zip")
                    final_path = dest_base.with_suffix(f".{fmt}")

                    self.archive_handler.pack(
                        content_root, final_path, fmt=fmt, level="normal"
                    )
                    logger.info(
                        f"📦 已重打包 (清理 {deleted_count} 个文件): {archive_path.name} -> {final_path}"
                    )
                else:
                    if not dest_base.exists():
                        shutil.move(str(content_root), str(dest_base))
                        logger.info(
                            f"✅ 已移动 (清理 {deleted_count} 个文件): {archive_path.name} -> {dest_base}"
                        )
                    else:
                        shutil.copytree(content_root, dest_base, dirs_exist_ok=True)
                        logger.info(
                            f"✅ 已合并 (清理 {deleted_count} 个文件): {archive_path.name} -> {dest_base}"
                        )

                return True

        except OSError as e:
            if e.errno == 28:
                logger.critical(f"⛔ 处理 {archive_path.name} 时磁盘空间耗尽！")
            else:
                logger.error(f"处理压缩包IO错误 {archive_path}: {e}")
            return False

        except Exception as e:
            logger.error(f"处理压缩包失败 {archive_path}: {e}")
            return False

    def _clean_directory_recursive(self, target_dir: Path, check_ads: bool) -> int:
        """递归清理临时目录中的垃圾和广告"""
        deleted_count = 0

        for root, _, files in os.walk(target_dir):
            root_path = Path(root)
            files = natsorted(files)

            image_candidates = []

            # 删杂项
            for f in files:
                f_path = root_path / f
                if self._is_junk(f_path):
                    try:
                        os.remove(f_path)
                        deleted_count += 1
                        logger.debug(f"[TempClean] 删除杂项: {f}")
                    except OSError:
                        pass
                elif f_path.suffix.lower() in self.supported_img:
                    image_candidates.append(f)

            # 删广告
            if check_ads and image_candidates:
                ads = self._detect_ads_in_folder(root_path, image_candidates)
                for ad in ads:
                    try:
                        os.remove(root_path / ad)
                        deleted_count += 1
                        logger.debug(f"[TempClean] 删除广告: {ad}")
                    except OSError:
                        pass

        return deleted_count

    def _is_junk(self, path: Path) -> bool:
        """判断是否为杂项文件"""
        name = path.name
        suffix = path.suffix.lower()

        # 隐藏文件
        if name.startswith("."):
            return True

        # 白名单文件
        if name.lower() in self.ext_config.misc_whitelist:
            return False

        return suffix not in self.valid_extensions

    def _is_archive(self, path: Path) -> bool:
        return path.suffix.lower() in self.ext_config.archive

    def _detect_ads_in_folder(self, root: Path, images: list[str]) -> set[str]:
        """倒序检测文件夹内的广告图片"""
        confirmed = set()

        # 倒序检查最后几张图
        for i in range(len(images) - 1, -1, -1):
            img_name = images[i]
            img_path = root / img_name
            try:
                info = self.image_processor.analyze(img_path)
            except Exception:
                continue

            # 如果是正常漫画页（非动图、非灰度等），停止检测
            # 简单启发式：如果不是二维码广告且内容看起来正常，就认为到底了
            if info.is_animated:
                break

            if self.image_processor.has_ad_qrcode(img_path):
                confirmed.add(img_name)
            else:
                # 遇到第一张非广告图，停止倒序扫描
                break

        return confirmed

    def _categorize_files(
        self, root: Path, images: list[str], ads: set[str], result: ScanResult
    ):
        for f_name in images:
            file_path = root / f_name
            suffix = file_path.suffix.lower()

            if f_name in ads:
                result.ads.append(file_path)
            elif suffix in self.ext_config.convert:
                result.to_convert.append(file_path)
            elif suffix in self.ext_config.passthrough:
                result.to_copy.append(file_path)
