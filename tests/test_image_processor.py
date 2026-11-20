from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest

from koma.core.image_processor import ImageProcessor


@pytest.fixture
def processor(scanner_config):
    return ImageProcessor(scanner_config)


def _write_qr(path: Path, url: str, size: int = 320) -> None:
    """生成一张真实二维码图片（用 imencode 规避 cv2.imwrite 的非 ASCII 路径问题）"""
    qr = cv2.QRCodeEncoder_create().encode(url)
    qr = cv2.resize(qr, (size, size), interpolation=cv2.INTER_NEAREST)
    qr = cv2.copyMakeBorder(qr, 50, 50, 50, 50, cv2.BORDER_CONSTANT, value=255)
    ok, buf = cv2.imencode(".png", qr)
    assert ok
    path.write_bytes(buf.tobytes())


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


def test_qr_engine_is_wechat_not_fallback(processor):
    """
    必须真正加载 WeChatQRCode 引擎，而不是静默回退到标准检测器。

    标准 QRCodeDetector 只是兜底：实测 12 个难度场景里只命中 3 个，
    而 WeChatQRCode 命中 8 个（小尺寸 / 低对比 / 模糊场景全靠它）。
    一旦回退，广告清理会明显失效 —— 所以这里把引擎类型锁死。

    回归背景：OpenCV 5.0 把 WeChatQRCode 的构造签名改成无参，
    旧代码传 4 个模型路径会抛异常并被 except 静默吞掉。
    """
    processor._get_qr_detector()

    assert processor._qr_engine_type == "WECHAT", (
        "微信二维码引擎未加载，已回退到标准检测器，广告检出率会明显下降"
    )
    assert isinstance(processor._qr_detector, cv2.wechat_qrcode_WeChatQRCode)


def test_has_ad_qrcode_detects_real_qrcode(tmp_path, processor):
    """端到端：真实二维码图片应被判为广告（走真实引擎，不用 mock）"""
    p = tmp_path / "ad_page.png"
    _write_qr(p, "https://ads.example.com/promo")

    assert processor.has_ad_qrcode(p) is True
    assert processor._qr_engine_type == "WECHAT"


def test_has_ad_qrcode_whitelist_with_real_qrcode(tmp_path, processor):
    """端到端：白名单内的域名即使解出二维码也不算广告"""
    processor.config.qr_whitelist = ["pixiv.net"]

    p = tmp_path / "cover_page.png"
    _write_qr(p, "https://www.pixiv.net/artworks/12345")

    assert processor.has_ad_qrcode(p) is False
    assert processor._qr_engine_type == "WECHAT"


@pytest.mark.parametrize(
    "url",
    [
        "https://pixiv.net/artworks/1",  # 主域
        "https://www.pixiv.net/artworks/1",  # 子域
        "pixiv.net/artworks/1",  # 二维码里常见的无 scheme 写法
        "HTTPS://WWW.PIXIV.NET/x",  # 大小写
        "https://toranoana.jp/x",  # 新增的日本零售站
        "https://www.melonbooks.co.jp/x",
    ],
)
def test_whitelist_accepts_domain_and_subdomains(processor, url):
    """白名单按 host 域名边界匹配：主域与其子域都算命中"""
    assert processor._is_whitelisted(url) is True


@pytest.mark.parametrize(
    "url",
    [
        # 旧子串匹配会把这两个误判为"安全"，属于广告检测绕过
        "https://notpixiv.net/ad",
        "https://evil.com/?ref=qq.com",
        # 把白名单域名当子域前缀
        "https://pixiv.net.evil.com/x",
        "https://toranoana.jp.evil.com/x",
        # 普通广告
        "https://ads.example.com/promo",
    ],
)
def test_whitelist_rejects_lookalike_and_query_bypass(processor, url):
    """仿冒域名 / query 参数里出现白名单域名，都不能算命中"""
    assert processor._is_whitelisted(url) is False


def test_lookalike_domain_qrcode_is_still_flagged(tmp_path, processor):
    """端到端：仿冒域名的真实二维码必须仍被判为广告"""
    p = tmp_path / "fake_pixiv.png"
    _write_qr(p, "https://notpixiv.net/ad")

    assert processor.has_ad_qrcode(p) is True


def test_whitelist_empty_host_is_not_whitelisted(processor):
    """非 URL 内容（取不出 host）不能因为白名单而放行"""
    assert processor._extract_host("") == ""
    assert processor._is_whitelisted("") is False
    assert processor._is_whitelisted("   ") is False
