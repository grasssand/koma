import csv
from pathlib import Path
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
    """测试常规重命名逻辑"""
    work_dir = renamer_setup

    with patch("koma.core.renamer.Scanner") as MockScanner:
        res = ScanResult()
        res.to_convert = [work_dir / "10.avif", work_dir / "COVER.webp"]
        res.to_copy = [work_dir / "2.png", work_dir / "001.jpg"]

        mock_instance = MockScanner.return_value
        mock_instance.run.return_value = iter([(work_dir, res)])

        renamer = Renamer(work_dir, ext_config, mock_image_processor)
        renamer.run()

        # 验证封面置顶 + 自然排序
        assert (work_dir / "000.webp").exists()  # cover
        assert (work_dir / "001.jpg").exists()  # 001
        assert (work_dir / "002.png").exists()  # 2
        assert (work_dir / "003.avif").exists()  # 10


def test_renamer_skip_single_cover(tmp_path, ext_config, mock_image_processor):
    """测试仅含单张 Cover 图时跳过"""
    work_dir = tmp_path / "cover_only"
    work_dir.mkdir()
    cover_file = work_dir / "cover.jpg"
    cover_file.touch()

    with patch("koma.core.renamer.Scanner") as MockScanner:
        res = ScanResult()
        res.to_copy = [cover_file]

        mock_instance = MockScanner.return_value
        mock_instance.run.return_value = iter([(work_dir, res)])

        renamer = Renamer(work_dir, ext_config, mock_image_processor)
        renamer.run()

        # 验证未被重命名
        assert cover_file.exists()
        assert not (work_dir / "000.jpg").exists()


def test_renamer_csv_export(renamer_setup, ext_config, mock_image_processor):
    """测试 CSV 导出"""
    work_dir = renamer_setup
    with patch("koma.core.renamer.Scanner") as MockScanner:
        res = ScanResult()
        res.to_convert = [work_dir / "10.avif"]

        mock_instance = MockScanner.return_value
        mock_instance.run.return_value = iter([(work_dir, res)])

        renamer = Renamer(work_dir, ext_config, mock_image_processor)
        renamer.run(options={"export_csv": True})

        csv_files = list(work_dir.glob("rename_report_*.csv"))
        assert len(csv_files) == 1

        with open(csv_files[0], encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            rows = list(reader)
            assert len(rows) >= 2  # Header + 1 row


def test_renamer_archive_processing(tmp_path, ext_config, mock_image_processor):
    """测试压缩包处理流程"""
    work_dir = tmp_path / "archive_test"
    work_dir.mkdir()
    archive_file = work_dir / "test.zip"
    archive_file.touch()
    # 重名文件不会覆盖
    target_file = work_dir / "test.cbz"
    target_file.touch()

    fixed_time = 1700000000

    with (
        patch("koma.core.renamer.Scanner") as MockScanner,
        patch("koma.core.renamer.ArchiveHandler") as MockArchiveHandler,
        patch("koma.core.renamer.send2trash") as mock_send2trash,
        patch("koma.core.renamer.shutil.move") as mock_move,
        patch("koma.core.renamer.tempfile.TemporaryDirectory") as mock_temp_dir,
        patch("koma.core.renamer.time.time", return_value=fixed_time),
    ):
        # 模拟 Scanner 返回压缩包
        res = ScanResult()
        res.archives = [archive_file]

        mock_scanner_inst = MockScanner.return_value
        mock_scanner_inst.run.return_value = iter([(work_dir, res)])

        # 模拟临时目录和解压
        temp_extract_dir = tmp_path / "temp_extract"
        temp_extract_dir.mkdir()
        mock_temp_dir.return_value.__enter__.return_value = str(temp_extract_dir)

        mock_ah_inst = MockArchiveHandler.return_value
        mock_ah_inst.extract.return_value = temp_extract_dir
        mock_ah_inst.pack.return_value = True

        # 在模拟解压目录中创建文件
        (temp_extract_dir / "p2.jpg").touch()
        (temp_extract_dir / "p1.png").touch()

        # 运行 Renamer
        renamer = Renamer(work_dir, ext_config, mock_image_processor)
        renamer.run(options={"enable_archive_scan": True, "pack_format": "cbz"})

        # 验证 Scanner 调用参数
        call_args = mock_scanner_inst.run.call_args
        assert call_args.kwargs["options"]["enable_archive_scan"] is False

        # 验证解压
        mock_ah_inst.extract.assert_called_with(
            archive_file, Path(str(temp_extract_dir))
        )

        # 验证重命名
        # p1.png -> 000.png, p2.jpg -> 001.jpg (按文件名排序 p1 在前)
        assert (temp_extract_dir / "000.png").exists()
        assert (temp_extract_dir / "001.jpg").exists()

        # 验证打包
        mock_ah_inst.pack.assert_called()
        _, kwargs = mock_ah_inst.pack.call_args
        assert kwargs["fmt"] == "cbz"

        expected_name = f"test_{fixed_time}.cbz"
        expected_final_path = work_dir / expected_name

        # 验证回收站
        mock_send2trash.assert_called_with(str(archive_file))

        # 验证移动
        assert mock_move.called
        args, _ = mock_move.call_args
        assert str(args[1]) == str(expected_final_path)

        # 确认原来的冲突文件没有被覆盖
        assert target_file.exists()
