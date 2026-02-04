from unittest.mock import MagicMock

import pytest

from koma.core.binder import Binder


@pytest.fixture
def binder_setup(tmp_path, ext_config):
    out_dir = tmp_path / "output"
    mock_archive = MagicMock()
    return Binder(out_dir, ext_config, mock_archive), tmp_path, out_dir, mock_archive


def test_scan_folder_images(binder_setup):
    """测试文件夹扫描"""
    binder, tmp, _, _ = binder_setup
    src = tmp / "folder"
    src.mkdir()
    (src / "10.jpg").touch()
    (src / "002.png").touch()
    (src / "ignore.txt").touch()

    imgs = binder._scan_folder_images(src)
    names = [p.name for p in imgs]
    # 验证自然排序
    assert names == ["002.png", "10.jpg"]


def test_binder_run_mixed_inputs(binder_setup):
    """测试核心流程：混合输入源 (图片 + 文件夹 + 压缩包)"""
    binder, tmp, out_dir, mock_handler = binder_setup

    img1 = tmp / "cover.jpg"
    img1.touch()
    archive = tmp / "ch1.zip"
    archive.touch()
    folder = tmp / "ch2"
    folder.mkdir()
    (folder / "p1.jpg").touch()

    # 模拟解压结果
    mock_extract_path = tmp / "extracted"
    mock_extract_path.mkdir()
    (mock_extract_path / "arc_p1.jpg").touch()
    mock_handler.extract.return_value = mock_extract_path

    progress_cb = MagicMock()
    binder.run([img1, archive, folder], progress_callback=progress_cb)

    dest_files = sorted(out_dir.iterdir())
    assert len(dest_files) == 3
    # 顺序：cover -> extracted -> folder
    assert dest_files[0].name.endswith(".jpg")
    assert dest_files[0].name.startswith("000")  # cover

    assert mock_handler.extract.called
    assert progress_cb.call_count >= 3


def test_binder_empty_input(binder_setup):
    """测试空输入"""
    binder, _, out_dir, _ = binder_setup
    binder.run([])
    assert not out_dir.exists()


def test_binder_non_existent_path(binder_setup):
    """测试不存在的路径"""
    binder, tmp, out_dir, _ = binder_setup
    binder.run([tmp / "ghost.jpg"])
    assert not list(out_dir.iterdir())


def test_binder_overwrite_existing(binder_setup):
    """测试目标文件已存在时，应自动覆盖"""
    binder, tmp, out_dir, _ = binder_setup
    img = tmp / "new.jpg"
    img.write_text("New")

    out_dir.mkdir()
    (out_dir / "000.jpg").write_text("Old")

    binder.run([img])
    assert (out_dir / "000.jpg").read_text() == "New"
