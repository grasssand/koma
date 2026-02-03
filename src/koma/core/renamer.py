import csv
import os
import time
import uuid
from pathlib import Path

from natsort import natsorted

from koma.core.scanner import Scanner
from koma.utils import logger


class Renamer:
    def __init__(
        self,
        target_dir: Path,
        enable_ad_detection: bool = False,
        export_csv: bool = False,
    ):
        self.target_dir = Path(target_dir)
        self.enable_ad_detection = enable_ad_detection
        self.export_csv = export_csv

    def run(self):
        logger.info(f"⚒️ 开始重命名整理: {self.target_dir}")
        scanner = Scanner(self.target_dir, enable_ad_detection=self.enable_ad_detection)

        csv_rows = []

        for root, result in scanner.run():
            all_images = result.to_convert + result.to_copy

            if not all_images:
                continue

            all_images = natsorted(all_images)

            cover_idx = -1
            for i, p in enumerate(all_images):
                if p.stem.lower() == "cover":
                    cover_idx = i
                    break
            if cover_idx > -1:
                all_images.insert(0, all_images.pop(cover_idx))

            total_count = len(all_images)
            logger.info(f"📂 {root.name} (共 {total_count} 张)")

            # 至少保留 3 位 (001)
            num_digits = max(3, len(str(total_count)))

            pending_ops = []
            skipped_count = 0

            for index, src_path in enumerate(all_images):
                # 计算预期的新文件名
                new_stem = f"{index:0{num_digits}d}"
                new_name = f"{new_stem}{src_path.suffix}"

                # 如果名字已经对了，直接跳过
                if src_path.name == new_name:
                    skipped_count += 1
                    continue

                pending_ops.append((src_path, new_name))

            if skipped_count > 0:
                logger.info(f"⏩ 跳过 {skipped_count} 个无需修改的文件")

            if not pending_ops:
                logger.info(f"✅ 完成: {root.name} (无需变动)")
                continue

            temp_map = []

            try:
                # 临时重命名为 UUID，防止冲突
                for src_path, target_name in pending_ops:
                    temp_name = f".tmp_{uuid.uuid4()}{src_path.suffix}"
                    temp_path = root / temp_name

                    os.rename(src_path, temp_path)

                    temp_map.append((temp_path, target_name, src_path.name))

            except Exception as e:
                logger.error(f"临时重命名阶段发生错误: {e}")
                continue

            # 最终重命名
            for temp_path, target_name, original_src_name in temp_map:
                try:
                    final_path = root / target_name
                    os.rename(temp_path, final_path)

                    logger.info(f"🔁 {original_src_name} -> {target_name}")

                    # 收集 CSV 数据
                    if self.export_csv:
                        csv_rows.append([root, original_src_name, target_name])

                except Exception as e:
                    logger.error(
                        f"最终重命名失败 {temp_path.name} -> {target_name}: {e}"
                    )

            logger.info(f"✅ 完成: {root.name}")

        # 写入 CSV 文件
        if self.export_csv and csv_rows:
            self._write_csv_report(csv_rows)

        logger.info("🎉 所有重命名任务完成！")

    def _write_csv_report(self, rows):
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
