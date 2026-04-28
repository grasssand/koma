from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from PIL import Image

from koma.core.deduplicator import Deduplicator, DuplicateItem


def test_filename_mode_normalization(tmp_path, ext_config, dedupe_config):
    """正则与文件名模式能否正确归一化并分组"""
    files = [
        "[Group] Title (Vol.1).zip",  # 标准
        "(C99) [Group] Title (Vol.1) [CN].rar",  # 带展会和语言
        "[Group (Author)] Title (Vol.1).7z",  # 带作者名
        "[Group] OtherTitle.zip",  # 干扰项 (不应在同一组)
    ]

    input_dir = tmp_path / "downloads"
    input_dir.mkdir()
    for f in files:
        (input_dir / f).touch()

    deduper = Deduplicator(ext_config, dedupe_config)
    results = deduper.run([input_dir], mode="filename")

    # 应该只发现 1 组重复项
    assert len(results) == 1

    duplicate_keys = list(results.keys())
    target_key = duplicate_keys[0]

    # 验证键名提取是否正确归一化
    assert "group" in target_key
    assert "title" in target_key
    assert "vol.1" in target_key

    # 验证分组内包含的文件
    detected_paths = [item.path.name for item in results[target_key]]
    assert len(detected_paths) == 3
    assert "[Group] Title (Vol.1).zip" in detected_paths
    assert "(C99) [Group] Title (Vol.1) [CN].rar" in detected_paths
    assert "[Group (Author)] Title (Vol.1).7z" in detected_paths
    assert "[Group] OtherTitle.zip" not in detected_paths


@patch("koma.core.deduplicator.Deduplicator._init_onnx")
@patch("koma.core.deduplicator.Deduplicator._extract_embedding")
def test_cover_mode_clustering(
    mock_extract, mock_init, tmp_path, ext_config, dedupe_config
):
    """封面查重模式能否正确根据特征向量聚类"""

    files = ["book_A1.zip", "book_A2.zip", "book_B.zip", "book_C.zip", "corrupt.zip"]
    input_dir = tmp_path / "covers"
    input_dir.mkdir()
    for f in files:
        (input_dir / f).touch()

    # 伪造特征向量
    # A1 和 A2 极其相似
    emb_a1 = np.array([1.0, 0.0, 0.0])
    emb_a2 = np.array([0.95, 0.312, 0.0])
    # B 和 C 是完全不同的图
    emb_b = np.array([0.0, 1.0, 0.0])
    emb_c = np.array([0.0, 0.0, 1.0])

    def mock_extract_side_effect(item):
        if item.path.name == "book_A1.zip":
            return emb_a1
        if item.path.name == "book_A2.zip":
            return emb_a2
        if item.path.name == "book_B.zip":
            return emb_b
        if item.path.name == "book_C.zip":
            return emb_c
        if item.path.name == "corrupt.zip":
            return None  # 模拟无法提取封面的损坏文件
        return None

    mock_extract.side_effect = mock_extract_side_effect

    deduper = Deduplicator(ext_config, dedupe_config)

    # 设定阈值为 85
    results = deduper.run([input_dir], mode="cover", similarity_threshold=85)

    # 验证是否只发现了一组重复项 (A1 和 A2)
    assert len(results) == 1

    group_key = next(iter(results.keys()))
    assert "book_A" in group_key

    detected_paths = [item.path.name for item in results[group_key]]
    assert len(detected_paths) == 2
    assert "book_A1.zip" in detected_paths
    assert "book_A2.zip" in detected_paths

    # B, C, corrupt 不应该出现在重复结果中
    assert "book_B.zip" not in detected_paths
    assert "book_C.zip" not in detected_paths


def test_empty_input(ext_config, dedupe_config):
    """空输入或不存在的路径的异常处理"""
    deduper = Deduplicator(ext_config, dedupe_config)

    # 测试空列表
    results_empty = deduper.run([], mode="filename")
    assert results_empty == {}

    # 测试不存在的路径
    results_invalid = deduper.run(
        [Path("/invalid/path/that/does/not/exist")], mode="cover"
    )
    assert results_invalid == {}


def test_extract_embedding_internal_coverage(tmp_path, ext_config, dedupe_config):
    """_extract_embedding 内部逻辑的测试"""
    deduper = Deduplicator(ext_config, dedupe_config)

    # 伪造 ONNX Session
    mock_session = MagicMock()
    mock_input = MagicMock()
    mock_input.name = "input"
    mock_session.get_inputs.return_value = [mock_input]

    # 伪造模型输出的 576 维特征向量
    fake_embedding = np.random.rand(1, 576).astype(np.float32)
    mock_session.run.return_value = [fake_embedding]
    deduper.ort_session = mock_session

    # 普通文件夹 + RGB 图片
    folder_rgb = tmp_path / "rgb_folder"
    folder_rgb.mkdir()
    img_rgb_path = folder_rgb / "cover.jpg"
    Image.new("RGB", (100, 100), color="red").save(img_rgb_path)

    item_rgb = DuplicateItem(path=folder_rgb, is_archive=False)
    emb_rgb = deduper._extract_embedding(item_rgb)
    assert emb_rgb is not None
    assert emb_rgb.shape == (576,)

    # 透明图片
    folder_rgba = tmp_path / "rgba_folder"
    folder_rgba.mkdir()
    img_rgba_path = folder_rgba / "cover.png"
    Image.new("RGBA", (100, 100), color=(255, 0, 0, 128)).save(img_rgba_path)

    item_rgba = DuplicateItem(path=folder_rgba, is_archive=False)
    emb_rgba = deduper._extract_embedding(item_rgba)
    assert emb_rgba is not None

    # 压缩包提取封面
    item_archive = DuplicateItem(path=tmp_path / "fake.zip", is_archive=True)
    deduper.archive_handler.extract_cover = MagicMock(
        return_value=Image.new("L", (50, 50))
    )
    emb_archive = deduper._extract_embedding(item_archive)
    assert emb_archive is not None

    # 异常处理
    mock_session.run.side_effect = Exception("模拟 ONNX 崩溃")
    emb_error = deduper._extract_embedding(item_rgb)
    assert emb_error is None  # 发生异常时应返回 None
