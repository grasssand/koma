from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from koma.core.converter import ConversionResult, Converter, Status
from koma.core.scanner import ScanResult


@pytest.fixture
def converter_setup(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    converter = Converter(input_dir, output_dir, "avif (svt)", 75, False)
    return converter, input_dir, output_dir


@pytest.fixture
def mock_deps():
    with (
        patch("koma.core.converter.CommandGenerator") as MockCmdGen,
        patch("koma.core.converter.analyze_image") as mock_analyze,
        patch("subprocess.run") as mock_run,
    ):
        mock_instance = MockCmdGen.return_value
        mock_instance.generate.return_value = ["ffmpeg", "-i", "fake"]
        mock_instance.get_ext.return_value = ".avif"

        mock_analyze.return_value = (False, False)

        yield mock_instance, mock_run, mock_analyze


def test_convert_worker_success(converter_setup, mock_deps):
    """测试转换成功流程 (Status.SUCCESS)"""
    converter, in_dir, out_dir = converter_setup
    mock_cmd_gen, mock_run, _ = mock_deps

    src_file = in_dir / "test.jpg"
    src_file.write_bytes(b"content" * 100)

    def side_effect(*args, **kwargs):
        expected_out = out_dir / "test.avif"
        expected_out.parent.mkdir(parents=True, exist_ok=True)
        expected_out.write_bytes(b"small")
        return MagicMock(returncode=0)

    mock_run.side_effect = side_effect

    res = converter._convert_worker(src_file)

    assert res.status == Status.SUCCESS
    assert res.file == src_file
    assert res.in_size == 700
    assert res.out_size == 5
    assert mock_run.called


def test_convert_worker_bigger(converter_setup, mock_deps):
    """测试转换后体积变大 (Status.BIGGER)"""
    converter, in_dir, out_dir = converter_setup
    _, mock_run, _ = mock_deps

    src_file = in_dir / "tiny.jpg"
    src_file.write_bytes(b"a")  # 1 byte

    def side_effect(*args, **kwargs):
        expected_out = out_dir / "tiny.avif"
        expected_out.parent.mkdir(parents=True, exist_ok=True)
        # 写入更大的数据
        expected_out.write_bytes(b"very large content")
        return MagicMock()

    mock_run.side_effect = side_effect

    res = converter._convert_worker(src_file)
    assert res.status == Status.BIGGER


@patch("koma.core.converter.time.sleep")
def test_convert_worker_retry_success(mock_sleep, converter_setup, mock_deps):
    """测试转换遇到临时错误，重试后成功"""
    converter, in_dir, out_dir = converter_setup
    _, mock_run, _ = mock_deps

    src_file = in_dir / "retry.jpg"
    src_file.write_bytes(b"content 0123456789abcdef")

    # 模拟：第1次报错，第2次成功
    def side_effect(*args, **kwargs):
        if mock_run.call_count == 1:
            raise Exception("FFmpeg temporary fail")

        # 第二次调用成功
        expected_out = out_dir / "retry.avif"
        expected_out.parent.mkdir(parents=True, exist_ok=True)
        expected_out.write_bytes(b"converted data")
        return MagicMock(returncode=0)

    mock_run.side_effect = side_effect

    res = converter._convert_worker(src_file)

    assert res.status == Status.SUCCESS
    assert mock_run.call_count == 2  # 确保调用了2次
    assert mock_sleep.called  # 确保触发了等待


@patch("koma.core.converter.time.sleep")
def test_convert_worker_fail_max_retries(mock_sleep, converter_setup, mock_deps):
    """测试重试次数耗尽仍然失败 (Status.ERROR)"""
    converter, in_dir, _ = converter_setup
    _, mock_run, _ = mock_deps

    src_file = in_dir / "corrupt.jpg"
    src_file.touch()

    # 始终抛出异常
    mock_run.side_effect = Exception("Persistent FFmpeg crash")

    res = converter._convert_worker(src_file)

    assert res.status == Status.ERROR
    assert "Persistent FFmpeg crash" in res.error
    assert mock_run.call_count == 3  # 默认 MAX_RETRIES = 3
    assert mock_sleep.call_count == 2  # 失败2次后sleep，第3次失败后退出


@patch("koma.core.converter.time.sleep")
def test_copy_worker_retry_success(mock_sleep, converter_setup):
    """测试复制操作的重试逻辑"""
    converter, in_dir, out_dir = converter_setup

    sub_dir = in_dir / "folder"
    sub_dir.mkdir()
    src_file = sub_dir / "retry_copy.png"
    src_file.write_bytes(b"data")

    with patch("shutil.copy2") as mock_copy:
        # 模拟：第1次抛出文件被占用错误，第2次成功
        def side_effect(src, dst):
            if mock_copy.call_count == 1:
                raise OSError("File used by another process")
            # 模拟复制动作 (创建目标文件)
            Path(dst).write_bytes(b"data")

        mock_copy.side_effect = side_effect

        res = converter._copy_worker(src_file)

        assert res.status == Status.COPY
        assert mock_copy.call_count == 2
        assert mock_sleep.called

        # 验证目标文件逻辑路径正确
        expected_out = out_dir / "folder" / "retry_copy.png"
        assert expected_out.exists()


def test_convert_worker_missing_source(converter_setup, mock_deps):
    """测试源文件缺失 (会被重试机制捕获，最终返回 ERROR)"""
    converter, in_dir, _ = converter_setup

    with patch("koma.core.converter.time.sleep"):
        res = converter._convert_worker(in_dir / "ghost.jpg")

    assert res.status == Status.ERROR
    assert "源文件缺失" in res.error


def test_run_loop_and_report(converter_setup, mock_deps):
    """测试主循环"""
    converter, in_dir, out_dir = converter_setup

    file_to_convert = in_dir / "a.jpg"
    file_to_copy = in_dir / "b.png"
    file_to_convert.touch()
    file_to_copy.touch()

    scan_res = ScanResult()
    scan_res.to_convert = [file_to_convert]
    scan_res.to_copy = [file_to_copy]

    mock_scanner_gen = iter([(in_dir, scan_res)])

    with (
        patch.object(converter, "_convert_worker") as mock_convert,
        patch.object(converter, "_copy_worker") as mock_copy,
    ):
        mock_convert.return_value = ConversionResult(
            file=file_to_convert, in_size=100, out_size=50, status=Status.SUCCESS
        )
        mock_copy.return_value = ConversionResult(
            file=file_to_copy, in_size=200, out_size=200, status=Status.COPY
        )

        mock_cb = MagicMock()
        converter.run(mock_scanner_gen, progress_callback=mock_cb)

        mock_convert.assert_called_with(file_to_convert)
        mock_copy.assert_called_with(file_to_copy)
        assert mock_cb.call_count == 2

        # 验证 CSV 报告生成
        csv_files = list(out_dir.glob("convert_report_*.csv"))
        assert len(csv_files) == 1

        content = csv_files[0].read_text(encoding="utf-8-sig")
        assert "a.jpg" in content
        assert "SUCCESS" in content
        assert "b.png" in content
        assert "COPY" in content


def test_format_size():
    """测试 format_size"""
    from koma.core.converter import format_size

    assert format_size(0) == "0 B"
    assert format_size(500) == "500.00 B"
    assert format_size(1024) == "1.00 KB"
    assert format_size(1024 * 1024 * 1.5) == "1.50 MB"
    assert format_size(1024 * 1024 * 1024 * 1.5) == "1.50 GB"
    assert format_size(1024 * 1024 * 1024 * 1024 * 1.5) == "1.50 TB"
