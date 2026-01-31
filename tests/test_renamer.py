from unittest.mock import patch

import pytest

from koma.core.renamer import Renamer
from koma.core.scanner import ScanResult


@pytest.fixture
def renamer_setup(tmp_path):
    """创建一个带有混乱文件名的测试目录"""
    work_dir = tmp_path / "chapter_1"
    work_dir.mkdir()

    (work_dir / "10.avif").touch()
    (work_dir / "2.png").touch()
    (work_dir / "001.jpg").touch()

    return work_dir


def test_renamer_success(renamer_setup):
    """测试完整的重命名流程"""
    work_dir = renamer_setup

    with patch("koma.core.renamer.Scanner") as MockScanner:
        mock_instance = MockScanner.return_value

        res = ScanResult()
        # 模拟乱序输入
        res.to_convert = [work_dir / "10.avif"]
        res.to_copy = [work_dir / "2.png", work_dir / "001.jpg"]

        mock_instance.run.return_value = iter([(work_dir, res)])

        renamer = Renamer(work_dir)
        renamer.run()

        assert (work_dir / "000.jpg").exists()  # 原 001.jpg
        assert (work_dir / "001.png").exists()  # 原 2.png
        assert (work_dir / "002.avif").exists()  # 原 10.avif

        # 验证旧文件不存在
        assert not (work_dir / "001.jpg").exists()


def test_renamer_empty_folder(renamer_setup):
    """测试没有图片的情况"""
    with patch("koma.core.renamer.Scanner") as MockScanner:
        mock_instance = MockScanner.return_value
        mock_instance.run.return_value = iter([(renamer_setup, ScanResult())])

        renamer = Renamer(renamer_setup)
        renamer.run()


def test_temp_rename_failure(renamer_setup):
    """测试临时重命名失败的情况"""
    work_dir = renamer_setup

    with (
        patch("koma.core.renamer.Scanner") as MockScanner,
        patch("os.rename") as mock_os_rename,
    ):
        mock_instance = MockScanner.return_value
        res = ScanResult(to_copy=[work_dir / "1.jpg"])
        mock_instance.run.return_value = iter([(work_dir, res)])

        mock_os_rename.side_effect = OSError("Permission denied")

        renamer = Renamer(work_dir)
        renamer.run()


def test_final_rename_failure(renamer_setup):
    """测试最终重命名失败的情况"""
    work_dir = renamer_setup

    with (
        patch("koma.core.renamer.Scanner") as MockScanner,
        patch("os.rename") as mock_os_rename,
    ):
        mock_instance = MockScanner.return_value
        res = ScanResult(to_copy=[work_dir / "1.jpg"])
        mock_instance.run.return_value = iter([(work_dir, res)])

        def side_effect(src, dst):
            if ".tmp_" in str(dst):
                return
            raise OSError("File locked")

        mock_os_rename.side_effect = side_effect

        renamer = Renamer(work_dir)
        renamer.run()
