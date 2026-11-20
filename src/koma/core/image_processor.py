import logging
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

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

                # 只要发现一个不在白名单里的，就判定为广告
                if not self._is_whitelisted(url):
                    logger.info(f"🚫 发现二维码广告: {url[:30]}... 在 {file_path}")
                    return True

            return False

        except Exception as e:
            logger.debug(f"二维码检测出错 {file_path.name}: {e}")
            return False

    @staticmethod
    def _extract_host(url: str) -> str:
        """
        从二维码内容里取出 host。
        """
        text = url.strip()
        if not text:
            return ""

        if "://" not in text:
            text = "http://" + text

        try:
            return urlsplit(text).hostname or ""
        except ValueError:
            # 端口非法等情况下 hostname 会抛异常
            return ""

    def _is_whitelisted(self, url: str) -> bool:
        """
        按 host 做**域名边界**匹配二维码内容是否命中白名单域名。
        """
        host = self._extract_host(url)
        if not host:
            return False

        for domain in self.config.qr_whitelist:
            d = domain.strip().lower().lstrip(".")
            if not d:
                continue
            if host == d or host.endswith("." + d):
                return True
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
        """
        加载二维码检测引擎。

        OpenCV 5.0 起 WeChatQRCode 的两个 CNN 模型（目标检测 + 超分）已内置在 cv2
        """
        if self._qr_detector is not None:
            return self._qr_detector

        try:
            self._qr_detector = cv2.wechat_qrcode_WeChatQRCode()  # type: ignore
            self._qr_engine_type = "WECHAT"
            logger.debug("✅ 微信二维码引擎加载成功")
            return self._qr_detector
        except Exception as e:
            logger.warning(f"⚠️ 微信二维码引擎加载异常: {e}")

        # 兜底：WeChatQRCode 不可用时退回标准检测器。
        # 但小尺寸 / 低对比 / 模糊的广告码检出率会明显下降（实测 8/12 -> 3/12），
        logger.warning("⚠️ 已回退使用标准 OpenCV QRCodeDetector，广告检出率会明显下降")
        self._qr_detector = cv2.QRCodeDetector()
        self._qr_engine_type = "STANDARD"
        return self._qr_detector
