import csv
import logging
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from natsort import natsorted
from send2trash import send2trash

from koma.config import ExtensionsConfig
from koma.core.archive import ArchiveHandler
from koma.core.file_safety import move_no_replace, validate_prefix
from koma.core.image_processor import ImageProcessor
from koma.core.scanner import Scanner

logger = logging.getLogger(__name__)

KOMA_TMP_PREFIX = "koma_tmp_"


class RenameBatchError(RuntimeError):
    """批次存在失败；保留已提交操作的映射，供报告和界面展示。"""

    def __init__(self, failures: list[str], rows: list):
        self.failures = failures
        self.rows = rows
        super().__init__("重命名未全部完成：" + "；".join(failures))


class Renamer:
    def __init__(
        self,
        target_dir: Path,
        ext_config: ExtensionsConfig,
        image_processor: ImageProcessor,
    ):
        """
        初始化重命名器

        Args:
            target_dir: 目标文件夹
            ext_config: 扩展名配置
            image_processor: 图片处理器
        """
        self.target_dir = Path(target_dir)
        self.ext_config = ext_config
        self.image_processor = image_processor
        self.archive_handler = ArchiveHandler(self.ext_config)

    def run(
        self,
        options: dict[str, Any] | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ):
        logger.info(f"⚒️ 开始重命名整理: {self.target_dir}")

        options = options or {}
        export_csv = options.get("export_csv", False)
        prefix = options.get("prefix", "")
        start_index = options.get("start_index", 0)
        enable_archive_scan = options.get("enable_archive_scan", False)
        pack_format = options.get("pack_format", "zip")
        validate_prefix(prefix)
        if (
            isinstance(start_index, bool)
            or not isinstance(start_index, int)
            or start_index < 0
        ):
            raise ValueError("起始序号必须是非负整数")
        if pack_format not in {"zip", "cbz", "7z", "cb7"}:
            raise ValueError("不支持的归档格式")

        scan_opts = options.copy()
        scan_opts["enable_archive_scan"] = False

        scanner = Scanner(
            input_dir=self.target_dir,
            ext_config=self.ext_config,
            image_processor=self.image_processor,
        )

        all_csv_rows = []
        failures = []

        def record_failure(error: Exception) -> None:
            logger.error(f"重命名任务失败: {error}")
            if isinstance(error, RenameBatchError):
                all_csv_rows.extend(error.rows)
                failures.extend(error.failures)
            else:
                failures.append(str(error))

        try:
            for root, result in scanner.run(options=scan_opts):
                all_images = result.to_convert + result.to_copy
                if all_images:
                    try:
                        all_csv_rows.extend(
                            self._rename_files_in_dir(
                                root,
                                all_images,
                                True,
                                prefix,
                                start_index,
                                progress_callback,
                            )
                        )
                    except Exception as e:
                        record_failure(e)

                if enable_archive_scan:
                    for arc_path in result.archives:
                        try:
                            all_csv_rows.extend(
                                self._process_archive(
                                    arc_path,
                                    pack_format,
                                    prefix,
                                    start_index,
                                    progress_callback,
                                )
                            )
                        except Exception as e:
                            record_failure(e)
        except Exception as e:
            record_failure(e)

        if export_csv and all_csv_rows:
            try:
                self._write_csv_report(all_csv_rows)
            except Exception as e:
                record_failure(e)
        if failures:
            raise RenameBatchError(failures, all_csv_rows)
        if progress_callback:
            progress_callback(1, 1, "重命名任务完成")
        logger.info("🎉 所有重命名任务完成！")

    def _process_archive(
        self,
        archive_path: Path,
        pack_format: str,
        prefix: str = "",
        start_index: int = 0,
        progress_callback: Callable | None = None,
    ) -> list:
        """处理单个压缩包；发布成功前不报告映射、不删除原包。"""
        validate_prefix(prefix)
        if pack_format not in {"zip", "cbz", "7z", "cb7"}:
            raise ValueError("不支持的归档格式")
        if progress_callback:
            progress_callback(0, 0, f"正在处理压缩包: {archive_path.name}")

        published_rows = []
        try:
            with tempfile.TemporaryDirectory(prefix="koma_rename_") as temp_dir:
                content_root = self.archive_handler.extract(
                    archive_path, Path(temp_dir)
                )
                images = [
                    path
                    for path in self.archive_handler._iter_files(content_root)
                    if path.suffix.lower() in self.ext_config.all_supported_img
                ]
                try:
                    changed_rows = self._rename_files_in_dir(
                        content_root, images, True, prefix, start_index, None
                    )
                except RenameBatchError as e:
                    # 解压副本的未提交修改不能进入用户文件映射报告。
                    raise RuntimeError(
                        f"压缩包内重命名失败: {archive_path}: {e}"
                    ) from e
                if not changed_rows:
                    logger.info(f"⏩ 压缩包内无需重命名，跳过: {archive_path}")
                    return []

                # 独占目录位于目标文件系统，避免跨卷复制和固定临时名冲突。
                with tempfile.TemporaryDirectory(
                    prefix=KOMA_TMP_PREFIX, dir=archive_path.parent
                ) as pack_dir:
                    staged = Path(pack_dir) / f"{archive_path.stem}.{pack_format}"
                    if not self.archive_handler.pack(
                        content_root, staged, fmt=pack_format, level="normal"
                    ):
                        raise RuntimeError(f"重打包失败: {archive_path}")
                    final_path = archive_path.with_suffix(f".{pack_format}")
                    attempt = 0
                    while True:
                        try:
                            move_no_replace(staged, final_path)
                            break
                        except FileExistsError:
                            attempt += 1
                            final_path = archive_path.with_name(
                                f"{archive_path.stem}_{uuid.uuid4().hex}_{attempt}"
                                f".{pack_format}"
                            )
                    for row in changed_rows:
                        row[0] = f"📦 {archive_path} -> {final_path}"
                    published_rows = changed_rows

            logger.info(f"✅ 压缩包处理完成: {final_path.name}")
            send2trash(str(archive_path))
        except Exception as e:
            if published_rows:
                raise RenameBatchError(
                    [f"新包已生成，但后续清理失败 {archive_path}: {e}"],
                    published_rows,
                ) from e
            raise
        return published_rows

    def _rename_files_in_dir(
        self,
        root_path: Path,
        files: list[Path],
        return_csv: bool = False,
        prefix: str = "",
        start_index: int = 0,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> list:
        """核心重命名逻辑"""
        validate_prefix(prefix)
        if (
            isinstance(start_index, bool)
            or not isinstance(start_index, int)
            or start_index < 0
        ):
            raise ValueError("起始序号必须是非负整数")
        if not files:
            return []

        folder_csv_rows = []

        all_images = natsorted(files)

        if len(all_images) == 1 and all_images[0].stem.lower() == "cover":
            logger.info(f"⏩ {root_path.name} 仅含封面图，跳过")
            return []

        # 封面置顶
        cover_idx = -1
        for i, p in enumerate(all_images):
            if p.stem.lower() == "cover":
                cover_idx = i
                break
        if cover_idx > -1:
            all_images.insert(0, all_images.pop(cover_idx))

        total_count = len(all_images)
        dir_name = (
            f"{'📦' if 'koma_rename_' not in str(root_path) else '📁'} {root_path.name}"
        )
        if progress_callback:
            progress_callback(0, total_count, f"正在处理: {dir_name}")

        num_digits = max(3, len(str(total_count + start_index - 1)))
        pending_ops = []

        for index, src_path in enumerate(all_images, start=start_index):
            new_stem = f"{prefix}{index:0{num_digits}d}"
            new_name = f"{new_stem}{src_path.suffix}"
            if src_path.name == new_name:
                continue
            pending_ops.append((src_path, new_name))

        if not pending_ops:
            return []

        logger.info(f"{dir_name}")

        # 保存完整原路径，嵌套目录回滚时不能把文件恢复到根目录。
        staged: list[tuple[Path, Path, Path]] = []
        done = 0
        source_paths = {source.absolute() for source, _ in pending_ops}
        for source, name in pending_ops:
            target = source.absolute().with_name(name)
            if (target.exists() or target.is_symlink()) and target not in source_paths:
                raise FileExistsError(f"重命名目标已存在: {target}")

        try:
            for source, target_name in pending_ops:
                source = source.absolute()
                temp_path = source.with_name(
                    f"{KOMA_TMP_PREFIX}{uuid.uuid4().hex}{source.suffix}"
                )
                move_no_replace(source, temp_path)
                staged.append((temp_path, source.with_name(target_name), source))

            for i, (temp_path, final_path, original_path) in enumerate(staged):
                move_no_replace(temp_path, final_path)
                staged[i] = (final_path, final_path, original_path)
                done = i + 1
                logger.info(f"🔁 {original_path} -> {final_path.name}")
                if progress_callback:
                    progress_callback(
                        done,
                        len(staged),
                        f"重命名: {original_path} -> {final_path.name}",
                    )
        except Exception as e:
            remaining = self._rollback_rename(staged, done, root_path)
            rows = [
                [str(root_path), str(original), str(current)]
                for current, _, original in remaining
                if current != original and current.exists()
            ]
            raise RenameBatchError([f"文件夹 {root_path}: {e}"], rows) from e

        if return_csv:
            folder_csv_rows = [
                [
                    str(root_path),
                    str(original.relative_to(root_path.absolute())),
                    str(final.relative_to(root_path.absolute())),
                ]
                for _, final, original in staged
            ]
        return folder_csv_rows

    def _rollback_rename(
        self, staged: list[tuple[Path, Path, Path]], done: int, root_path: Path
    ) -> list[tuple[Path, Path, Path]]:
        """先腾空已发布名称，再按完整原路径恢复，绝不覆盖冲突文件。"""
        logger.warning(f"↩️ 正在回滚 {root_path} 中的重命名操作...")
        for i in range(done):
            current, target, original = staged[i]
            temporary = current.with_name(
                f"{KOMA_TMP_PREFIX}{uuid.uuid4().hex}{current.suffix}"
            )
            try:
                move_no_replace(current, temporary)
                staged[i] = (temporary, target, original)
            except OSError as e:
                logger.critical(f"⛔ 回滚暂存失败，保留 {current}: {e}")

        for i, (current, target, original) in enumerate(staged):
            try:
                move_no_replace(current, original)
                staged[i] = (original, target, original)
            except OSError as e:
                logger.critical(
                    f"⛔ 回滚受阻，文件保留在 {current}，未覆盖 {original}: {e}"
                )
        return staged

    def _write_csv_report(self, rows: list):
        """生成 CSV 报告"""
        try:
            timestamp = int(time.time())
            csv_path = self.target_dir / f"rename_report_{timestamp}.csv"
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["文件夹", "原文件名", "新文件名"])
                writer.writerows(rows)
            logger.info(f"📊 CSV 映射报告已生成: {csv_path}")
        except Exception as e:
            logger.error(f"生成 CSV 报告失败: {e}")
            raise
