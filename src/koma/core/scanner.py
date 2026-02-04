import logging
import os
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from pathlib import Path

from natsort import natsorted

from koma.config import ExtensionsConfig
from koma.core.image_processor import ImageProcessor

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    to_convert: list[Path] = field(default_factory=list)
    to_copy: list[Path] = field(default_factory=list)
    ads: list[Path] = field(default_factory=list)
    junk: list[Path] = field(default_factory=list)


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

    def run(
        self, progress_callback: Callable[[int, int, str], None] | None = None
    ) -> Generator[tuple[Path, ScanResult], None, None]:
        supported_img = self.ext_config.all_supported_img
        convert_exts = self.ext_config.convert
        passthrough_exts = self.ext_config.passthrough
        misc_whitelist = self.ext_config.misc_whitelist

        # 合法文件白名单：图片 | 归档 | 文档
        valid_extensions = (
            supported_img | self.ext_config.archive | self.ext_config.document
        )

        try:
            for root, dirs, files in os.walk(self.input_dir):
                # 排除隐藏文件夹
                dirs[:] = [d for d in dirs if not d.startswith(".")]

                root = Path(root)
                result = ScanResult()
                files = natsorted(files)

                image_candidates = []

                for f in files:
                    f_path = root / f
                    f_lower = f.lower()
                    suffix_lower = f_path.suffix.lower()

                    # 垃圾文件判定
                    if f.startswith(".") or (
                        f_lower not in misc_whitelist
                        and suffix_lower not in valid_extensions
                    ):
                        result.junk.append(f_path)
                        logger.info(f"❌ 发现杂项文件: {f_path}")
                        continue

                    # 图片收集
                    elif suffix_lower in supported_img:
                        image_candidates.append(f)

                # 广告检测
                confirmed_ads: set[str] = set()
                if image_candidates:
                    confirmed_ads = self._detect_ads(root, image_candidates)

                # 结果分类
                for f_name in image_candidates:
                    file_path = root / f_name
                    suffix_lower = file_path.suffix.lower()

                    if f_name in confirmed_ads:
                        result.ads.append(file_path)
                    elif suffix_lower in convert_exts:
                        result.to_convert.append(file_path)
                    elif suffix_lower in passthrough_exts:
                        result.to_copy.append(file_path)

                if result.to_convert or result.to_copy or result.ads or result.junk:
                    yield root, result

        finally:
            if progress_callback:
                progress_callback(1, 1, "扫描分析完成")

    def _detect_ads(self, root: Path, images: list[str]) -> set[str]:
        """倒序检测广告图片"""
        confirmed = set()

        for i in range(len(images) - 1, -1, -1):
            img_name = images[i]
            img_path = root / img_name

            info = self.image_processor.analyze(img_path)

            if info.is_animated or info.is_grayscale:
                break

            if self.image_processor.has_ad_qrcode(img_path):
                confirmed.add(img_name)
                continue
            else:
                break

        return confirmed
