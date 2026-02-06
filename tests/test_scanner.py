import pytest

from koma.core.image_processor import ImageInfo
from koma.core.scanner import Scanner


@pytest.fixture
def scanner_setup(tmp_path):
    root = tmp_path / "manga"
    root.mkdir()

    # 模拟各类文件
    (root / "01.jpg").touch()
    (root / "02.png").touch()
    (root / "03.avif").touch()
    (root / "script.txt").touch()  # Junk
    (root / ".hidden").touch()

    return root


def test_scanner_classification(scanner_setup, ext_config, mock_image_processor):
    """测试基本的文件分类逻辑"""
    scanner = Scanner(scanner_setup, ext_config, mock_image_processor)
    results = list(scanner.run())

    assert len(results) == 1
    _, res = results[0]

    convert_names = [p.name for p in res.to_convert]
    copy_names = [p.name for p in res.to_copy]
    junk_names = [p.name for p in res.junk]

    assert "01.jpg" in convert_names
    assert "02.png" in convert_names
    assert "03.avif" in copy_names

    assert "script.txt" in junk_names
    assert ".hidden" in junk_names


def test_scanner_ad_detection_logic(scanner_setup, ext_config, mock_image_processor):
    """测试广告检测的核心逻辑"""
    (scanner_setup / "04.jpg").touch()
    (scanner_setup / "05.jpg").touch()
    (scanner_setup / "06.jpg").touch()

    def side_effect_qrcode(path):
        return bool("05" in path.name or "06" in path.name)

    mock_image_processor.has_ad_qrcode.side_effect = side_effect_qrcode
    mock_image_processor.analyze.return_value = ImageInfo(False, False)

    scanner = Scanner(scanner_setup, ext_config, mock_image_processor)
    results = list(scanner.run())

    res = results[0][1]
    ads_names = [p.name for p in res.ads]
    convert_names = [p.name for p in res.to_convert]

    # 验证广告被识别
    assert "06.jpg" in ads_names
    assert "05.jpg" in ads_names
    # 验证正文没有被误判
    assert "04.jpg" in convert_names
    assert "04.jpg" not in ads_names


def test_scanner_stop_on_special(scanner_setup, ext_config, mock_image_processor):
    """测试遇到动图/灰度图停止扫描"""
    (scanner_setup / "end.gif").touch()

    mock_image_processor.analyze.return_value = ImageInfo(is_animated=True)

    scanner = Scanner(scanner_setup, ext_config, mock_image_processor)
    list(scanner.run())

    mock_image_processor.has_ad_qrcode.assert_not_called()
