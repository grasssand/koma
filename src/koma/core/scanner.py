import logging
import shutil
import tempfile
import uuid
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from natsort import natsorted
from PIL import Image

from koma.config import ExtensionsConfig
from koma.core.archive import ArchiveHandler
from koma.core.file_safety import move_no_replace
from koma.core.image_processor import ImageProcessor

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    to_convert: list[Path] = field(default_factory=list)
    to_copy: list[Path] = field(default_factory=list)
    ads: list[Path] = field(default_factory=list)
    junk: list[Path] = field(default_factory=list)
    archives: list[Path] = field(default_factory=list)
    processed_archives: int = 0
    failed_archives: int = 0


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
        enable_custom_ad_scan = options.get("enable_custom_ad_scan", False)
        custom_ad_dir = options.get("custom_ad_dir")
        enable_archive_scan = options.get("enable_archive_scan", False)
        out_dir_str = options.get("archive_out_path")
        exclude_path = Path(out_dir_str).resolve() if out_dir_str else None
        if enable_archive_scan and exclude_path:
            source = self.input_dir.resolve()
            if source == exclude_path or source.is_relative_to(exclude_path):
                raise ValueError("压缩包输出目录不能是输入目录或其上级目录")

        if enable_ad_scan and enable_custom_ad_scan:
            self.custom_ad_hashes = self._load_custom_ads(custom_ad_dir)
        else:
            self.custom_ad_hashes = []

        try:
            for root, dirs, files in self.input_dir.walk():
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

                root_path = Path(root)
                result = ScanResult()

                # 排除隐藏文件夹
                keep_dirs = []
                for d in dirs:
                    if d.startswith("."):
                        continue
                    if d.lower() in self.ext_config.system_junk:
                        junk_dir = root_path / d
                        logger.info(f"⚠️ 发现系统垃圾目录: {junk_dir}")
                        result.junk.append(junk_dir)
                        continue
                    keep_dirs.append(d)
                dirs[:] = keep_dirs

                files = natsorted(files)

                image_candidates = []

                for f in files:
                    f_path = root_path / f

                    # 压缩包扫描
                    if self._is_archive(f_path):
                        result.archives.append(f_path)

                        if enable_archive_scan:
                            outcome = self._process_archive(f_path, options)
                            if outcome is True:
                                result.processed_archives += 1
                            elif outcome is None:
                                result.failed_archives += 1

                        continue

                    # 常规文件扫描
                    is_junk_file = self._is_junk(f_path)

                    if is_junk_file:
                        logger.info(f"⚠️ 发现杂项文件: {f_path}")
                        result.junk.append(f_path)
                        continue

                    if f_path.suffix.lower() in self.supported_img:
                        image_candidates.append(f)

                # 广告检测
                confirmed_ads = set()
                if image_candidates and enable_ad_scan:
                    confirmed_ads = self._detect_ads_in_folder(
                        root_path, image_candidates, enable_custom_ad_scan
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
                    or result.archives
                    or result.processed_archives > 0
                ):
                    yield root_path, result

        finally:
            if progress_callback:
                progress_callback(1, 1, "扫描分析完成")

    def _process_archive(self, archive_path: Path, options: dict) -> bool | None:
        """返回 True（成功）、False（无需清理）或 None（失败）。"""
        output_dir = options.get("archive_out_path")
        if not output_dir:
            return None

        try:
            required_space = archive_path.stat().st_size * 2.5
            temp_base = Path(tempfile.gettempdir())
            free_space = shutil.disk_usage(temp_base).free

            if free_space < required_space:
                logger.error(
                    f"❌ 跳过压缩包 {archive_path.name}: 磁盘空间不足 "
                    f"(需要 {required_space / 1024 / 1024:.1f}MB, 剩余 {free_space / 1024 / 1024:.1f}MB)"
                )
                return None
        except Exception:
            pass

        try:
            with tempfile.TemporaryDirectory(prefix="koma_extract_") as temp_dir:
                temp_root = Path(temp_dir)

                # 解压
                content_root = self.archive_handler.extract(archive_path, temp_root)

                # 清理
                deleted_count = self._clean_directory_recursive(
                    content_root,
                    options.get("enable_ad_scan", False),
                    options.get("enable_custom_ad_scan", False),
                )
                if deleted_count == 0:
                    logger.info(f"⏩ 跳过干净压缩包: {archive_path.name}")
                    return False

                logger.info(f"🚫 发现杂项或广告: {archive_path.name}")

                # 按输入相对目录输出，同名结果只创建新名字，不合并旧目录。
                relative_parent = archive_path.parent.resolve().relative_to(
                    self.input_dir.resolve()
                )
                dest_parent = Path(output_dir).resolve() / relative_parent
                dest_parent.mkdir(parents=True, exist_ok=True)
                if options.get("repack", True):
                    fmt = options.get("pack_format", "zip")
                    if fmt not in {"zip", "cbz", "7z", "cb7"}:
                        raise ValueError("不支持的压缩包输出格式")
                    name = f"{archive_path.stem}.{fmt}"
                else:
                    name = archive_path.stem

                with tempfile.TemporaryDirectory(
                    prefix=".koma-", dir=dest_parent
                ) as staging_dir:
                    staged = Path(staging_dir) / name
                    if options.get("repack", True):
                        if not self.archive_handler.pack(
                            content_root, staged, fmt=fmt, level="normal"
                        ):
                            raise RuntimeError("压缩包重打包失败")
                        if not staged.is_file() or staged.stat().st_size == 0:
                            raise RuntimeError("压缩包输出为空")
                    else:
                        shutil.copytree(content_root, staged)

                    final_path = dest_parent / name
                    while True:
                        try:
                            if options.get("repack", True):
                                move_no_replace(staged, final_path)
                            else:
                                if final_path.exists() or final_path.is_symlink():
                                    raise FileExistsError(str(final_path))
                                staged.rename(final_path)
                            break
                        except FileExistsError:
                            suffix = f"_{uuid.uuid4().hex}"
                            final_path = dest_parent / (
                                f"{archive_path.stem}{suffix}.{fmt}"
                                if options.get("repack", True)
                                else f"{archive_path.stem}{suffix}"
                            )
                logger.info(
                    f"✅ 已清理 {deleted_count} 个文件: {archive_path.name} -> {final_path}"
                )

                return True

        except OSError as e:
            if e.errno == 28:
                logger.critical(f"⛔ 处理 {archive_path.name} 时磁盘空间耗尽！")
            else:
                logger.error(f"处理压缩包IO错误 {archive_path}: {e}")
            return None

        except Exception as e:
            logger.error(f"处理压缩包失败 {archive_path}: {e}")
            return None

    def _clean_directory_recursive(
        self, target_dir: Path, enable_ad_scan: bool, enable_custom_ad_scan: bool
    ) -> int:
        """递归清理临时目录中的垃圾和广告"""
        deleted_count = 0

        def fail_walk(error: OSError) -> None:
            raise error

        for root, dirs, files in target_dir.walk(on_error=fail_walk):
            root_path = Path(root)
            files = natsorted(files)
            for name in list(dirs):
                if name.lower() in self.ext_config.system_junk:
                    shutil.rmtree(root_path / name)
                    dirs.remove(name)
                    deleted_count += 1

            image_candidates = []

            # 删杂项
            for f in files:
                f_path = root_path / f
                if self._is_junk(f_path):
                    f_path.unlink()
                    deleted_count += 1
                    logger.debug(f"[TempClean] 删除杂项: {f}")
                elif f_path.suffix.lower() in self.supported_img:
                    image_candidates.append(f)

            # 删广告
            if enable_ad_scan and image_candidates:
                ads = self._detect_ads_in_folder(
                    root_path, image_candidates, enable_custom_ad_scan
                )
                for ad in ads:
                    (root_path / ad).unlink()
                    deleted_count += 1
                    logger.debug(f"[TempClean] 删除广告: {ad}")

        return deleted_count

    def _is_junk(self, path: Path) -> bool:
        """判断是否为杂项文件"""
        name = path.name

        # 隐藏文件
        if name.startswith("."):
            return True

        # 系统垃圾文件：显式配置优先，即使扩展名在支持列表里也一律视为垃圾
        if name.lower() in self.ext_config.system_junk:
            return True

        # 白名单文件
        if name.lower() in self.ext_config.misc_whitelist:
            return False

        return path.suffix.lower() not in self.valid_extensions

    def _is_archive(self, path: Path) -> bool:
        return path.suffix.lower() in self.ext_config.archive

    def _detect_ads_in_folder(
        self, root: Path, images: list[str], enable_custom_ad_scan: bool = False
    ) -> set[str]:
        """检测结尾二维码和自定义广告图"""
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

        # 检测首2尾3自定义图
        if enable_custom_ad_scan and self.custom_ad_hashes:
            # 排除掉已经被刚才判定为二维码的图片
            remaining = [img for img in images if img not in confirmed]
            first_2 = remaining[:2]
            last_3 = remaining[-3:] if len(remaining) >= 3 else remaining
            candidates_to_check = list(dict.fromkeys(first_2 + last_3))

            for img_name in candidates_to_check:
                img_path = root / img_name
                img_data = self._calc_dhash(img_path)

                if img_data is not None:
                    img_hash, img_brightness = img_data
                    for ad_hash, ad_brightness in self.custom_ad_hashes:
                        distance = bin(img_hash ^ ad_hash).count("1")

                        if distance <= 5 and abs(img_brightness - ad_brightness) <= 30:
                            logger.info(f"🚫 发现自定义广告: {img_path}")
                            confirmed.add(img_name)
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

    def _calc_dhash(self, img_path: Path) -> tuple[int, float] | None:
        """计算差异哈希和平均亮度"""
        try:
            with Image.open(img_path) as img:
                img = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
                pixels = list(img.tobytes())
                mean_brightness = sum(pixels) / len(pixels)

                diff = []
                for row in range(8):
                    for col in range(8):
                        idx = row * 9 + col
                        diff.append(1 if pixels[idx] > pixels[idx + 1] else 0)

                hash_val = sum(v << i for i, v in enumerate(diff))

                return hash_val, mean_brightness
        except Exception as e:
            logger.debug(f"哈希计算失败 {img_path.name}: {e}")
            return None

    def _load_custom_ads(self, custom_ad_dir: str | None) -> list[tuple[int, float]]:
        """计算自定义广告的特征库"""
        ad_hashes = []
        if not custom_ad_dir:
            return ad_hashes

        path = Path(custom_ad_dir)
        if not path.exists() or not path.is_dir():
            path.mkdir(parents=True, exist_ok=True)
            return ad_hashes

        for f in path.iterdir():
            if f.is_file() and f.suffix.lower() in self.supported_img:
                h = self._calc_dhash(f)
                if h is not None:
                    ad_hashes.append(h)

        return ad_hashes
