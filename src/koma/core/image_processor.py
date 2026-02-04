import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from koma.config import ScannerConfig

logger = logging.getLogger(__name__)


@dataclass
class ImageInfo:
    is_animated: bool = False
    is_grayscale: bool = False


class ImageProcessor:
    def __init__(self, config: ScannerConfig):
        self.config = config

        self._qr_detector = None
        self._qr_engine_type = None

    def analyze(self, file_path: Path) -> ImageInfo:
        """综合分析图片属性，判断是否为动图和灰度图"""
        try:
            is_anim = self._check_is_animated(file_path)
            if is_anim:
                return ImageInfo(is_animated=True, is_grayscale=False)

            is_gray = self._check_is_grayscale(file_path)

            return ImageInfo(is_animated=False, is_grayscale=is_gray)

        except Exception as e:
            logger.debug(f"图片分析异常 {file_path.name}: {e}")
            return ImageInfo()

    def has_ad_qrcode(self, file_path: Path) -> bool:
        """检测是否包含广告二维码"""
        if not self.config.enable_ad_scan:
            return False

        try:
            img_array = np.fromfile(str(file_path), dtype=np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_GRAYSCALE)

            if img is None:
                return False

            detector = self._get_qr_detector()
            found_urls = []

            if self._qr_engine_type == "WECHAT":
                try:
                    res, *_ = detector.detectAndDecode(img)
                    found_urls = res
                except Exception:
                    pass
            else:
                # 标准库回退
                res, *_ = detector.detectAndDecode(img)
                if res:
                    found_urls = [res]

            if not found_urls:
                return False

            for url in found_urls:
                if not url:
                    continue
                url_lower = url.lower()

                # 只要发现一个不在白名单里的，就判定为广告
                is_safe = False
                for safe_domain in self.config.qr_whitelist:
                    if safe_domain in url_lower:
                        is_safe = True
                        break

                if not is_safe:
                    logger.info(f"🚫 发现广告二维码: {url[:30]}... 在 {file_path.name}")
                    return True

            return False

        except Exception as e:
            logger.debug(f"二维码检测出错 {file_path.name}: {e}")
            return False

    def _check_is_animated(self, file_path: Path) -> bool:
        try:
            with Image.open(file_path) as img:
                return getattr(img, "is_animated", False)
        except Exception:
            return False

    def _check_is_grayscale(self, file_path: Path) -> bool:
        try:
            img_array = np.fromfile(str(file_path), dtype=np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

            if img is None:
                return False

            thumb = cv2.resize(img, (64, 64), interpolation=cv2.INTER_AREA)
            hsv = cv2.cvtColor(thumb, cv2.COLOR_BGR2HSV)

            return bool(np.mean(hsv[:, :, 1]) < 5.0)
        except Exception:
            return False

    def _get_qr_detector(self):
        """加载二维码模型"""
        if self._qr_detector is not None:
            return self._qr_detector

        try:
            import sys

            if getattr(sys, "frozen", False):
                base_path = Path(sys._MEIPASS) / "koma"  # type: ignore
            else:
                base_path = Path(__file__).parent.parent

            model_dir = base_path / "resources" / "wechat_qrcode"

            files = [
                "detect.prototxt",
                "detect.caffemodel",
                "sr.prototxt",
                "sr.caffemodel",
            ]
            if all((model_dir / f).exists() for f in files):
                self._qr_detector = cv2.wechat_qrcode_WeChatQRCode(  # type: ignore
                    str(model_dir / "detect.prototxt"),
                    str(model_dir / "detect.caffemodel"),
                    str(model_dir / "sr.prototxt"),
                    str(model_dir / "sr.caffemodel"),
                )
                self._qr_engine_type = "WECHAT"
                logger.debug("✅ 微信二维码引擎加载成功")
                return self._qr_detector
            else:
                logger.warning(f"⚠️ 微信模型文件缺失: {model_dir}")

        except Exception as e:
            logger.warning(f"⚠️ 微信模型加载异常: {e}")

        logger.info("🔄 回退使用标准 OpenCV QRCodeDetector")
        self._qr_detector = cv2.QRCodeDetector()
        self._qr_engine_type = "STANDARD"
        return self._qr_detector
