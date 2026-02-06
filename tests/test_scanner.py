import errno
from pathlib import Path
from unittest.mock import patch

import pytest

from koma.core.image_processor import ImageInfo
from koma.core.scanner import Scanner


@pytest.fixture
def scanner_setup(tmp_path):
    root = tmp_path / "manga"
    root.mkdir()

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
    # 启用广告扫描
    options = {"enable_ad_scan": True}
    results = list(scanner.run(options=options))

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
    options = {"enable_ad_scan": True}
    list(scanner.run(options=options))

    mock_image_processor.has_ad_qrcode.assert_not_called()


@pytest.fixture
def archive_options(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    return {
        "enable_archive_scan": True,
        "archive_out_path": str(output),
        "repack": True,
        "pack_format": "cbz",
    }


def test_scanner_skip_clean_archive(
    scanner_setup, ext_config, mock_image_processor, archive_options
):
    """测试：如果压缩包内没有清理任何文件，应该跳过重打包"""
    (scanner_setup / "clean.zip").touch()

    with (
        patch("koma.core.scanner.ArchiveHandler"),
        patch.object(
            Scanner, "_clean_directory_recursive", return_value=0
        ) as mock_clean,
    ):
        scanner = Scanner(scanner_setup, ext_config, mock_image_processor)
        results = list(scanner.run(options=archive_options))

        processed_count = 0
        for _, res in results:
            processed_count += res.processed_archives

        assert processed_count == 0

        scanner.archive_handler.pack.assert_not_called()  # type: ignore
        mock_clean.assert_called()


def test_scanner_process_dirty_archive(
    scanner_setup, ext_config, mock_image_processor, archive_options
):
    """测试：压缩包内有垃圾文件，触发重打包流程"""
    (scanner_setup / "dirty.zip").touch()

    with patch("koma.core.scanner.ArchiveHandler") as MockHandler:
        mock_instance = MockHandler.return_value
        mock_instance.extract.return_value = Path("/tmp/mock_extract")

        with patch.object(Scanner, "_clean_directory_recursive", return_value=1):
            scanner = Scanner(scanner_setup, ext_config, mock_image_processor)
            results = list(scanner.run(options=archive_options))

            # 验证统计数据
            total_processed = sum(res.processed_archives for _, res in results)
            assert total_processed == 1

            # 验证调用了 pack，且参数正确
            mock_instance.pack.assert_called_once()
            _, kwargs = mock_instance.pack.call_args
            assert kwargs["fmt"] == "cbz"
            assert kwargs.get("level") == "normal"


def test_scanner_archive_disk_space_check(
    scanner_setup, ext_config, mock_image_processor, archive_options, caplog
):
    """测试：磁盘空间不足时跳过处理"""
    (scanner_setup / "big.zip").touch()

    # 模拟 zip 文件大小 100MB
    with patch.object(Path, "stat") as mock_stat:
        mock_stat.return_value.st_size = 100 * 1024 * 1024

        # 模拟磁盘剩余空间 10MB (不足 2.5倍)
        with patch("shutil.disk_usage") as mock_usage:
            mock_usage.return_value.free = 10 * 1024 * 1024

            scanner = Scanner(scanner_setup, ext_config, mock_image_processor)
            list(scanner.run(options=archive_options))

            # 验证错误日志
            assert "磁盘空间不足" in caplog.text


def test_scanner_infinite_loop_prevention(
    scanner_setup, ext_config, mock_image_processor
):
    """测试：输出目录在输入目录内部时，应避免递归扫描输出目录"""
    output_dir = scanner_setup / "output"
    output_dir.mkdir()

    (output_dir / "should_ignore.jpg").touch()
    (scanner_setup / "normal.jpg").touch()

    options = {
        "enable_archive_scan": True,
        "archive_out_path": str(output_dir),
    }

    scanner = Scanner(scanner_setup, ext_config, mock_image_processor)
    results = list(scanner.run(options=options))

    # 收集所有扫描到的文件
    all_files = []
    for _, res in results:
        all_files.extend(res.to_convert)
        all_files.extend(res.to_copy)

    file_names = [f.name for f in all_files]

    assert "normal.jpg" in file_names
    assert "should_ignore.jpg" not in file_names


def test_process_archive_runtime_disk_full(
    scanner_setup, ext_config, mock_image_processor, archive_options, caplog
):
    """测试在处理过程中（如解压/移动时）突然发生磁盘空间不足异常 (Errno 28)"""
    (scanner_setup / "bomb.zip").touch()

    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value.free = 10**12  # 1TB free

        with patch("koma.core.scanner.ArchiveHandler") as MockHandlerClass:
            mock_handler_instance = MockHandlerClass.return_value

            disk_full_error = OSError(errno.ENOSPC, "No space left on device")
            mock_handler_instance.extract.side_effect = disk_full_error

            scanner = Scanner(scanner_setup, ext_config, mock_image_processor)

            list(scanner.run(options=archive_options))

            assert "磁盘空间耗尽" in caplog.text
            assert "bomb.zip" in caplog.text


def test_process_archive_generic_io_error(
    scanner_setup, ext_config, mock_image_processor, archive_options, caplog
):
    """测试普通 IO 错误"""
    (scanner_setup / "corrupt.zip").touch()

    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value.free = 10**12

        with patch("koma.core.scanner.ArchiveHandler") as MockHandlerClass:
            mock_handler_instance = MockHandlerClass.return_value

            perm_error = OSError(errno.EACCES, "Permission denied")
            mock_handler_instance.extract.side_effect = perm_error

            scanner = Scanner(scanner_setup, ext_config, mock_image_processor)
            list(scanner.run(options=archive_options))

            assert "处理压缩包IO错误" in caplog.text
            assert "磁盘空间耗尽" not in caplog.text


def test_clean_directory_recursive_real_logic(
    ext_config, mock_image_processor, tmp_path
):
    """
    测试 _clean_directory_recursive 的内部逻辑：
    验证循环、删除垃圾、删除广告、计数是否正确。
    """
    target_dir = tmp_path / "extract_temp"
    target_dir.mkdir()

    # 垃圾文件 (should be deleted)
    junk_file = target_dir / "thumbs.db"
    junk_file.touch()

    # 广告图片 (should be deleted)
    ad_file = target_dir / "zz_ad.jpg"
    ad_file.touch()

    # 正常图片 (should keep)
    normal_file = target_dir / "01_chapter.jpg"
    normal_file.touch()

    # 子文件夹里的垃圾
    sub_dir = target_dir / "subdir"
    sub_dir.mkdir()
    sub_junk = sub_dir / ".DS_Store"
    sub_junk.touch()

    # 模拟广告检测
    def side_effect_qrcode(path):
        return "ad" in path.name

    mock_image_processor.has_ad_qrcode.side_effect = side_effect_qrcode
    mock_image_processor.analyze.return_value = ImageInfo(False, False)

    scanner = Scanner(tmp_path, ext_config, mock_image_processor)

    deleted_count = scanner._clean_directory_recursive(target_dir, check_ads=True)

    # 预期删除: thumbs.db, ad_01.jpg, .DS_Store
    assert deleted_count == 3

    # 验证文件物理状态
    assert not junk_file.exists(), "垃圾文件未被删除"
    assert not ad_file.exists(), "广告文件未被删除"
    assert not sub_junk.exists(), "子文件夹垃圾未被删除"
    assert normal_file.exists(), "正常文件被误删"
