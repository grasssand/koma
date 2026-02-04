import logging
import os
import re
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from natsort import natsorted

from koma.config import DeduplicatorConfig, ExtensionsConfig

logger = logging.getLogger(__name__)


class DuplicateItem(NamedTuple):
    path: Path
    is_archive: bool


class Deduplicator:
    def __init__(self, ext_config: ExtensionsConfig, dedupe_config: DeduplicatorConfig):
        """
        初始化查重器

        Args:
            ext_config: 扩展名配置
            dedupe_config: 查重配置
        """
        self.ext_config = ext_config
        self.config = dedupe_config

        try:
            self.title_re = re.compile(self.config.comic_dir_regex)
        except re.error as e:
            logger.error(f"正则编译失败: {e}，将使用全名匹配作为回退方案")
            self.title_re = re.compile(r"(?P<title>.*)")

    def run(
        self,
        input_paths: list[Path],
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, list[DuplicateItem]]:
        items_map = defaultdict(list)
        archive_exts = self.ext_config.archive | self.ext_config.document

        for _, root in enumerate(input_paths):
            root = Path(root)
            if not root.exists():
                continue

            if progress_callback:
                progress_callback(0, 0, f"正在扫描根目录: {root.name}...")

            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                current_dir = Path(dirpath)

                if progress_callback:
                    # 限制显示长度，防止路径太长撑爆 UI
                    display_path = current_dir.name
                    if len(display_path) > 30:
                        display_path = display_path[:27] + "..."
                    progress_callback(0, 0, f"分析中: {display_path}")

                if not dirnames:
                    self._process_node(current_dir, is_archive=False, lookup=items_map)

                for f in filenames:
                    f_path = current_dir / f
                    if f_path.suffix.lower() in archive_exts:
                        self._process_node(f_path, is_archive=True, lookup=items_map)

        final_results = {}
        valid_keys = [k for k, v in items_map.items() if len(v) > 1]
        sorted_keys = natsorted(valid_keys)
        for key in sorted_keys:
            items = items_map[key]
            items.sort(
                key=lambda x: x.path.stat().st_mtime if x.path.exists() else 0,
                reverse=True,
            )

            final_results[key] = items

        if progress_callback:
            progress_callback(1, 1, "扫描分析完成")

        return final_results

    def _normalize_text(self, text: str) -> str:
        """归一化：全角转半角，去多余空格，转小写"""
        if not text:
            return ""
        text = text.replace("　", " ")
        text = re.sub(r"\s+", " ", text)
        return text.strip().lower()

    def _extract_circle_name(self, bracket_content: str) -> str:
        """从 '[社团 (作者)]' 提取 '社团'"""
        if not bracket_content:
            return ""
        content = bracket_content.strip("[]")
        if "(" in content:
            return content.split("(", 1)[0]
        return content

    def _process_node(self, path: Path, is_archive: bool, lookup: dict):
        name = path.stem if is_archive else path.name
        match = self.title_re.search(name)

        if match:
            groups = match.groupdict()
            raw_artist = groups.get("artist") or ""
            raw_title = groups.get("title") or ""
            raw_series = groups.get("series") or ""

            if raw_series:
                raw_series = raw_series.rstrip(") ")

            core_artist = self._extract_circle_name(raw_artist)
            artist_norm = self._normalize_text(core_artist)
            title_norm = self._normalize_text(raw_title)
            series_norm = self._normalize_text(raw_series)

            key_parts = [p for p in [artist_norm, title_norm, series_norm] if p]
            key = " - ".join(key_parts)
            if not key:
                key = self._normalize_text(name)
            lookup[key].append(DuplicateItem(path, is_archive))
        else:
            key = self._normalize_text(name)
            lookup[key].append(DuplicateItem(path, is_archive))
