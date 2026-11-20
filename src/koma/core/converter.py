import concurrent.futures
import csv
import logging
import os
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable, Generator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from koma.config import ConverterConfig
from koma.core.command_generator import CommandGenerator
from koma.core.file_safety import atomic_output, validate_prefix
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

    def _target_path(self, file_path: Path, *, convert: bool) -> Path:
        """为输入生成单层输出路径，并校验自定义扩展名边界。"""
        try:
            rel_path = file_path.relative_to(self.input_dir)
        except ValueError as e:
            raise ValueError(f"输入文件不在输入目录中: {file_path}") from e

        target_folder = self.output_dir / rel_path.parent
        if not convert:
            return target_folder / rel_path.name

        extension = self.cmd_gen.get_ext()
        if (
            not isinstance(extension, str)
            or not extension.startswith(".")
            or len(extension) < 2
            or extension[-1] in ". "
            or any(char in extension for char in "/\\")
        ):
            raise ValueError(f"无效的输出扩展名: {extension!r}")

        target_name = f"{file_path.stem}{extension}"
        try:
            validate_prefix(target_name)
        except ValueError as e:
            raise ValueError(f"无效的输出文件名: {target_name!r}") from e
        return target_folder / target_name

    @staticmethod
    def _path_key(path: Path) -> str:
        """规范化路径，涵盖符号链接及 Windows 大小写别名。"""
        return os.path.normcase(str(path.resolve(strict=False)))

    def _validate_output_root(self) -> None:
        input_root = self.input_dir.resolve(strict=False)
        output_root = self.output_dir.resolve(strict=False)
        input_key = self._path_key(input_root)
        if input_key == self._path_key(output_root) or input_key in {
            self._path_key(parent) for parent in output_root.parents
        }:
            raise ValueError("输出目录不能位于输入目录内")

    def _plan_tasks(
        self,
        scanner_generator: Generator[tuple[Path, ScanResult], None, None],
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> list[tuple[Callable[[Path], ConversionResult], Path]]:
        plan: list[tuple[Callable[[Path], ConversionResult], Path]] = []
        for root, result in scanner_generator:
            if progress_callback:
                progress_callback(0, 0, f"正在分析目录: {root.name}")
            plan.extend((self._copy_worker, p) for p in result.to_copy)
            plan.extend((self._convert_worker, p) for p in result.to_convert)

        source_keys = {self._path_key(path) for _, path in plan}
        target_keys: dict[str, Path] = {}
        for worker, path in plan:
            target = self._target_path(path, convert=worker == self._convert_worker)
            key = self._path_key(target)
            if key in source_keys:
                raise ValueError(f"输出目标与输入文件冲突: {target}")
            if key in target_keys:
                raise ValueError(
                    f"多个输入映射到同一输出文件: {target_keys[key]} 和 {path}"
                )
            target_keys[key] = path
        return plan

    def run(
        self,
        scanner_generator: Generator[tuple[Path, ScanResult], None, None],
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> list[ConversionResult]:
        workers = self.config.actual_workers
        logger.info(f"🚀 转换器启动 (并发: {workers})")

        all_results: list[ConversionResult] = []
        global_start = time.monotonic()

        # 在途任务上限：否则几万张图会同时产生同样数量的 Future 与排队任务
        window = max(workers * 4, 16)

        try:
            self._validate_output_root()
            # 完整扫描并预检所有输出，发现别名/碰撞时不启动任何写任务。
            plan = self._plan_tasks(scanner_generator, progress_callback)
            total_tasks = len(plan)

            # 阶段 2：有界提交，边跑边回收
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                pending: set[concurrent.futures.Future] = set()

                def drain_one() -> None:
                    """阻塞到至少有一个任务完成，并回收其结果"""
                    if not pending:
                        return

                    done, _ = concurrent.futures.wait(
                        pending, return_when=concurrent.futures.FIRST_COMPLETED
                    )
                    for future in done:
                        pending.discard(future)
                        res = future.result()
                        all_results.append(res)

                        if progress_callback:
                            progress_callback(
                                len(all_results),
                                total_tasks,
                                f"处理中 ({len(all_results)}/{total_tasks}): {res.file}",
                            )

                for worker, path in plan:
                    pending.add(executor.submit(worker, path))
                    while len(pending) >= window:
                        drain_one()

                while pending:
                    drain_one()
        finally:
            if progress_callback:
                progress_callback(1, 1, "任务全部完成")

        self._generate_report(all_results, global_start)
        return all_results

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

                target_file = self._target_path(file_path, convert=True)

                # 使用 ImageProcessor 分析图片属性 (动图/灰度)
                img_info = self.image_processor.analyze(file_path)

                # 转换到暂存文件，失败时不影响已有结果。
                with atomic_output(target_file) as staged_file:
                    cmd = self.cmd_gen.generate(
                        file_path,
                        staged_file,
                        img_info.is_animated,
                        img_info.is_grayscale,
                    )

                    subprocess.run(
                        cmd,
                        check=True,
                        capture_output=True,
                        startupinfo=self.startupinfo,
                    )

                    if not staged_file.is_file():
                        raise FileNotFoundError("输出文件未生成")
                    out_size = staged_file.stat().st_size
                    if out_size == 0:
                        raise ValueError("转换输出为空")
                    res.out_size = out_size

                # 如果转换后体积反而变大，标记为 BIGGER
                res.status = (
                    Status.BIGGER if res.out_size > res.in_size else Status.SUCCESS
                )
                self._log_result(res)
                return res

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
                target_path = self._target_path(file_path, convert=False)
                with atomic_output(target_path) as staged_path:
                    shutil.copy2(file_path, staged_path)
                    if not staged_path.is_file():
                        raise FileNotFoundError("复制后文件未生成")
                    res.out_size = staged_path.stat().st_size

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
        failed_in = 0
        csv_rows = []
        failures = []

        for r in results:
            if r.status == Status.ERROR:
                failures.append(r)
                failed_in += r.in_size
            else:
                total_in += r.in_size
                total_out += r.out_size

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
        if failed_in:
            logger.info(f"🚫 未处理体积: {format_size(failed_in)}")
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

        csv_path = self.output_dir / (
            f"convert_report_{int(time.time())}_{uuid.uuid4().hex[:8]}.csv"
        )
        try:
            with (
                atomic_output(csv_path) as staged_report,
                open(staged_report, mode="w", encoding="utf-8-sig", newline="") as f,
            ):
                writer = csv.writer(f)
                writer.writerow(["文件名", "原大小", "新大小", "比例%", "状态", "错误"])
                writer.writerows(csv_rows)

            logger.info("-" * 100)
            logger.info(f"📊 详细 CSV 报告已生成: {csv_path}")
        except Exception as e:
            logger.error(f"无法生成报告: {e}")
