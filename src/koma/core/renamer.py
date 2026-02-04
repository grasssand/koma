import csv
import logging
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from natsort import natsorted

from koma.config import ExtensionsConfig
from koma.core.image_processor import ImageProcessor
from koma.core.scanner import Scanner

logger = logging.getLogger(__name__)


class Renamer:
    def __init__(
        self,
        target_dir: Path,
        ext_config: ExtensionsConfig,
        image_processor: ImageProcessor,
        export_csv: bool = False,
    ):
        """
        初始化重命名器

        Args:
            target_dir: 目标文件夹
            ext_config: 扩展名配置
            image_processor: 图片处理器
            export_csv: 是否导出 CSV 映射表
        """
        self.target_dir = Path(target_dir)
        self.ext_config = ext_config
        self.image_processor = image_processor
        self.export_csv = export_csv

    def run(self, progress_callback: Callable[[int, int, str], None] | None = None):
        logger.info(f"⚒️ 开始重命名整理: {self.target_dir}")

        scanner = Scanner(
            input_dir=self.target_dir,
            ext_config=self.ext_config,
            image_processor=self.image_processor,
        )

        csv_rows = []

        for root, result in scanner.run():
            all_images = result.to_convert + result.to_copy

            if not all_images:
                continue

            all_images = natsorted(all_images)
            # 封面置顶
            cover_idx = -1
            for i, p in enumerate(all_images):
                if p.stem.lower() == "cover":
                    cover_idx = i
                    break
            if cover_idx > -1:
                all_images.insert(0, all_images.pop(cover_idx))

            total_count = len(all_images)
            logger.info(f"📂 {root.name} (共 {total_count} 张)")

            if progress_callback:
                progress_callback(0, total_count, f"正在处理文件夹: {root.name}")

            num_digits = max(3, len(str(total_count)))
            pending_ops = []
            skipped_count = 0

            for index, src_path in enumerate(all_images):
                new_stem = f"{index:0{num_digits}d}"
                new_name = f"{new_stem}{src_path.suffix}"

                if src_path.name == new_name:
                    skipped_count += 1
                    continue
                pending_ops.append((src_path, new_name))

            if not pending_ops:
                if progress_callback:
                    progress_callback(total_count, total_count, f"跳过: {root.name}")
                continue

            temp_map = []

            total_ops = len(pending_ops) * 2
            current_op = 0

            try:
                # 临时重命名为 UUID，防止冲突
                for src_path, target_name in pending_ops:
                    temp_name = f".tmp_{uuid.uuid4()}{src_path.suffix}"
                    temp_path = root / temp_name
                    os.rename(src_path, temp_path)
                    temp_map.append((temp_path, target_name, src_path.name))

                    current_op += 1

                    if progress_callback:
                        progress_callback(
                            current_op, total_ops, f"预处理: {src_path.name}"
                        )

            except Exception as e:
                logger.error(f"临时重命名错误: {e}")
                continue

            # 最终重命名
            for temp_path, target_name, original_src_name in temp_map:
                try:
                    final_path = root / target_name
                    os.rename(temp_path, final_path)

                    logger.info(f"🔁 {original_src_name} -> {target_name}")

                    # 收集 CSV 数据
                    if self.export_csv:
                        csv_rows.append([str(root), original_src_name, target_name])

                    current_op += 1
                    if progress_callback:
                        progress_callback(
                            current_op, total_ops, f"重命名: {target_name}"
                        )

                except Exception as e:
                    logger.error(f"重命名失败: {e}")

            logger.info(f"✅ 完成: {root.name}")

        if self.export_csv and csv_rows:
            self._write_csv_report(csv_rows)

        if progress_callback:
            progress_callback(1, 1, "重命名任务完成")

        logger.info("🎉 所有重命名任务完成！")

        # 任务结束，发送 100%
        if progress_callback:
            progress_callback(1, 1, "重命名任务完成")

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
