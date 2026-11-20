import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from koma.core.archive import ArchiveHandler
from koma.core.binder import Binder


@pytest.mark.parametrize("prefix", ["../", "nested/", "bad:name"])
def test_binder_rejects_invalid_prefix_before_creating_output(binder_setup, prefix):
    binder, tmp, out_dir, _ = binder_setup
    source = tmp / "page.jpg"
    source.write_bytes(b"page")

    with pytest.raises(ValueError):
        binder.run([source], {"prefix": prefix})

    assert not out_dir.exists()


@pytest.mark.parametrize("start_index", [-1, "1", True, 1.5])
def test_binder_rejects_invalid_start_index(binder_setup, start_index):
    binder, tmp, out_dir, _ = binder_setup
    source = tmp / "page.jpg"
    source.write_bytes(b"page")

    with pytest.raises(ValueError, match="起始序号必须是非负整数"):
        binder.run([source], {"start_index": start_index})

    assert not out_dir.exists()


def test_binder_rejects_output_over_input(binder_setup):
    binder, tmp, _, _ = binder_setup
    source = tmp / "000.jpg"
    source.write_bytes(b"keep original")
    binder.output_dir = tmp

    with pytest.raises(ValueError, match="输出目标与输入文件冲突"):
        binder.run([source])

    assert source.read_bytes() == b"keep original"
    assert not list(tmp.glob(".koma-binder-*"))


def test_binder_staging_failure_preserves_all_old_results(binder_setup):
    binder, tmp, out_dir, _ = binder_setup
    first = tmp / "first.jpg"
    second = tmp / "second.jpg"
    first.write_bytes(b"first input")
    second.write_bytes(b"second input")
    out_dir.mkdir()
    old_first = out_dir / "000.jpg"
    old_second = out_dir / "001.jpg"
    old_first.write_bytes(b"old first")
    old_second.write_bytes(b"old second")
    calls = 0

    def fail_second_stage(src, dst):
        nonlocal calls
        calls += 1
        if calls == 2:
            Path(dst).write_bytes(b"partial stage")
            raise OSError("staging failed")
        Path(dst).write_bytes(Path(src).read_bytes())

    with (
        patch("koma.core.binder.shutil.copy2", side_effect=fail_second_stage),
        pytest.raises(OSError, match="staging failed"),
    ):
        binder.run([first, second])

    assert old_first.read_bytes() == b"old first"
    assert old_second.read_bytes() == b"old second"
    assert not list(out_dir.glob(".koma-binder-*"))


def test_binder_archive_extract_failure_is_reported(binder_setup):
    binder, tmp, out_dir, mock_handler = binder_setup
    archive = tmp / "chapter.zip"
    archive.write_bytes(b"not a real archive")
    out_dir.mkdir()
    target = out_dir / "000.jpg"
    target.write_bytes(b"old result")
    mock_handler.extract.side_effect = OSError("解压失败")

    with pytest.raises(OSError, match="解压失败"):
        binder.run([archive])

    assert target.read_bytes() == b"old result"


def test_binder_real_archives_with_same_logical_name(tmp_path, ext_config):
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first_archive = first_dir / "chapter.zip"
    second_archive = second_dir / "chapter.zip"
    with zipfile.ZipFile(first_archive, "w") as archive:
        archive.writestr("001.jpg", b"first archive image")
    with zipfile.ZipFile(second_archive, "w") as archive:
        archive.writestr("001.jpg", b"second archive image")

    out_dir = tmp_path / "output"
    binder = Binder(out_dir, ext_config, ArchiveHandler(ext_config))
    binder.run([first_archive, second_archive])

    assert (out_dir / "000.jpg").read_bytes() == b"first archive image"
    assert (out_dir / "001.jpg").read_bytes() == b"second archive image"


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
    options = {"prefix": "test_", "start_index": 5}
    binder.run([img1, archive, folder], options, progress_callback=progress_cb)

    dest_files = sorted(out_dir.iterdir())
    assert len(dest_files) == 3
    # 顺序：cover -> extracted -> folder
    assert dest_files[0].name.endswith(".jpg")
    assert dest_files[0].name.startswith("test_005")  # cover

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


def test_binder_publish_failure_restores_previous_outputs(binder_setup, monkeypatch):
    """后续发布失败时，已覆盖的旧输出必须恢复。"""
    import os

    binder, tmp, out_dir, _ = binder_setup
    first = tmp / "first.jpg"
    second = tmp / "second.jpg"
    first.write_bytes(b"new first")
    second.write_bytes(b"new second")
    out_dir.mkdir()
    (out_dir / "000.jpg").write_bytes(b"old first")
    (out_dir / "001.jpg").write_bytes(b"old second")
    real_replace = os.replace

    def fail_second_publish(source, target):
        source = Path(source)
        target = Path(target)
        if source.name == "00000002.jpg" and target.name == "001.jpg":
            raise PermissionError("publication failed")
        return real_replace(source, target)

    monkeypatch.setattr("koma.core.binder.os.replace", fail_second_publish)
    with pytest.raises(PermissionError, match="publication failed"):
        binder.run([first, second])

    assert (out_dir / "000.jpg").read_bytes() == b"old first"
    assert (out_dir / "001.jpg").read_bytes() == b"old second"
    assert not list(out_dir.glob(".koma-binder-*"))


def test_binder_rejects_hard_link_to_input(binder_setup):
    """输出目标即使换了路径名，也不能通过硬链接覆盖输入实体。"""
    binder, tmp, out_dir, _ = binder_setup
    source = tmp / "chapter" / "page.jpg"
    source.parent.mkdir()
    source.write_bytes(b"keep input")
    out_dir.mkdir()
    try:
        (out_dir / "000.jpg").hardlink_to(source)
    except OSError:
        pytest.skip("当前文件系统不支持硬链接")

    with pytest.raises(ValueError, match="输出目标与输入文件冲突"):
        binder.run([source])

    assert source.read_bytes() == b"keep input"
    assert (out_dir / "000.jpg").read_bytes() == b"keep input"
