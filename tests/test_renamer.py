import csv
from unittest.mock import patch

import pytest

from koma.core.renamer import Renamer
from koma.core.scanner import ScanResult


@pytest.fixture
def renamer_setup(tmp_path):
    work_dir = tmp_path / "chapter_1"
    work_dir.mkdir()
    (work_dir / "10.avif").touch()
    (work_dir / "cover.webp").touch()
    (work_dir / "2.png").touch()
    (work_dir / "001.jpg").touch()
    return work_dir


def test_renamer_success(renamer_setup, ext_config, mock_image_processor):
    """测试完整的重命名流程"""
    work_dir = renamer_setup

    with patch("koma.core.renamer.Scanner") as MockScanner:
        res = ScanResult()
        res.to_convert = [work_dir / "10.avif", work_dir / "COVER.webp"]
        res.to_copy = [work_dir / "2.png", work_dir / "001.jpg"]

        MockScanner.return_value.run.return_value = iter([(work_dir, res)])

        renamer = Renamer(work_dir, ext_config, mock_image_processor)
        renamer.run()

        # 验证封面置顶 + 自然排序
        assert (work_dir / "000.webp").exists()  # cover
        assert (work_dir / "001.jpg").exists()  # 001
        assert (work_dir / "002.png").exists()  # 2
        assert (work_dir / "003.avif").exists()  # 10


def test_renamer_empty_folder(renamer_setup, ext_config, mock_image_processor):
    """测试没有图片的情况"""
    with patch("koma.core.renamer.Scanner") as MockScanner:
        MockScanner.return_value.run.return_value = iter(
            [(renamer_setup, ScanResult())]
        )
        renamer = Renamer(renamer_setup, ext_config, mock_image_processor)
        renamer.run()
        # 不应报错


def test_temp_rename_failure(renamer_setup, ext_config, mock_image_processor):
    """测试临时重命名阶段失败"""
    work_dir = renamer_setup
    with (
        patch("koma.core.renamer.Scanner") as MockScanner,
        patch("os.rename") as mock_os_rename,
    ):
        res = ScanResult(to_copy=[work_dir / "1.jpg"])
        MockScanner.return_value.run.return_value = iter([(work_dir, res)])
        mock_os_rename.side_effect = OSError("Permission denied")

        renamer = Renamer(work_dir, ext_config, mock_image_processor)
        renamer.run()
        # 应该捕获异常并继续


def test_final_rename_failure(renamer_setup, ext_config, mock_image_processor):
    """测试最终重命名阶段失败"""
    work_dir = renamer_setup
    with (
        patch("koma.core.renamer.Scanner") as MockScanner,
        patch("os.rename") as mock_os_rename,
    ):
        res = ScanResult(to_copy=[work_dir / "1.jpg"])
        MockScanner.return_value.run.return_value = iter([(work_dir, res)])

        # 第一次(temp)成功，第二次(final)失败
        def side_effect(src, dst):
            if ".tmp_" in str(dst):
                return
            raise OSError("File locked")

        mock_os_rename.side_effect = side_effect

        renamer = Renamer(work_dir, ext_config, mock_image_processor)
        renamer.run()


def test_renamer_csv_export(renamer_setup, ext_config, mock_image_processor):
    """测试 CSV 报告生成功能"""
    work_dir = renamer_setup
    with patch("koma.core.renamer.Scanner") as MockScanner:
        res = ScanResult()
        res.to_convert = [work_dir / "10.avif"]
        res.to_copy = [work_dir / "2.png"]
        MockScanner.return_value.run.return_value = iter([(work_dir, res)])

        renamer = Renamer(work_dir, ext_config, mock_image_processor, export_csv=True)
        renamer.run()

        csv_files = list(work_dir.glob("rename_report_*.csv"))
        assert len(csv_files) == 1

        with open(csv_files[0], encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            rows = list(reader)
            assert len(rows) == 3  # Header + 2 items
            assert "10.avif" in rows[2][1]
            assert "001.avif" in rows[2][2]
