import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from natsort import natsorted

from koma.config import ARCHIVE_EXTS, SUPPORTED_IMAGE_EXTS
from koma.utils import logger
from koma.utils.archive import ArchiveHandler


class Binder:
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.archive_handler = ArchiveHandler()

    def _is_image(self, path: Path) -> bool:
        return path.suffix.lower() in SUPPORTED_IMAGE_EXTS

    def _is_archive(self, path: Path) -> bool:
        return path.suffix.lower() in ARCHIVE_EXTS

    def _scan_folder_images(self, folder: Path) -> list[Path]:
        """扫描文件夹下仅第一层的图片，并按自然顺序排序"""
        if not folder.exists():
            return []

        images = [
            p
            for p in folder.iterdir()
            if p.is_file() and not p.name.startswith(".") and self._is_image(p)
        ]
        return natsorted(images)

    def run(
        self,
        ordered_paths: list[Path],
        progress_callback: Callable[[int, int, str], None] | None = None,
    ):
        """
        执行合集整理

        Args:
            ordered_paths: 用户排序好的路径列表
            progress_callback: 回调函数 (current, total, status_msg)
        """
        if not ordered_paths:
            logger.warning("合集列表为空")
            return

        self.output_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="koma_binder_") as temp_root_str:
            temp_root = Path(temp_root_str)
            final_sequence: list[Path] = []

            logger.info("📦 开始收集文件序列...")

            for path in ordered_paths:
                path = Path(path)
                if not path.exists():
                    logger.warning(f"跳过不存在的路径: {path}")
                    continue

                try:
                    # 单张图片
                    if path.is_file() and self._is_image(path):
                        final_sequence.append(path)
                        logger.info(f"添加图片: {path.name}")

                    # 压缩包
                    elif path.is_file() and self._is_archive(path):
                        if progress_callback:
                            progress_callback(0, 0, f"正在解压: {path.name}...")

                        extract_dir = self.archive_handler.extract(path, temp_root)
                        imgs = [
                            p
                            for p in extract_dir.rglob("*")
                            if p.is_file() and self._is_image(p)
                        ]
                        imgs = natsorted(imgs)

                        final_sequence.extend(imgs)
                        logger.info(f"从归档添加 {len(imgs)} 张图片: {path.name}")

                    # 文件夹
                    elif path.is_dir():
                        imgs = self._scan_folder_images(path)
                        final_sequence.extend(imgs)
                        logger.info(f"从文件夹添加 {len(imgs)} 张图片: {path.name}")

                except Exception as e:
                    logger.error(f"处理路径出错 {path}: {e}")

            total_count = len(final_sequence)
            if total_count == 0:
                logger.warning("⚠️ 未找到任何有效图片，任务终止。")
                return

            logger.info(f"✅ 收集完成，共 {total_count} 张图片")

            num_digits = max(3, len(str(total_count)))
            for index, src_path in enumerate(final_sequence):
                try:
                    new_stem = f"{index:0{num_digits}d}"
                    new_name = f"{new_stem}{src_path.suffix}"
                    dest_path = self.output_dir / new_name

                    if progress_callback:
                        progress_callback(index + 1, total_count, f"导出: {new_name}")

                    # 使用 copy2 保留文件元数据
                    shutil.copy2(src_path, dest_path)

                except Exception as e:
                    logger.error(f"复制文件失败 {src_path.name}: {e}")

            logger.info(f"🎉 合集整理完成！输出目录: {self.output_dir}")
