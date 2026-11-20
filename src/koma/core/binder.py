import logging
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from natsort import natsorted

from koma.config import ExtensionsConfig
from koma.core.archive import ArchiveHandler
from koma.core.file_safety import move_no_replace, validate_prefix

logger = logging.getLogger(__name__)


class Binder:
    def __init__(
        self,
        output_dir: Path,
        ext_config: ExtensionsConfig,
        archive_handler: ArchiveHandler,
    ):
        """
        初始化合集装订器

        Args:
            output_dir: 输出目录
            ext_config: 扩展名配置
            archive_handler: 归档处理器
        """
        self.output_dir = Path(output_dir)
        self.ext_config = ext_config
        self.archive_handler = archive_handler

    def run(
        self,
        ordered_paths: list[Path],
        options: dict[str, Any] | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> None:
        if not ordered_paths:
            logger.warning("合集列表为空")
            return

        options = options or {}
        prefix = options.get("prefix", "")
        validate_prefix(prefix)
        start_index = options.get("start_index", 0)
        if (
            isinstance(start_index, bool)
            or not isinstance(start_index, int)
            or start_index < 0
        ):
            raise ValueError("起始序号必须是非负整数")

        with tempfile.TemporaryDirectory(prefix="koma_binder_") as temp_root_str:
            temp_root = Path(temp_root_str)
            final_sequence: list[Path] = []
            protected_inputs: list[Path] = []

            logger.info("📦 开始收集文件序列...")

            for original_path in ordered_paths:
                path = Path(original_path)
                if not path.exists():
                    logger.warning(f"跳过不存在的路径: {path}")
                    continue

                if path.is_file():
                    # 原始文件（尤其是归档本身）也不能被输出结果覆盖。
                    protected_inputs.append(path)
                    if self._is_image(path):
                        final_sequence.append(path)
                        logger.info(f"添加图片: {path.name}")
                    elif self._is_archive(path):
                        if progress_callback:
                            progress_callback(0, 0, f"正在解压: {path.name}...")

                        extract_dir = self.archive_handler.extract(path, temp_root)
                        imgs = [
                            p
                            for p in extract_dir.rglob("*")
                            if p.is_file() and self._is_image(p)
                        ]
                        final_sequence.extend(natsorted(imgs))
                        logger.info(f"从归档添加 {len(imgs)} 张图片: {path.name}")
                elif path.is_dir():
                    # 保护所选目录内全部文件，避免输出覆盖尚未读取的素材。
                    protected_inputs.extend(p for p in path.rglob("*") if p.is_file())
                    imgs = self._scan_folder_images(path)
                    final_sequence.extend(imgs)
                    logger.info(f"从文件夹添加 {len(imgs)} 张图片: {path.name}")

            total_count = len(final_sequence)
            if total_count == 0:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                logger.warning("⚠️ 未找到任何有效图片，任务终止。")
                return

            logger.info(f"✅ 收集完成，共 {total_count} 张图片")

            # 先规划全部名称，拒绝别名目标及对未读取输入的覆盖。
            num_digits = max(3, len(str(total_count + start_index - 1)))
            protected_keys = {self._path_key(path) for path in protected_inputs}
            protected_keys.update(self._path_key(path) for path in final_sequence)
            target_keys: dict[tuple, Path] = {}
            targets: list[tuple[Path, Path]] = []
            for index, src_path in enumerate(final_sequence, start=start_index):
                new_stem = f"{prefix}{index:0{num_digits}d}"
                new_name = f"{new_stem}{src_path.suffix}"
                validate_prefix(new_name)
                dest_path = self.output_dir / new_name
                key = self._path_key(dest_path)
                if key in protected_keys:
                    raise ValueError(f"输出目标与输入文件冲突: {dest_path}")
                if dest_path.is_symlink() or dest_path.is_dir():
                    raise ValueError(f"输出目标不能是链接或目录: {dest_path}")
                if key in target_keys:
                    raise ValueError(
                        f"多个输入映射到同一输出文件: {target_keys[key]} 和 {src_path}"
                    )
                target_keys[key] = src_path
                targets.append((src_path, dest_path))
            self.output_dir.mkdir(parents=True, exist_ok=True)

            # 先暂存所有输入和旧输出；发布中途失败时恢复已经替换的目标。
            stage_root = Path(
                tempfile.mkdtemp(prefix=".koma-binder-", dir=self.output_dir)
            )
            keep_stage = False
            try:
                backup_root = stage_root / "backups"
                backup_root.mkdir()
                staged_targets: list[tuple[Path, Path]] = []
                backups: dict[Path, Path] = {}
                target_stats = {}

                for index, (src_path, dest_path) in enumerate(targets, start=1):
                    if progress_callback:
                        progress_callback(
                            index - 1, total_count, f"暂存: {dest_path.name}"
                        )
                    staged_path = stage_root / f"{index:08d}{dest_path.suffix}"
                    shutil.copy2(src_path, staged_path)
                    if not staged_path.is_file():
                        raise FileNotFoundError(f"暂存文件未生成: {src_path}")
                    staged_targets.append((staged_path, dest_path))

                    if dest_path.exists():
                        stat = dest_path.stat()
                        identity = (
                            stat.st_dev,
                            stat.st_ino,
                            stat.st_size,
                            stat.st_mtime_ns,
                        )
                        target_stats[dest_path] = identity
                        backup = backup_root / f"{index:08d}{dest_path.suffix}"
                        shutil.copy2(dest_path, backup)
                        after_copy = dest_path.stat()
                        if identity != (
                            after_copy.st_dev,
                            after_copy.st_ino,
                            after_copy.st_size,
                            after_copy.st_mtime_ns,
                        ):
                            raise RuntimeError(f"输出文件在备份期间被修改: {dest_path}")
                        backups[dest_path] = backup

                published: list[Path] = []
                try:
                    for index, (staged_path, dest_path) in enumerate(
                        staged_targets, start=1
                    ):
                        if dest_path in backups:
                            current = dest_path.stat()
                            identity = (
                                current.st_dev,
                                current.st_ino,
                                current.st_size,
                                current.st_mtime_ns,
                            )
                            if target_stats[dest_path] != identity:
                                raise RuntimeError(
                                    f"输出文件已被其他程序修改: {dest_path}"
                                )
                            os.replace(staged_path, dest_path)
                        else:
                            move_no_replace(staged_path, dest_path)
                        published.append(dest_path)
                        if progress_callback:
                            progress_callback(
                                index, total_count, f"导出: {dest_path.name}"
                            )
                except Exception as e:
                    rollback_errors = []
                    for dest_path in reversed(published):
                        try:
                            if dest_path in backups:
                                os.replace(backups[dest_path], dest_path)
                            else:
                                dest_path.unlink()
                        except OSError as rollback_error:
                            rollback_errors.append(f"{dest_path}: {rollback_error}")
                    if rollback_errors:
                        keep_stage = True
                        raise RuntimeError(
                            f"发布失败且回滚未完成；原始输出备份保留在 {stage_root}: "
                            + "; ".join(rollback_errors)
                        ) from e
                    raise
            finally:
                if not keep_stage:
                    try:
                        shutil.rmtree(stage_root)
                    except OSError as e:
                        logger.warning(f"清理装订暂存目录失败 {stage_root}: {e}")

            if progress_callback:
                progress_callback(total_count, total_count, "装订整理完成")
            logger.info(f"🎉 合集整理完成！输出目录: {self.output_dir}")

    @staticmethod
    def _path_key(path: Path) -> tuple:
        """按路径及文件实体检测符号链接、硬链接和大小写别名。"""
        try:
            resolved = path.resolve(strict=False)
        except (OSError, RuntimeError):
            resolved = Path(os.path.abspath(path))
        try:
            stat = resolved.stat()
        except OSError:
            return ("path", os.path.normcase(str(resolved)).casefold())
        if stat.st_ino:
            return ("stat", stat.st_dev, stat.st_ino)
        return ("path", os.path.normcase(str(resolved)).casefold())

    def _is_image(self, path: Path) -> bool:
        return path.suffix.lower() in self.ext_config.all_supported_img

    def _is_archive(self, path: Path) -> bool:
        return path.suffix.lower() in self.ext_config.archive

    def _scan_folder_images(self, folder: Path) -> list[Path]:
        if not folder.exists():
            return []

        images = [
            p
            for p in folder.iterdir()
            if p.is_file() and not p.name.startswith(".") and self._is_image(p)
        ]
        return natsorted(images)
