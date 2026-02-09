import concurrent.futures
import csv
import logging
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Generator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from koma.config import ConverterConfig
from koma.core.command_generator import CommandGenerator
from koma.core.image_processor import ImageProcessor
from koma.core.scanner import ScanResult

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


class Status(Enum):
    PENDING = "⏳ PENDING"
    SUCCESS = "✅ SUCCESS"
    ERROR = "❌ ERROR"
    BIGGER = "⚠️ BIGGER"
    COPY = "⏩ COPY"


def format_size(size_bytes: int | float) -> str:
    if size_bytes == 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"


@dataclass
class ConversionResult:
    """转换结果数据类"""

    file: Path
    in_size: int = 0
    out_size: int = 0
    status: Status = Status.PENDING
    error: str = ""

    @property
    def ratio(self) -> float:
        if self.in_size > 0 and self.out_size > 0:
            return round(((self.out_size - self.in_size) / self.in_size) * 100, 2)
        return 0.0

    @property
    def in_size_fmt(self) -> str:
        return format_size(self.in_size)

    @property
    def out_size_fmt(self) -> str:
        return format_size(self.out_size)

    def __str__(self) -> str:
        name = f"{self.file.parent.name}/{self.file.name}"
        limit = 50
        if len(name) > limit:
            remain = limit - 3
            keep_front = 20
            keep_end = remain - keep_front
            display_name = f"{name[:keep_front]}...{name[-keep_end:]}"
        else:
            display_name = name

        col_file = f"{display_name:<50}"
        col_in = f"{self.in_size_fmt:>10}"
        col_status = f"{self.status.value:<10}"

        if self.status == Status.ERROR:
            col_out = f"{'-':>10}"
            col_ratio = f"{'-':>10}"
        else:
            col_out = f"{self.out_size_fmt:>10}"
            col_ratio = f"{self.ratio:>+9.1f}%"

        return f"{col_file} | {col_in} | {col_out} | {col_ratio} | {col_status}"


