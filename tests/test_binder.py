from unittest.mock import MagicMock, patch

import pytest

from koma.core import Binder


@pytest.fixture
def binder_setup(tmp_path):
    out_dir = tmp_path / "output"
    return Binder(out_dir), tmp_path, out_dir


def test_scan_folder_images(binder_setup):
    """测试文件夹扫描"""
    binder, tmp, _ = binder_setup

    src = tmp / "folder"
    src.mkdir()

    (src / "10.jpg").touch()
    (src / "002.png").touch()
    (src / "1.webp").touch()
    (src / "info.txt").touch()
    (src / ".hidden").touch()

    imgs = binder._scan_folder_images(src)

    names = [p.name for p in imgs]
    assert names == ["1.webp", "002.png", "10.jpg"]


def test_binder_run_mixed_inputs(binder_setup):
    """测试核心流程：混合输入源 (图片 + 文件夹 + 压缩包)"""
    binder, tmp, out_dir = binder_setup

    # 单图
    img1 = tmp / "cover.jpg"
    img1.touch()
    # 压缩包
    archive = tmp / "chapter1.zip"
    archive.touch()
    # 文件夹
    folder = tmp / "chapter2"
    folder.mkdir()
    (folder / "p1.png").touch()
    (folder / "p2.jpg").touch()

    # 模拟压缩包解压后的路径
    mock_extract_path = tmp / "temp_extract"
    mock_extract_path.mkdir()
    (mock_extract_path / "arc_1.jpg").touch()
    (mock_extract_path / "arc_2.jpg").touch()

    ordered_paths = [img1, archive, folder]

    with patch("koma.core.binder.ArchiveHandler") as MockHandlerClass:
        mock_handler = MockHandlerClass.return_value
        mock_handler.extract.return_value = mock_extract_path

        binder.archive_handler = mock_handler

        progress_cb = MagicMock()
        binder.run(ordered_paths, progress_callback=progress_cb)

    dest_files = sorted(out_dir.iterdir())
    assert len(dest_files) == 5

    dest_names = [p.name for p in dest_files]
    assert dest_names[0].startswith("000")  # cover.jpg
    assert dest_names[1].startswith("001")  # arc_1
    assert dest_names[2].startswith("002")  # arc_2
    assert dest_names[3].startswith("003")  # p1
    assert dest_names[4].startswith("004")  # p2

    assert progress_cb.call_count >= 5


def test_binder_empty_input(binder_setup):
    """测试空输入"""
    binder, _, out_dir = binder_setup
    binder.run([])
    assert not out_dir.exists()


def test_binder_non_existent_path(binder_setup):
    """测试不存在的路径"""
    binder, tmp, out_dir = binder_setup

    bad_path = tmp / "ghost.jpg"
    binder.run([bad_path])

    assert not list(out_dir.iterdir())


def test_binder_overwrite_existing(binder_setup):
    """测试目标文件已存在时，应自动覆盖"""
    binder, tmp, out_dir = binder_setup

    img1 = tmp / "new_image.jpg"
    img1.write_text("New Content")
    out_dir.mkdir(parents=True, exist_ok=True)
    dest_file = out_dir / "000.jpg"
    dest_file.write_text("Old Content")
    binder.run([img1])

    assert dest_file.read_text() == "New Content"
