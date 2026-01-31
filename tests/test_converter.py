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


def test_convert_worker_fail_subprocess(converter_setup, mock_deps):
    """测试 FFmpeg 报错 (Status.ERROR)"""
    converter, in_dir, _ = converter_setup
    _, mock_run, _ = mock_deps

    src_file = in_dir / "corrupt.jpg"
    src_file.touch()

    mock_run.side_effect = Exception("FFmpeg crashed")

    res = converter._convert_worker(src_file)
    assert res.status == Status.ERROR
    assert "FFmpeg crashed" in res.error


def test_convert_worker_missing_source(converter_setup, mock_deps):
    """测试源文件缺失"""
    converter, in_dir, _ = converter_setup

    res = converter._convert_worker(in_dir / "ghost.jpg")
    assert res.status == Status.ERROR
    assert "源文件缺失" in res.error


def test_copy_worker(converter_setup):
    """测试直接复制逻辑"""
    converter, in_dir, out_dir = converter_setup

    sub_dir = in_dir / "folder"
    sub_dir.mkdir()
    src_file = sub_dir / "keep.png"
    src_file.write_bytes(b"keep me")

    res = converter._copy_worker(src_file)

    assert res.status == Status.COPY
    expected_out = out_dir / "folder" / "keep.png"
    assert expected_out.exists()
    assert expected_out.read_bytes() == b"keep me"


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
        assert mock_cb.call_count == 2  # 两个任务，回调两次

        # 验证 CSV 报告生成
        csv_files = list(out_dir.glob("report_*.csv"))
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
