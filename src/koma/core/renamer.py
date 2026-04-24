import csv
import logging
import shutil
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
from koma.core.image_processor import ImageProcessor
from koma.core.scanner import Scanner

logger = logging.getLogger(__name__)


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

        scan_opts = options.copy()
        scan_opts["enable_archive_scan"] = False

        scanner = Scanner(
            input_dir=self.target_dir,
            ext_config=self.ext_config,
            image_processor=self.image_processor,
        )

        all_csv_rows = []

        for root, result in scanner.run(options=scan_opts):
            # 处理普通文件夹内的图片
            all_images = result.to_convert + result.to_copy
            if all_images:
                folder_csv_rows = self._rename_files_in_dir(
                    root, all_images, export_csv, prefix, start_index, progress_callback
                )
                all_csv_rows.extend(folder_csv_rows)

            if enable_archive_scan and result.archives:
                for arc_path in result.archives:
                    archive_csv_rows = self._process_archive(
                        arc_path, pack_format, prefix, start_index, progress_callback
                    )
                    all_csv_rows.extend(archive_csv_rows)

        if export_csv and all_csv_rows:
            self._write_csv_report(all_csv_rows)

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
        """处理单个压缩包：解压 -> 重命名 -> 重打包 -> 安全替换"""
        csv_rows = []
        temp_pack_path = None

        try:
            if progress_callback:
                progress_callback(0, 0, f"正在处理压缩包: {archive_path.name}")

            with tempfile.TemporaryDirectory(prefix="koma_rename_") as temp_dir:
                temp_root = Path(temp_dir)

                try:
                    content_root = self.archive_handler.extract(archive_path, temp_root)
                except Exception as e:
                    logger.error(f"解压失败 {archive_path.name}: {e}")
                    return []

                images = []
                for r, _, files in content_root.walk():
                    for f in files:
                        fp = Path(r) / f
                        if fp.suffix.lower() in self.ext_config.all_supported_img:
                            images.append(fp)

                changed_rows = self._rename_files_in_dir(
                    content_root, images, True, prefix, start_index, None
                )

                if not changed_rows:
                    logger.info(f"⏩ 压缩包内无需重命名，跳过: {archive_path}")
                    return []

                for row in changed_rows:
                    row[0] = f"📦 {archive_path}"
                csv_rows.extend(changed_rows)

                temp_pack_path = (
                    archive_path.parent / f"{archive_path.stem}_tmp.{pack_format}"
                )

                success = self.archive_handler.pack(
                    content_root, temp_pack_path, fmt=pack_format, level="normal"
                )

                if not success:
                    raise RuntimeError("重打包失败")

            # 安全替换
            send2trash(str(archive_path))
            logger.info(f"🗑️ 原文件已移入回收站: {archive_path.name}")

            final_name = f"{archive_path.stem}.{pack_format}"
            final_path = archive_path.parent / final_name

            if final_path.exists():
                final_path = (
                    archive_path.parent
                    / f"{archive_path.stem}_{int(time.time())}.{pack_format}"
                )
                logger.warning("⚠️ 存在同名文件，新压缩包已更名！")

            shutil.move(str(temp_pack_path), str(final_path))
            logger.info(f"✅ 压缩包处理完成: {final_path.name}")

        except Exception as e:
            logger.error(f"处理压缩包出错 {archive_path.name}: {e}")
            if temp_pack_path and temp_pack_path.exists():
                try:
                    temp_pack_path.unlink()
                except Exception:
                    pass

        return csv_rows

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

        num_digits = max(3, len(str(total_count)))
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

        temp_map = []
        total_ops = len(pending_ops) * 2
        current_op = 0

        try:
            # 临时重命名为 UUID，防止冲突
            for src_path, target_name in pending_ops:
                temp_name = f".tmp_{uuid.uuid4()}{src_path.suffix}"
                temp_path = src_path.parent / temp_name
                src_path.rename(temp_path)
                temp_map.append((temp_path, target_name, src_path.name))
                current_op += 1
                # if progress_callback:
                #     progress_callback(current_op, total_ops, "预处理重命名...")

            # 最终重命名
            for temp_path, target_name, original_src_name in temp_map:
                final_path = temp_path.parent / target_name
                temp_path.rename(final_path)
                logger.info(f"🔁 {original_src_name} -> {target_name}")

                # 收集 CSV 数据
                if return_csv:
                    folder_csv_rows.append(
                        [str(root_path), original_src_name, target_name]
                    )
                current_op += 1
                if progress_callback:
                    progress_callback(
                        current_op,
                        total_ops,
                        f"重命名: {root_path / original_src_name} -> {target_name}",
                    )

        except Exception as e:
            logger.error(f"文件夹 {root_path} 重命名发生错误: {e}")

        return folder_csv_rows

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
