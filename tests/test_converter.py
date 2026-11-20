import concurrent.futures
import logging
import os
import time
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
def mock_deps(converter_setup):
    converter, _, _ = converter_setup
    with (
        patch("koma.core.converter.subprocess.run") as mock_run,
        patch.object(
            converter.cmd_gen,
            "generate",
            side_effect=lambda _src, dst, *_args: ["ffmpeg", str(dst)],
        ),
        patch.object(converter.cmd_gen, "get_ext", return_value=".avif"),
    ):
        yield converter.cmd_gen, mock_run


def test_convert_worker_success(converter_setup, mock_deps):
    """测试转换成功流程 (Status.SUCCESS)"""
    converter, in_dir, _ = converter_setup
    _, mock_run = mock_deps

    src = in_dir / "test.jpg"
    src.write_bytes(b"content" * 100)

    def side_effect(*args, **kwargs):
        staged = Path(mock_run.call_args.args[0][-1])
        staged.write_bytes(b"small")
        return MagicMock(returncode=0)

    mock_run.side_effect = side_effect

    res = converter._convert_worker(src)
    assert res.status == Status.SUCCESS
    assert res.in_size == 700
    assert res.out_size == 5


def test_convert_worker_bigger(converter_setup, mock_deps):
    """测试转换后体积变大 (Status.BIGGER)"""
    converter, in_dir, _ = converter_setup
    _, mock_run = mock_deps

    src = in_dir / "tiny.jpg"
    src.write_bytes(b"a")  # 1 byte

    def side_effect(*args, **kwargs):
        staged = Path(mock_run.call_args.args[0][-1])
        staged.write_bytes(b"very large content")
        return MagicMock()

    mock_run.side_effect = side_effect

    res = converter._convert_worker(src)
    assert res.status == Status.BIGGER


@patch("koma.core.converter.time.sleep")
def test_convert_worker_retry_success(mock_sleep, converter_setup, mock_deps):
    """测试转换遇到临时错误，重试后成功"""
    converter, in_dir, _ = converter_setup
    _, mock_run = mock_deps

    src = in_dir / "retry.jpg"
    src.write_bytes(b"content 0123456789abcdef")

    # 模拟：第1次报错，第2次成功
    def side_effect(*args, **kwargs):
        if mock_run.call_count == 1:
            raise Exception("FFmpeg temporary fail")
        staged = Path(mock_run.call_args.args[0][-1])
        staged.write_bytes(b"converted data")
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
    converter, in_dir, _ = converter_setup

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


def test_report_excludes_failed_files(converter_setup, caplog):
    """失败文件的原体积不能计入「节省空间」，否则压缩率虚高"""
    converter, in_dir, _ = converter_setup

    ok = ConversionResult(
        file=in_dir / "ok.jpg",
        in_size=1000,
        out_size=100,
        status=Status.SUCCESS,
    )
    failed = ConversionResult(
        file=in_dir / "failed.jpg",
        in_size=5000,
        out_size=0,
        status=Status.ERROR,
        error="ffmpeg 崩溃",
    )

    with caplog.at_level(logging.INFO, logger="koma.core.converter"):
        converter._generate_report([ok, failed], time.monotonic())

    # 总原体积只统计成功的那个文件
    assert "1000.00 B" in caplog.text
    # 失败文件的体积单独列出（5000 B -> 4.88 KB）
    assert "未处理体积" in caplog.text
    assert "4.88 KB" in caplog.text
    # 若把失败体积算进去，总原体积会变成 6000 B (5.86 KB) —— 不允许出现
    assert "5.86 KB" not in caplog.text
    # 节省空间 = 1000 - 100
    assert "900.00 B" in caplog.text


