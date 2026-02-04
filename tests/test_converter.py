from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from koma.core.converter import ConversionResult, Converter, Status
from koma.core.scanner import ScanResult


@pytest.fixture
def converter_setup(tmp_path, converter_config, mock_image_processor):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    # 注入配置
    converter_config.format = "avif (svt)"
    converter_config.quality = 75

    converter = Converter(input_dir, output_dir, converter_config, mock_image_processor)
    return converter, input_dir, output_dir


@pytest.fixture
def mock_deps():
    with (
        patch("koma.core.converter.CommandGenerator") as MockCmdGen,
        patch("subprocess.run") as mock_run,
    ):
        mock_instance = MockCmdGen.return_value
        mock_instance.generate.return_value = ["ffmpeg", "-i", "fake"]
        mock_instance.get_ext.return_value = ".avif"
        yield mock_instance, mock_run


def test_convert_worker_success(converter_setup, mock_deps):
    """测试转换成功流程 (Status.SUCCESS)"""
    converter, in_dir, out_dir = converter_setup
    _, mock_run = mock_deps

    src = in_dir / "test.jpg"
    src.write_bytes(b"content" * 100)

    def side_effect(*args, **kwargs):
        (out_dir / "test.avif").parent.mkdir(parents=True, exist_ok=True)
        (out_dir / "test.avif").write_bytes(b"small")
        return MagicMock(returncode=0)

    mock_run.side_effect = side_effect

    res = converter._convert_worker(src)
    assert res.status == Status.SUCCESS
    assert res.in_size == 700
    assert res.out_size == 5


def test_convert_worker_bigger(converter_setup, mock_deps):
    """测试转换后体积变大 (Status.BIGGER)"""
    converter, in_dir, out_dir = converter_setup
    _, mock_run = mock_deps

    src = in_dir / "tiny.jpg"
    src.write_bytes(b"a")  # 1 byte

    def side_effect(*args, **kwargs):
        (out_dir / "tiny.avif").parent.mkdir(parents=True, exist_ok=True)
        (out_dir / "tiny.avif").write_bytes(b"very large content")
        return MagicMock()

    mock_run.side_effect = side_effect

    res = converter._convert_worker(src)
    assert res.status == Status.BIGGER


@patch("koma.core.converter.time.sleep")
def test_convert_worker_retry_success(mock_sleep, converter_setup, mock_deps):
    """测试转换遇到临时错误，重试后成功"""
    converter, in_dir, out_dir = converter_setup
    _, mock_run = mock_deps

    src = in_dir / "retry.jpg"
    src.write_bytes(b"content 0123456789abcdef")

    # 模拟：第1次报错，第2次成功
    def side_effect(*args, **kwargs):
        if mock_run.call_count == 1:
            raise Exception("FFmpeg temporary fail")
        (out_dir / "retry.avif").parent.mkdir(parents=True, exist_ok=True)
        (out_dir / "retry.avif").write_bytes(b"converted data")
        return MagicMock(returncode=0)

    mock_run.side_effect = side_effect

    res = converter._convert_worker(src)
    assert res.status == Status.SUCCESS
    assert mock_run.call_count == 2
    assert mock_sleep.called


@patch("koma.core.converter.time.sleep")
def test_convert_worker_fail_max_retries(mock_sleep, converter_setup, mock_deps):
    """测试重试次数耗尽仍然失败 (Status.ERROR)"""
    converter, in_dir, _ = converter_setup
    _, mock_run = mock_deps

    src = in_dir / "corrupt.jpg"
    src.touch()
    mock_run.side_effect = Exception("Persistent FFmpeg crash")

    res = converter._convert_worker(src)
    assert res.status == Status.ERROR
    assert mock_run.call_count == 3


@patch("koma.core.converter.time.sleep")
def test_copy_worker_retry_success(mock_sleep, converter_setup):
    """测试复制操作的重试逻辑"""
    converter, in_dir, out_dir = converter_setup

    src = in_dir / "retry_copy.png"
    src.write_bytes(b"data")

    with patch("shutil.copy2") as mock_copy:

        def side_effect(src, dst):
            if mock_copy.call_count == 1:
                raise OSError("File locked")
            Path(dst).write_bytes(b"data")

        mock_copy.side_effect = side_effect

        res = converter._copy_worker(src)
        assert res.status == Status.COPY
        assert mock_copy.call_count == 2


def test_convert_worker_missing_source(converter_setup, mock_deps):
    """测试源文件缺失 (会被重试机制捕获，最终返回 ERROR)"""
    converter, in_dir, _ = converter_setup
    with patch("koma.core.converter.time.sleep"):
        res = converter._convert_worker(in_dir / "ghost.jpg")
    assert res.status == Status.ERROR
    assert "源文件缺失" in str(res.error)


def test_run_loop_and_report(converter_setup):
    """测试主循环"""
    converter, in_dir, out_dir = converter_setup

    file_to_convert = in_dir / "a.jpg"
    file_to_convert.touch()
    file_to_copy = in_dir / "b.png"
    file_to_copy.touch()

    scan_res = ScanResult()
    scan_res.to_convert = [file_to_convert]
    scan_res.to_copy = [file_to_copy]

    with (
        patch.object(converter, "_convert_worker") as mock_convert,
        patch.object(converter, "_copy_worker") as mock_copy,
    ):
        mock_convert.return_value = ConversionResult(
            file=file_to_convert, status=Status.SUCCESS
        )
        mock_copy.return_value = ConversionResult(file=file_to_copy, status=Status.COPY)

        mock_cb = MagicMock()
        converter.run(iter([(in_dir, scan_res)]), progress_callback=mock_cb)

        assert mock_convert.call_count == 1
        assert mock_copy.call_count == 1
        assert mock_cb.call_count == 4

        # 验证报告
        csv_files = list(out_dir.glob("convert_report_*.csv"))
        assert len(csv_files) == 1
