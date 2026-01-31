from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest

from koma.utils import AdDetector, analyze_image


def test_analyze_image_gray(tmp_path):
    """测试灰度图像"""
    img_data = np.full((100, 100, 3), 128, dtype=np.uint8)
    p = tmp_path / "gray.png"
    cv2.imwrite(str(p), img_data)
    is_anim, is_gray = analyze_image(p)
    assert is_gray and not is_anim


def test_analyze_image_color(tmp_path):
    """测试彩色图像"""
    img_data = np.zeros((100, 100, 3), dtype=np.uint8)
    img_data[:] = (255, 0, 0)
    p = tmp_path / "color.png"
    cv2.imwrite(str(p), img_data)
    is_anim, is_gray = analyze_image(p)
    assert not is_gray and not is_anim


@pytest.fixture(autouse=True)
def reset_detector_state():
    AdDetector._wechat_detector = None
    AdDetector._detector_type = None
    yield
    AdDetector._wechat_detector = None
    AdDetector._detector_type = None


@pytest.fixture
def mock_deps():
    with (
        patch("koma.utils.ad_detector.cv2") as m_cv2,
        patch("koma.utils.ad_detector.np.fromfile") as m_fromfile,
        patch("koma.utils.ad_detector.AdDetector._get_detector") as m_get_detector,
    ):
        m_fromfile.return_value = np.array([1])
        m_cv2.imdecode.return_value = np.zeros((100, 100), dtype=np.uint8)
        m_get_detector.return_value = MagicMock()
        std_detector_instance = m_cv2.QRCodeDetector.return_value

        yield m_cv2, std_detector_instance


def test_logic_spam_detection(tmp_path, mock_deps):
    """测试广告"""
    _, mock_detector = mock_deps

    # 模拟发现广告链接
    mock_detector.detectAndDecode.return_value = ("http://spam.com", None, None)

    p = tmp_path / "spam.jpg"
    p.touch()

    is_spam = AdDetector.is_spam_qrcode(p)

    assert is_spam is True


def test_logic_whitelist_pass(tmp_path, mock_deps):
    """测试白名单"""
    _, mock_detector = mock_deps

    # 临时修改配置里的白名单
    with patch("koma.utils.ad_detector.QR_WHITELIST", ["pixiv.net"]):
        mock_detector.detectAndDecode.return_value = (
            "https://pixiv.net/abc",
            None,
            None,
        )

        p = tmp_path / "safe.jpg"
        p.touch()

        is_spam = AdDetector.is_spam_qrcode(p)

        assert is_spam is False


def test_logic_wechat_fallback(tmp_path, mock_deps):
    """测试回退到标准检测器"""
    _, mock_detector = mock_deps
    mock_detector.detectAndDecode.return_value = ("http://fallback-ad.com", None, None)

    p = tmp_path / "fallback.jpg"
    p.touch()

    is_spam = AdDetector.is_spam_qrcode(p)

    assert is_spam is True


def test_logic_image_load_fail(tmp_path, mock_deps):
    """测试图片读取失败"""
    m_cv2, _ = mock_deps
    m_cv2.imdecode.return_value = None
    p = tmp_path / "broken.jpg"
    p.touch()

    is_spam = AdDetector.is_spam_qrcode(p)

    assert is_spam is False
