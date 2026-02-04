from unittest.mock import MagicMock

import pytest

from koma.config import GlobalConfig
from koma.core.image_processor import ImageInfo, ImageProcessor


@pytest.fixture
def global_config():
    """提供一套默认的全局配置"""
    return GlobalConfig()


@pytest.fixture
def ext_config(global_config):
    return global_config.extensions


@pytest.fixture
def scanner_config(global_config):
    return global_config.scanner


@pytest.fixture
def converter_config(global_config):
    return global_config.converter


@pytest.fixture
def dedupe_config(global_config):
    return global_config.deduplicator


@pytest.fixture
def mock_image_processor():
    """
    提供一个 Mock 的 ImageProcessor。
    默认行为：不是动图，不是灰度，没有二维码。
    """
    processor = MagicMock(spec=ImageProcessor)
    # 设置 analyze 的默认返回值
    processor.analyze.return_value = ImageInfo(is_animated=False, is_grayscale=False)
    # 设置 has_ad_qrcode 的默认返回值
    processor.has_ad_qrcode.return_value = False
    return processor
