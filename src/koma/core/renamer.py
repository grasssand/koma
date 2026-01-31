import os
import uuid
from pathlib import Path

from natsort import natsorted

from koma.core.scanner import Scanner
from koma.utils import logger


class Renamer:
    def __init__(self, target_dir: Path, enable_ad_detection: bool = False):
        self.target_dir = Path(target_dir)
        self.enable_ad_detection = enable_ad_detection

    def run(self):
        logger.info(f"⚒️ 开始重命名整理: {self.target_dir}")
        scanner = Scanner(self.target_dir, enable_ad_detection=self.enable_ad_detection)
        for root, result in scanner.run():
            all_images = result.to_convert + result.to_copy

            if not all_images:
                continue

            all_images = natsorted(all_images, key=lambda p: p.name)

            total_count = len(all_images)
            logger.info(f"📂 {root.name} (共 {total_count} 张)")

            # 至少保留 3 位 (001)
            num_digits = max(3, len(str(total_count)))

            temp_map = []

            try:
                for src_path in all_images:
                    # 生成临时文件名，防止命名冲突
                    temp_name = f".tmp_{uuid.uuid4()}{src_path.suffix}"
                    temp_path = root / temp_name

                    os.rename(src_path, temp_path)
                    temp_map.append((src_path.name, temp_path))

            except Exception as e:
                logger.error(f"临时重命名发生错误，停止当前文件夹处理: {e}")
                continue

            for index, (src_name, temp_path) in enumerate(temp_map):
                new_name = ""
                try:
                    suffix = temp_path.suffix
                    new_stem = f"{index:0{num_digits}d}"
                    new_name = f"{new_stem}{suffix}"
                    final_path = root / new_name

                    logger.info(f"🔁 {src_name} -> {new_name}")
                    os.rename(temp_path, final_path)

                except Exception as e:
                    logger.error(f"最终重命名失败 {temp_path.name} -> {new_name}: {e}")

            logger.info(f"✅ 完成: {root.name}")

        logger.info("🎉 所有重命名任务完成！")
