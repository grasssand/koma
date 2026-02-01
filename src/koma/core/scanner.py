import os
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path

from natsort import natsorted

from koma.config import (
    ARCHIVE_EXTS,
    CONVERT_EXTS,
    DOCUMENT_EXTS,
    MISC_WHITELIST_FILES,
    PASSTHROUGH_EXTS,
    SUPPORTED_IMAGE_EXTS,
)
from koma.utils import AdDetector, logger
from koma.utils.image_analysis import analyze_image


@dataclass
class ScanResult:
    to_convert: list[Path] = field(default_factory=list)
    to_copy: list[Path] = field(default_factory=list)
    ads: list[Path] = field(default_factory=list)
    junk: list[Path] = field(default_factory=list)


class Scanner:
    def __init__(self, input_dir: Path, enable_ad_detection: bool = True):
        self.input_dir = Path(input_dir)
        self.enable_ad_detection = enable_ad_detection

    def run(self) -> Generator[tuple[Path, ScanResult], None, None]:
        for root, dirs, files in os.walk(self.input_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".")]

            root = Path(root)
            result = ScanResult()
            files = natsorted(files)

            image_candidates = []

            for f in files:
                f_path = root / f

                if f.startswith(".") or (
                    f.lower() not in MISC_WHITELIST_FILES
                    and f_path.suffix.lower()
                    not in (SUPPORTED_IMAGE_EXTS | ARCHIVE_EXTS | DOCUMENT_EXTS)
                ):
                    result.junk.append(f_path)
                    logger.info(f"❌ 发现杂项文件: {f_path}")
                    continue

                elif f_path.suffix.lower() in SUPPORTED_IMAGE_EXTS:
                    image_candidates.append(f)

            confirmed_ads = set()
            if self.enable_ad_detection and image_candidates:
                confirmed_ads = self._detect_ads(root, image_candidates)

            for f_name in image_candidates:
                file_path = root / f_name

                if f_name in confirmed_ads:
                    result.ads.append(file_path)
                elif file_path.suffix.lower() in CONVERT_EXTS:
                    result.to_convert.append(file_path)
                elif file_path.suffix.lower() in PASSTHROUGH_EXTS:
                    result.to_copy.append(file_path)

            if result.to_convert or result.to_copy or result.ads or result.junk:
                yield root, result

    def _detect_ads(self, root: Path, images: list[str]) -> set:
        """广告检测"""
        confirmed = set()

        for i in range(len(images) - 1, -1, -1):
            img_name = images[i]
            img_path = root / img_name

            is_anim, is_gray = analyze_image(img_path)

            if is_anim or is_gray:
                break

            if AdDetector.is_spam_qrcode(img_path):
                confirmed.add(img_name)
                continue
            else:
                break

        return confirmed
