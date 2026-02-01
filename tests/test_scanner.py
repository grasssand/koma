from unittest.mock import patch

import pytest

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


def test_scanner_classification(scanner_setup):
    """测试基本的文件分类逻辑"""
    with patch("koma.core.scanner.analyze_image", return_value=(False, False)):
        scanner = Scanner(scanner_setup, enable_ad_detection=False)
        results = list(scanner.run())

        assert len(results) == 1
        root, res = results[0]

        convert_names = [p.name for p in res.to_convert]
        copy_names = [p.name for p in res.to_copy]
        junk_names = [p.name for p in res.junk]

        assert "01.jpg" in convert_names
        assert "02.png" in convert_names
        assert "03.avif" in copy_names

        assert "script.txt" in junk_names
        assert ".hidden" in junk_names


def test_scanner_ad_detection_logic(scanner_setup):
    """测试广告检测的核心逻辑"""
    (scanner_setup / "04.jpg").touch()
    (scanner_setup / "05.jpg").touch()
    (scanner_setup / "06.jpg").touch()

    with (
        patch("koma.core.scanner.analyze_image") as mock_analyze,
        patch("koma.core.scanner.AdDetector") as MockAdDetector,
    ):
        mock_analyze.return_value = (False, False)

        # 05 或 06 是广告
        def side_effect(path):
            if "05" in path.name or "06" in path.name:
                return True
            return False

        MockAdDetector.is_spam_qrcode.side_effect = side_effect

        scanner = Scanner(scanner_setup, enable_ad_detection=True)
        results = list(scanner.run())

        res = results[0][1]
        ads_names = [p.name for p in res.ads]
        convert_names = [p.name for p in res.to_convert]

        assert MockAdDetector.is_spam_qrcode.call_count >= 1

        # 验证广告被识别
        assert "06.jpg" in ads_names
        assert "05.jpg" in ads_names
        # 验证正文没有被误判
        assert "04.jpg" in convert_names
        assert "04.jpg" not in ads_names


def test_scanner_ad_stop_on_anim(scanner_setup):
    """测试遇到动图立即停止检测"""
    (scanner_setup / "ending.gif").touch()

    with (
        patch("koma.core.scanner.analyze_image") as mock_analyze,
        patch("koma.core.scanner.AdDetector") as MockAdDetector,
    ):
        mock_analyze.return_value = (True, False)

        scanner = Scanner(scanner_setup, enable_ad_detection=True)
        list(scanner.run())

        MockAdDetector.is_spam_qrcode.assert_not_called()


def test_scanner_ad_stop_on_gray(scanner_setup):
    """测试遇到灰度图立即停止检测"""
    (scanner_setup / "gray.jpg").touch()

    with (
        patch("koma.core.scanner.analyze_image") as mock_analyze,
        patch("koma.core.scanner.AdDetector") as MockAdDetector,
    ):
        mock_analyze.return_value = (False, True)

        scanner = Scanner(scanner_setup, enable_ad_detection=True)
        list(scanner.run())

        MockAdDetector.is_spam_qrcode.assert_not_called()
