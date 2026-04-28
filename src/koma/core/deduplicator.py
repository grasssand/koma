import logging
import re
import sys
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import numpy as np
import onnxruntime as ort
from natsort import natsorted
from PIL import Image

from koma.config import DeduplicatorConfig, ExtensionsConfig
from koma.core.archive import ArchiveHandler

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
        self.archive_handler = ArchiveHandler(self.ext_config)
        self.ort_session = None

        try:
            self.title_re = re.compile(self.config.comic_dir_regex)
        except re.error as e:
            logger.error(f"正则编译失败: {e}，将使用全名匹配作为回退方案")
            self.title_re = re.compile(r"(?P<title>.*)")

    def _init_onnx(self):
        """初始化 ONNX 模型"""
        if self.ort_session is not None:
            return

        if getattr(sys, "frozen", False):
            base_path = Path(sys._MEIPASS) / "koma"  # type: ignore
        else:
            base_path = Path(__file__).parent.parent
        model_path = (
            base_path / "resources" / "onnx" / "mobilenet_v3_small_features.onnx"
        )

        if not model_path.exists():
            raise FileNotFoundError(f"未找到 ONNX 模型文件: {model_path}")

        self.ort_session = ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )

    def run(
        self,
        input_paths: list[Path],
        mode: str = "filename",  # "filename" 或 "cover"
        similarity_threshold: int = 85,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, list[DuplicateItem]]:
        all_items: list[DuplicateItem] = []
        archive_exts = self.ext_config.archive | self.ext_config.document

        for root in input_paths:
            root = Path(root)
            if not root.exists():
                continue

            for dirpath, dirnames, filenames in root.walk():
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                current_dir = Path(dirpath)

                if progress_callback:
                    progress_callback(0, 0, f"扫描收集目录中: {current_dir.name[:27]}")

                if not dirnames:
                    all_items.append(DuplicateItem(current_dir, is_archive=False))

                for f in filenames:
                    f_path = current_dir / f
                    if f_path.suffix.lower() in archive_exts:
                        all_items.append(DuplicateItem(f_path, is_archive=True))

        if not all_items:
            return {}

        if mode == "cover":
            self._init_onnx()
            return self._run_cover_mode(
                all_items, similarity_threshold, progress_callback
            )
        else:
            return self._run_filename_mode(all_items, progress_callback)

    def _run_filename_mode(
        self,
        items: list[DuplicateItem],
        progress_callback: Callable[[int, int, str], None] | None = None,
    ):
        items_map = defaultdict(list)

        def _process_node(item: DuplicateItem):
            name = item.path.stem if item.is_archive else item.path.name
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
                items_map[key].append(item)
            else:
                key = self._normalize_text(name)
                items_map[key].append(item)

        total = len(items)
        for i, item in enumerate(items):
            if progress_callback:
                progress_callback(i, total, f"文件名分析: {item.path.name[:25]}...")
            _process_node(item)

        if progress_callback:
            progress_callback(total, total, "文件名对比分析完成")

        return self._format_results(items_map)

    def _run_cover_mode(
        self,
        items: list[DuplicateItem],
        threshold: int,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ):
        threshold /= 100.0
        total = len(items)
        clusters = []

        for i, item in enumerate(items):
            if progress_callback:
                progress_callback(i, total, f"封面分析: {item.path.name[:25]}...")

            emb = self._extract_embedding(item)
            if emb is None:
                continue

            best_match_idx = -1
            best_sim = -1.0

            for c_idx, cluster in enumerate(clusters):
                sim = np.dot(emb, cluster["center_emb"])
                if sim > best_sim:
                    best_sim = sim
                    best_match_idx = c_idx

            if best_sim >= threshold:
                clusters[best_match_idx]["items"].append(item)
            else:
                clusters.append({"center_emb": emb, "items": [item]})

        items_map = {}
        for cluster in clusters:
            if len(cluster["items"]) > 1:
                rep_name = cluster["items"][0].path.stem
                items_map[f"相似组: {rep_name}"] = cluster["items"]

        if progress_callback:
            progress_callback(total, total, "封面比对分析完成")

        return self._format_results(items_map)

    def _format_results(self, items_map: dict) -> dict[str, list[DuplicateItem]]:
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

    def _extract_embedding(self, item: DuplicateItem) -> np.ndarray | None:
        """从文件提取封面并转化为 1D 特征向量"""
        try:
            img = None
            if not item.is_archive:
                for f in natsorted(item.path.iterdir(), key=lambda x: str(x)):
                    if (
                        f.is_file()
                        and f.suffix.lower() in self.ext_config.all_supported_img
                    ):
                        img = Image.open(f)
                        break
            else:
                img = self.archive_handler.extract_cover(item.path)

            if img is None:
                return None

            if img.mode in ("P", "RGBA", "LA") or (
                img.mode == "P" and "transparency" in img.info
            ):
                img = img.convert("RGBA")
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                img = bg
            else:
                img = img.convert("RGB")

            img = img.resize((224, 224))
            img_data = np.array(img).astype("float32") / 255.0

            mean = np.array([0.485, 0.456, 0.406])
            std = np.array([0.229, 0.224, 0.225])
            img_data = (img_data - mean) / std

            img_data = np.transpose(img_data, (2, 0, 1))
            img_data = np.expand_dims(img_data, axis=0)
            img_data = img_data.astype(np.float32)

            ort_inputs = {self.ort_session.get_inputs()[0].name: img_data}
            ort_outs = self.ort_session.run(None, ort_inputs)

            embedding = ort_outs[0].flatten()
            eps = 1e-8
            embedding = (embedding - np.mean(embedding)) / (np.std(embedding) + eps)
            norm = np.linalg.norm(embedding)

            return embedding / norm if norm > 0 else embedding

        except Exception as e:
            logger.debug(f"❌ 无法提取特征 {item.path.name}: {e}")
            return None