class Converter:
    def __init__(
        self,
        input_dir: Path,
        output_dir: Path,
        config: ConverterConfig,
        image_processor: ImageProcessor,
    ):
        """
        初始化转换器

        Args:
            input_dir: 输入根目录
            output_dir: 输出根目录
            config: 转换配置对象
            image_processor: 图像处理器
        """
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.config = config
        self.image_processor = image_processor

        self.cmd_gen = CommandGenerator(
            self.config.format,
            self.config.quality,
            self.config.lossless,
            self.config.custom_params,
            self.config.custom_ext,
        )

        self.startupinfo = None
        if os.name == "nt":
            self.startupinfo = subprocess.STARTUPINFO()
            self.startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    def run(
        self,
        scanner_generator: Generator[tuple[Path, ScanResult], None, None],
        progress_callback: Callable[[int, int, str], None] | None = None,
    ):
        workers = self.config.actual_workers
        logger.info(f"🚀 转换器启动 (并发: {workers})")

        all_results = []
        global_start = time.monotonic()
        tasks = []

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                for root, result in scanner_generator:
                    if progress_callback:
                        progress_callback(0, 0, f"正在分析目录: {root.name}")

                    for p in result.to_copy:
                        tasks.append(executor.submit(self._copy_worker, p))
                    for p in result.to_convert:
                        tasks.append(executor.submit(self._convert_worker, p))

                total_tasks = len(tasks)

                for completed, future in enumerate(
                    concurrent.futures.as_completed(tasks), start=1
                ):
                    res = future.result()
                    all_results.append(res)

                    if progress_callback:
                        progress_callback(
                            completed,
                            total_tasks,
                            f"处理中 ({completed}/{total_tasks}): {res.file.name}",
                        )
        finally:
            if progress_callback:
                progress_callback(1, 1, "任务全部完成")

        self._generate_report(all_results, global_start)

    def _log_result(self, res: ConversionResult):
        if res.status == Status.ERROR:
            logger.error(res)
            # 额外打印一行错误详情
            short_msg = res.error.strip().split("\n")[0][:100]
            logger.error(f"  └── ❌ {short_msg}...")
        else:
            logger.info(res)

    def _convert_worker(self, file_path: Path) -> ConversionResult:
        res = ConversionResult(file=file_path)

        for attempt in range(MAX_RETRIES):
            try:
                if not file_path.exists():
                    raise FileNotFoundError("源文件缺失")

                res.error = ""
                res.in_size = file_path.stat().st_size

                # 计算相对路径，保持目录结构
                rel_path = file_path.relative_to(self.input_dir)
                target_folder = self.output_dir / rel_path.parent
                target_folder.mkdir(parents=True, exist_ok=True)

                # 生成目标文件名
                target_file = target_folder / (file_path.stem + self.cmd_gen.get_ext())

                # 使用 ImageProcessor 分析图片属性 (动图/灰度)
                img_info = self.image_processor.analyze(file_path)

                # 生成 FFmpeg 命令行
                cmd = self.cmd_gen.generate(
                    file_path, target_file, img_info.is_animated, img_info.is_grayscale
                )

                subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    startupinfo=self.startupinfo,
                )

                if target_file.exists():
                    res.out_size = target_file.stat().st_size
                    # 如果转换后体积反而变大，标记为 BIGGER
                    res.status = (
                        Status.BIGGER if res.out_size > res.in_size else Status.SUCCESS
                    )
                    self._log_result(res)
                    return res

                else:
                    raise FileNotFoundError("输出文件未生成")

            except Exception as e:
                res.error = str(e)
                if attempt < MAX_RETRIES - 1:
                    logger.warning(
                        f"⚠️ 转换失败，正在重试 ({attempt + 1}/{MAX_RETRIES}): {file_path}"
                    )
                    time.sleep(1)
                else:
                    res.status = Status.ERROR
                    self._log_result(res)

        return res

    def _copy_worker(self, file_path: Path) -> ConversionResult:
        res = ConversionResult(file=file_path)

        for attempt in range(MAX_RETRIES):
            try:
                res.error = ""

                if not file_path.exists():
                    raise FileNotFoundError("源文件缺失")

                res.in_size = file_path.stat().st_size
                rel_path = file_path.relative_to(self.input_dir)
                target_path = self.output_dir / rel_path
                target_path.parent.mkdir(parents=True, exist_ok=True)

                shutil.copy2(file_path, target_path)

                res.out_size = target_path.stat().st_size
                res.status = Status.COPY
                self._log_result(res)

                return res

            except Exception as e:
                res.error = str(e)
                if attempt < MAX_RETRIES - 1:
                    logger.warning(
                        f"⚠️ 复制失败，正在重试 ({attempt + 1}/{MAX_RETRIES}): {file_path}"
                    )
                    time.sleep(1)
                else:
                    res.status = Status.ERROR
                    self._log_result(res)

        return res

    def _generate_report(self, results: list[ConversionResult], start_time: float):
        if not results:
            return

        total_in = 0
        total_out = 0
        csv_rows = []
        failures = []

        for r in results:
            total_in += r.in_size
            total_out += r.out_size

            if r.error:
                failures.append(r)

            csv_rows.append(
                [
                    str(r.file),
                    r.in_size_fmt,
                    r.out_size_fmt,
                    f"{r.ratio:.2f}%" if r.ratio else "-",
                    r.status.value,
                    r.error,
                ]
            )

        total_time = time.monotonic() - start_time
        saved_size = total_in - total_out
        saved_ratio = (saved_size / total_in * 100) if total_in > 0 else 0

        logger.info("=" * 100)
        logger.info(
            f"🏁 任务完成！总计: {len(results)} | 成功: {len(results) - len(failures)} | 失败: {len(failures)}"
        )
        logger.info(f"⏱️ 总耗时: {total_time:.1f}s")
        logger.info(f"📈 总原体积: {format_size(total_in)}")
        logger.info(f"📉 总新体积: {format_size(total_out)}")
        if saved_size >= 0:
            logger.info(f"♻️ 节省空间: {format_size(saved_size)} (-{saved_ratio:.1f}%)")
        else:
            logger.info(
                f"⚠️ 体积增加: {format_size(abs(saved_size))} (+{abs(saved_ratio):.1f}%)"
            )

        if failures:
            logger.info("-" * 100)
            logger.warning(f"⚠️ 发现 {len(failures)} 个文件处理失败:")
            for i, f in enumerate(failures, 1):
                if i > 20:
                    logger.warning(
                        f"  ... 以及其他 {len(failures) - 20} 个错误 (详情请见 CSV 报告)"
                    )
                    break
                logger.warning(f"❌ [{i}] {f.file}: {f.error}")

        csv_path = self.output_dir / f"convert_report_{int(time.time())}.csv"
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            with open(csv_path, mode="w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["文件名", "原大小", "新大小", "比例%", "状态", "错误"])
                writer.writerows(csv_rows)

            logger.info("-" * 100)
            logger.info(f"📊 详细 CSV 报告已生成: {csv_path}")
        except Exception as e:
            logger.error(f"无法生成报告: {e}")
