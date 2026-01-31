from pathlib import Path

import cv2
import numpy as np

from koma.config import QR_WHITELIST

from .logger import logger


class AdDetector:
    _wechat_detector = None
    _detector_type = None

    @staticmethod
    def _get_detector():
        """
        获取二维码探测器实例
        优先加载本地 WeChatQRCode 模型，如果失败则回退到标准版
        """
        if AdDetector._wechat_detector is not None:
            return AdDetector._wechat_detector

        current_dir = Path(__file__).parent
        model_dir = current_dir.parent / "resources" / "wechat_qrcode"

        required_files = [
            "detect.prototxt",
            "detect.caffemodel",
            "sr.prototxt",
            "sr.caffemodel",
        ]
        missing_files = [f for f in required_files if not (model_dir / f).exists()]

        if not missing_files:
            try:
                # 初始化微信引擎
                AdDetector._wechat_detector = cv2.wechat_qrcode_WeChatQRCode(  # type: ignore
                    str(model_dir / "detect.prototxt"),
                    str(model_dir / "detect.caffemodel"),
                    str(model_dir / "sr.prototxt"),
                    str(model_dir / "sr.caffemodel"),
                )
                AdDetector._detector_type = "WECHAT"
            except Exception as e:
                logger.error(f"加载微信模型失败: {e}，将回退到标准版")
                AdDetector._detector_type = "STANDARD"
        else:
            AdDetector._detector_type = "STANDARD"

        if AdDetector._detector_type == "STANDARD":
            AdDetector._wechat_detector = "STANDARD_PLACEHOLDER"

        return AdDetector._wechat_detector

    @staticmethod
    def is_spam_qrcode(path: Path) -> bool:
        """检测是否包含非白名单（广告）二维码"""
        try:
            img_array = np.fromfile(str(path), dtype=np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_GRAYSCALE)

            if img is None:
                return False

            detector_instance = AdDetector._get_detector()
            found_contents = []

            if AdDetector._detector_type == "WECHAT":
                try:
                    res, _ = detector_instance.detectAndDecode(img)  # type: ignore
                    found_contents = res
                except Exception:
                    pass
            else:
                std_detector = cv2.QRCodeDetector()
                data, _, _ = std_detector.detectAndDecode(img)
                if data:
                    found_contents = [data]

            if not found_contents:
                return False

            for data in found_contents:
                if not data:
                    continue
                data = data.lower()

                # 拦截非白名单二维码
                is_safe = False
                for safe_domain in QR_WHITELIST:
                    if safe_domain in data:
                        is_safe = True
                        break

                if not is_safe:
                    logger.info(f"🚫 发现疑似广告二维码: {data[:50]}... 在 {path}")
                    return True

        except Exception:
            pass

        return False