def test_run_scan_finishes_before_submitting(converter_setup):
    """
    必须先把扫描跑完再提交任务。

    回归背景：旧实现边扫边 submit，几万张图会在扫描阶段就把全部任务
    塞进线程池队列，内存无上限。
    """
    converter, in_dir, _ = converter_setup

    scan_done = False
    observed = []

    def generator():
        nonlocal scan_done
        for i in range(3):
            res = ScanResult()
            res.to_convert = [in_dir / f"{i}.jpg"]
            yield in_dir, res
            # 给"边扫边跑"的旧实现留出时间窗：它会在这里就把任务跑起来
            time.sleep(0.05)
        scan_done = True

    def worker(path):
        observed.append(scan_done)
        return ConversionResult(file=path, status=Status.SUCCESS)

    with patch.object(converter, "_convert_worker", side_effect=worker):
        converter.run(generator())

    assert observed == [True, True, True]


class _TrackingExecutor(concurrent.futures.ThreadPoolExecutor):
    """记录「已提交但未完成」的峰值，用于验证在途任务数有上限"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pending = 0
        self.peak = 0

    def submit(self, fn, /, *args, **kwargs):
        self.pending += 1
        self.peak = max(self.peak, self.pending)
        future = super().submit(fn, *args, **kwargs)
        future.add_done_callback(lambda _f: setattr(self, "pending", self.pending - 1))
        return future


def test_run_bounds_in_flight_tasks(converter_setup):
    """
    在途任务数必须有上限，不能把整批任务一次性 submit。

    回归背景：旧实现先 submit 完全部任务再 as_completed，
    几万张图会同时产生同样数量的 Future 与排队任务。
    """
    converter, in_dir, _ = converter_setup
    converter.config.max_workers = 1  # 窗口 = max(1*4, 16) = 16

    total = 60
    scan_res = ScanResult()
    for i in range(total):
        p = in_dir / f"{i:03d}.jpg"
        p.touch()
        scan_res.to_convert.append(p)

    def worker(path):
        return ConversionResult(file=path, status=Status.SUCCESS)

    created = []

    def make_executor(*args, **kwargs):
        executor = _TrackingExecutor(*args, **kwargs)
        created.append(executor)
        return executor

    with (
        patch.object(converter, "_convert_worker", side_effect=worker),
        patch(
            "koma.core.converter.concurrent.futures.ThreadPoolExecutor",
            side_effect=make_executor,
        ),
    ):
        converter.run(iter([(in_dir, scan_res)]))

    assert len(created) == 1
    window = max(converter.config.actual_workers * 4, 16)
    # 旧实现这里会是 total(60)
    assert created[0].peak <= window, (
        f"在途任务峰值 {created[0].peak} 超过窗口 {window}"
    )


def test_run_rejects_copy_convert_target_collision(converter_setup, mock_deps):
    converter, in_dir, out_dir = converter_setup
    copied = in_dir / "chapter.avif"
    converted = in_dir / "chapter.jpg"
    copied.write_bytes(b"copy input")
    converted.write_bytes(b"convert input")
    old_target = out_dir / "chapter.avif"
    old_target.write_bytes(b"previous result")

    scan_result = ScanResult()
    scan_result.to_copy.append(copied)
    scan_result.to_convert.append(converted)

    with (
        patch.object(converter, "_copy_worker") as copy_worker,
        patch.object(converter, "_convert_worker") as convert_worker,
        pytest.raises(ValueError, match="同一输出文件"),
    ):
        converter.run(iter([(in_dir, scan_result)]))

    copy_worker.assert_not_called()
    convert_worker.assert_not_called()
    assert old_target.read_bytes() == b"previous result"


def test_run_rejects_nested_output_root(converter_setup):
    converter, in_dir, _ = converter_setup
    nested_output = in_dir / "generated"
    converter.output_dir = nested_output

    with pytest.raises(ValueError, match="输出目录不能位于输入目录内"):
        converter.run(iter([]))

    assert not nested_output.exists()


def test_run_rejects_nested_custom_extension(converter_setup, monkeypatch):
    converter, in_dir, out_dir = converter_setup
    monkeypatch.setattr(converter.cmd_gen, "get_ext", lambda: "/../escape.avif")
    src = in_dir / "page.jpg"
    src.write_bytes(b"page")
    scan_result = ScanResult()
    scan_result.to_convert.append(src)

    with pytest.raises(ValueError, match="无效的输出扩展名"):
        converter.run(iter([(in_dir, scan_result)]))

    assert list(out_dir.iterdir()) == []


@patch("koma.core.converter.time.sleep")
def test_convert_failure_keeps_previous_target(mock_sleep, converter_setup, mock_deps):
    converter, in_dir, out_dir = converter_setup
    _, mock_run = mock_deps
    src = in_dir / "page.jpg"
    src.write_bytes(b"original")
    target = out_dir / "page.avif"
    target.write_bytes(b"old result")

    def fail_after_partial_output(*args, **kwargs):
        staged = Path(mock_run.call_args.args[0][-1])
        staged.write_bytes(b"partial result")
        raise OSError("编码失败")

    mock_run.side_effect = fail_after_partial_output
    result = converter._convert_worker(src)

    assert result.status == Status.ERROR
    assert target.read_bytes() == b"old result"


@patch("koma.core.converter.time.sleep")
def test_convert_empty_output_keeps_previous_target(
    mock_sleep, converter_setup, mock_deps
):
    converter, in_dir, out_dir = converter_setup
    _, mock_run = mock_deps
    src = in_dir / "page.jpg"
    src.write_bytes(b"original")
    target = out_dir / "page.avif"
    target.write_bytes(b"old result")

    def empty_output(*args, **kwargs):
        Path(mock_run.call_args.args[0][-1]).touch()

    mock_run.side_effect = empty_output
    result = converter._convert_worker(src)

    assert result.status == Status.ERROR
    assert "为空" in result.error
    assert target.read_bytes() == b"old result"


@patch("koma.core.converter.time.sleep")
def test_copy_failure_keeps_previous_target(mock_sleep, converter_setup):
    converter, in_dir, out_dir = converter_setup
    src = in_dir / "page.png"
    src.write_bytes(b"new result")
    target = out_dir / "page.png"
    target.write_bytes(b"old result")

    with patch("koma.core.converter.shutil.copy2", side_effect=OSError("复制失败")):
        result = converter._copy_worker(src)

    assert result.status == Status.ERROR
    assert target.read_bytes() == b"old result"


def test_copy_preserves_metadata_and_run_returns_results(converter_setup):
    converter, in_dir, out_dir = converter_setup
    src = in_dir / "page.png"
    src.write_bytes(b"copied")
    os.utime(src, (1_700_000_000, 1_700_000_000))
    scan_result = ScanResult()
    scan_result.to_copy.append(src)

    results = converter.run(iter([(in_dir, scan_result)]))

    target = out_dir / "page.png"
    assert [result.status for result in results] == [Status.COPY]
    assert target.read_bytes() == b"copied"
    assert target.stat().st_mtime == src.stat().st_mtime


@pytest.mark.skipif(os.name != "nt", reason="仅 Windows 路径大小写不敏感")
def test_run_rejects_case_alias_targets(converter_setup):
    converter, in_dir, out_dir = converter_setup
    upper = in_dir / "Page.jpg"
    lower = in_dir / "page.jpg"
    upper.write_bytes(b"upper")
    lower.write_bytes(b"lower")
    scan_result = ScanResult()
    scan_result.to_convert.extend([upper, lower])

    with pytest.raises(ValueError, match="同一输出文件"):
        converter.run(iter([(in_dir, scan_result)]))

    assert list(out_dir.iterdir()) == []


def test_generate_report_preserves_previous_timestamp_report(
    converter_setup, monkeypatch
):
    """新报告不得覆盖旧版时间戳命名的现有 CSV。"""
    converter, in_dir, out_dir = converter_setup
    previous = out_dir / "convert_report_123.csv"
    previous.write_bytes(b"keep previous report")
    result = ConversionResult(
        file=in_dir / "page.jpg", status=Status.SUCCESS, in_size=10, out_size=5
    )
    monkeypatch.setattr("koma.core.converter.time.time", lambda: 123)

    converter._generate_report([result], time.monotonic())

    reports = list(out_dir.glob("convert_report_123_*.csv"))
    assert len(reports) == 1
    assert previous.read_bytes() == b"keep previous report"
    assert "page.jpg" in reports[0].read_text(encoding="utf-8-sig")
