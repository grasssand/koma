from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest

from koma.core.image_processor import ImageProcessor


@pytest.fixture
def processor(scanner_config):
    return ImageProcessor(scanner_config)


def test_analyze_image_gray(tmp_path, processor):
    """测试灰度图像识别"""
    img_data = np.full((100, 100, 3), 128, dtype=np.uint8)
    p = tmp_path / "gray.png"
    cv2.imwrite(str(p), img_data)

    info = processor.analyze(p)
    assert info.is_grayscale is True
    assert info.is_animated is False


def test_analyze_image_color(tmp_path, processor):
    """测试彩色图像识别"""
    img_data = np.zeros((100, 100, 3), dtype=np.uint8)
    img_data[:] = (255, 0, 0)  # Blue
    p = tmp_path / "color.png"
    cv2.imwrite(str(p), img_data)

    info = processor.analyze(p)
    assert info.is_grayscale is False


def test_ad_detection_logic(tmp_path, processor):
    """测试二维码广告检测逻辑"""
    processor._qr_detector = MagicMock()
    processor._qr_engine_type = "STANDARD"

    # 模拟检测到一个广告链接
    processor._qr_detector.detectAndDecode.return_value = (
        "http://spam.com",
        None,
        None,
    )

    p = tmp_path / "spam.jpg"
    p.touch()

    processor.config.enable_ad_scan = True

    with (
        patch("koma.core.image_processor.np.fromfile"),
        patch("koma.core.image_processor.cv2.imdecode") as m_decode,
    ):
        # 返回一个非 None 的伪造图片对象
        m_decode.return_value = np.zeros((10, 10), dtype=np.uint8)

        is_ad = processor.has_ad_qrcode(p)
        assert is_ad is True


def test_ad_whitelist_pass(tmp_path, processor):
    """测试白名单通过"""
    processor._qr_detector = MagicMock()
    processor._qr_engine_type = "STANDARD"
    # 临时修改配置里的白名单
    processor.config.qr_whitelist = ["pixiv.net"]
    processor.config.enable_ad_scan = True

    processor._qr_detector.detectAndDecode.return_value = (
        "https://pixiv.net/artworks/123",
        None,
        None,
    )

    p = tmp_path / "safe.jpg"
    p.touch()

    with (
        patch("koma.core.image_processor.np.fromfile"),
        patch(
            "koma.core.image_processor.cv2.imdecode", return_value=np.zeros((10, 10))
        ),
    ):
        is_ad = processor.has_ad_qrcode(p)
        assert is_ad is False
