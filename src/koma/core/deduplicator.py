import os
import re
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple

from koma.config import ARCHIVE_EXTS, COMIC_TITLE_RE


class DuplicateItem(NamedTuple):
    path: Path
    is_archive: bool


class Deduplicator:
    def scan(self, input_paths: list[Path]) -> dict[str, list[DuplicateItem]]:
        items_map = defaultdict(list)

        for root in input_paths:
            root = Path(root)
            if not root.exists():
                continue

            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                current_dir = Path(dirpath)

                # 检查最深层文件夹
                if not dirnames:
                    self._process_node(current_dir, is_archive=False, lookup=items_map)

                # 检查归档文件
                for f in filenames:
                    f_path = current_dir / f
                    if f_path.suffix.lower() in ARCHIVE_EXTS:
                        self._process_node(f_path, is_archive=True, lookup=items_map)

        return {k: v for k, v in items_map.items() if len(v) > 1}

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

        match = COMIC_TITLE_RE.search(name)
        if match:
            raw_artist = match.group("artist") or ""
            raw_title = match.group("title") or ""
            raw_series = match.group("series") or ""
            if raw_series:
                raw_series = raw_series.rstrip(") ")

            core_artist = self._extract_circle_name(raw_artist)

            artist_norm = self._normalize_text(core_artist)
            title_norm = self._normalize_text(raw_title)
            series_norm = self._normalize_text(raw_series)

            key_parts = [p for p in [artist_norm, title_norm, series_norm] if p]
            key = " - ".join(key_parts)

            lookup[key].append(DuplicateItem(path, is_archive))
        else:
            key = self._normalize_text(name)
            lookup[key].append(DuplicateItem(path, is_archive))
