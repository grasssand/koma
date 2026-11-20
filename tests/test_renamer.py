import csv
import zipfile
from unittest.mock import patch

import pytest

from koma.core.file_safety import move_no_replace
from koma.core.renamer import KOMA_TMP_PREFIX, RenameBatchError, Renamer
from koma.core.scanner import ScanResult


@pytest.fixture
def renamer_setup(tmp_path):
    work_dir = tmp_path / "chapter_1"
    work_dir.mkdir()
    (work_dir / "10.avif").touch()
    (work_dir / "cover.webp").touch()
    (work_dir / "2.png").touch()
    (work_dir / "001.jpg").touch()
    return work_dir


def test_renamer_success(renamer_setup, ext_config, mock_image_processor):
    """测试常规重命名逻辑"""
    work_dir = renamer_setup

    with patch("koma.core.renamer.Scanner") as MockScanner:
        res = ScanResult()
        res.to_convert = [work_dir / "10.avif", work_dir / "cover.webp"]
        res.to_copy = [work_dir / "2.png", work_dir / "001.jpg"]

        mock_instance = MockScanner.return_value
        mock_instance.run.return_value = iter([(work_dir, res)])

        renamer = Renamer(work_dir, ext_config, mock_image_processor)
        renamer.run({"prefix": "test_", "start_index": 5})

        # 验证封面置顶 + 自然排序
        assert (work_dir / "test_005.webp").exists()  # cover
        assert (work_dir / "test_006.jpg").exists()  # 001
        assert (work_dir / "test_007.png").exists()  # 2
        assert (work_dir / "test_008.avif").exists()  # 10


def test_renamer_skip_single_cover(tmp_path, ext_config, mock_image_processor):
    """测试仅含单张 Cover 图时跳过"""
    work_dir = tmp_path / "cover_only"
    work_dir.mkdir()
    cover_file = work_dir / "cover.jpg"
    cover_file.touch()

    with patch("koma.core.renamer.Scanner") as MockScanner:
        res = ScanResult()
        res.to_copy = [cover_file]

        mock_instance = MockScanner.return_value
        mock_instance.run.return_value = iter([(work_dir, res)])

        renamer = Renamer(work_dir, ext_config, mock_image_processor)
        renamer.run()

        # 验证未被重命名
        assert cover_file.exists()
        assert not (work_dir / "000.jpg").exists()


def test_renamer_csv_export(renamer_setup, ext_config, mock_image_processor):
    """测试 CSV 导出"""
    work_dir = renamer_setup
    with patch("koma.core.renamer.Scanner") as MockScanner:
        res = ScanResult()
        res.to_convert = [work_dir / "10.avif"]

        mock_instance = MockScanner.return_value
        mock_instance.run.return_value = iter([(work_dir, res)])

        renamer = Renamer(work_dir, ext_config, mock_image_processor)
        renamer.run(options={"export_csv": True})

        csv_files = list(work_dir.glob("rename_report_*.csv"))
        assert len(csv_files) == 1

        with open(csv_files[0], encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            rows = list(reader)
            assert len(rows) >= 2  # Header + 1 row


def test_renamer_archive_processing(tmp_path, ext_config, mock_image_processor):
    """真实重命名并打包，目标冲突时保留已有内容。"""
    archive_file = tmp_path / "test.zip"
    with zipfile.ZipFile(archive_file, "w") as zf:
        zf.writestr("p1.png", b"first")
        zf.writestr("p2.jpg", b"second")
    target_file = tmp_path / "test.cbz"
    target_file.write_bytes(b"existing")
    renamer = Renamer(tmp_path, ext_config, mock_image_processor)
    renamer.archive_handler.seven_zip = None

    with patch("koma.core.renamer.send2trash") as trash:
        rows = renamer._process_archive(archive_file, "cbz")

    assert len(rows) == 2
    assert target_file.read_bytes() == b"existing"
    generated = list(tmp_path.glob("test_*.cbz"))
    assert len(generated) == 1
    with zipfile.ZipFile(generated[0]) as zf:
        assert zf.read("000.png") == b"first"
        assert zf.read("001.jpg") == b"second"
    assert str(generated[0]) in rows[0][0]
    trash.assert_called_once_with(str(archive_file))
    assert list(tmp_path.glob(f"{KOMA_TMP_PREFIX}*")) == []


def test_rename_rollback_on_failure(tmp_path, ext_config, mock_image_processor):
    """
    测试阶段 2 中途失败时能完整回滚：
    文件名与内容都必须恢复原状，且不能残留 koma_tmp_* 文件。
    """
    work_dir = tmp_path / "rollback"
    work_dir.mkdir()
    targets = [work_dir / "10.jpg", work_dir / "20.jpg", work_dir / "30.jpg"]
    for i, p in enumerate(targets):
        p.write_bytes(f"content-{i}".encode())

    call_count = 0

    def flaky_move(source, target):
        """前 3 次暂存正常，第 5 次发布失败。"""
        nonlocal call_count
        call_count += 1
        if call_count == 5:
            raise OSError("模拟文件被占用")
        move_no_replace(source, target)

    renamer = Renamer(work_dir, ext_config, mock_image_processor)

    with (
        patch("koma.core.renamer.move_no_replace", side_effect=flaky_move),
        pytest.raises(RenameBatchError) as error,
    ):
        renamer._rename_files_in_dir(work_dir, targets, return_csv=True)

    assert error.value.rows == []

    # 原始文件名与内容都完好
    for i, p in enumerate(targets):
        assert p.exists(), f"{p.name} 未被还原"
        assert p.read_bytes() == f"content-{i}".encode()

    # 没有留下中间态文件
    assert list(work_dir.glob(f"{KOMA_TMP_PREFIX}*")) == []
    assert not (work_dir / "000.jpg").exists()


def test_rename_temp_prefix_is_not_junk(ext_config, mock_image_processor, tmp_path):
    """中间态文件前缀不能以 "." 开头，否则会被扫描清理当作杂项删除"""
    from koma.core.scanner import Scanner

    assert not KOMA_TMP_PREFIX.startswith(".")

    work_dir = tmp_path / "junk_check"
    work_dir.mkdir()
    (work_dir / f"{KOMA_TMP_PREFIX}abc.jpg").touch()
    (work_dir / ".tmp_abc.jpg").touch()

    scanner = Scanner(work_dir, ext_config, mock_image_processor)

    # 旧的 ".tmp_" 会被判为杂项（这正是原先的数据丢失链路）
    assert scanner._is_junk(work_dir / ".tmp_abc.jpg") is True
    # 新的前缀会被当作正常图片，不会被误删
    assert scanner._is_junk(work_dir / f"{KOMA_TMP_PREFIX}abc.jpg") is False


def test_archive_original_kept_when_move_fails(
    tmp_path, ext_config, mock_image_processor
):
    """新包无法发布时，原包与映射报告都不能被提前提交。"""
    archive_file = tmp_path / "test.zip"
    with zipfile.ZipFile(archive_file, "w") as zf:
        zf.writestr("p1.jpg", b"original")
    original = archive_file.read_bytes()
    renamer = Renamer(tmp_path, ext_config, mock_image_processor)
    renamer.archive_handler.seven_zip = None

    def fail_publication(source, target):
        if source.suffix == ".cbz":
            assert source.parent.parent == archive_file.parent
            raise OSError("磁盘已满")
        move_no_replace(source, target)

    result = ScanResult()
    result.archives = [archive_file]
    with (
        patch("koma.core.renamer.Scanner") as scanner,
        patch("koma.core.renamer.send2trash") as trash,
        patch("koma.core.renamer.move_no_replace", side_effect=fail_publication),
        patch.object(renamer, "_write_csv_report") as report,
    ):
        scanner.return_value.run.return_value = iter([(tmp_path, result)])
        with pytest.raises(RenameBatchError) as error:
            renamer.run(
                {
                    "enable_archive_scan": True,
                    "pack_format": "cbz",
                    "export_csv": True,
                }
            )

    assert error.value.rows == []
    report.assert_not_called()
    trash.assert_not_called()
    assert archive_file.read_bytes() == original
    assert list(tmp_path.glob(f"{KOMA_TMP_PREFIX}*")) == []
    assert not (tmp_path / "test.cbz").exists()


@pytest.mark.parametrize("options", [{"prefix": "../"}, {"pack_format": "../zip"}])
def test_invalid_options_fail_before_scanning(
    tmp_path, ext_config, mock_image_processor, options
):
    """非法前缀或格式必须在扫描器可能清理文件之前拒绝。"""
    renamer = Renamer(tmp_path, ext_config, mock_image_processor)
    with patch("koma.core.renamer.Scanner") as scanner, pytest.raises(ValueError):
        renamer.run(options)
    scanner.assert_not_called()


@pytest.mark.parametrize("start_index", [-1, True, False, 1.5, "0", None])
def test_invalid_start_index_fails_before_scanning_or_renaming(
    tmp_path, ext_config, mock_image_processor, start_index
):
    """非整数、布尔值和负数必须在扫描或改名之前拒绝。"""
    source = tmp_path / "page.jpg"
    source.write_bytes(b"original")
    renamer = Renamer(tmp_path, ext_config, mock_image_processor)
    with (
        patch("koma.core.renamer.Scanner") as scanner,
        pytest.raises(ValueError, match="起始序号"),
    ):
        renamer.run({"start_index": start_index})
    scanner.assert_not_called()
    with pytest.raises(ValueError, match="起始序号"):
        renamer._rename_files_in_dir(tmp_path, [source], start_index=start_index)
    assert source.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [source]


def test_rename_collision_preserves_unselected_file(
    tmp_path, ext_config, mock_image_processor
):
    """POSIX rename 会覆盖目标；核心逻辑必须明确禁止这种替换。"""
    source = tmp_path / "page.jpg"
    source.write_bytes(b"page")
    target = tmp_path / "000.jpg"
    target.write_bytes(b"user")
    renamer = Renamer(tmp_path, ext_config, mock_image_processor)
    with pytest.raises(FileExistsError):
        renamer._rename_files_in_dir(tmp_path, [source], True)
    assert source.read_bytes() == b"page"
    assert target.read_bytes() == b"user"
    assert list(tmp_path.glob(f"{KOMA_TMP_PREFIX}*")) == []


def test_nested_rename_rollback_uses_full_original_paths(
    tmp_path, ext_config, mock_image_processor
):
    """嵌套目录出现同名文件时，也必须各自回到原目录。"""
    sources = []
    for name in ("a", "b"):
        folder = tmp_path / name
        folder.mkdir()
        source = folder / "page.jpg"
        source.write_text(name)
        sources.append(source)
    calls = 0

    def fail_second_publication(source, target):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("无法发布")
        move_no_replace(source, target)

    renamer = Renamer(tmp_path, ext_config, mock_image_processor)
    with (
        patch("koma.core.renamer.move_no_replace", side_effect=fail_second_publication),
        pytest.raises(RenameBatchError) as error,
    ):
        renamer._rename_files_in_dir(tmp_path, sources, True)
    assert error.value.rows == []
    for source in sources:
        assert source.read_text() == source.parent.name
    assert not (tmp_path / "page.jpg").exists()
    assert not list(tmp_path.rglob(f"{KOMA_TMP_PREFIX}*"))


def test_rollback_does_not_replace_new_user_file(
    tmp_path, ext_config, mock_image_processor
):
    """回滚时原位置被其他文件占用，保留用户文件与暂存中的原数据。"""
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    calls = 0

    def collide_during_publication(source, target):
        nonlocal calls
        calls += 1
        if calls == 4:
            first.write_bytes(b"new user data")
            raise OSError("发布失败")
        move_no_replace(source, target)

    renamer = Renamer(tmp_path, ext_config, mock_image_processor)
    with (
        patch(
            "koma.core.renamer.move_no_replace", side_effect=collide_during_publication
        ),
        pytest.raises(RenameBatchError) as error,
    ):
        renamer._rename_files_in_dir(tmp_path, [first, second], True)
    assert first.read_bytes() == b"new user data"
    assert second.read_bytes() == b"second"
    retained = list(tmp_path.glob(f"{KOMA_TMP_PREFIX}*"))
    assert len(retained) == 1
    assert retained[0].read_bytes() == b"first"
    assert error.value.rows == [[str(tmp_path), str(first), str(retained[0])]]


def test_batch_failure_preserves_successful_report_rows(
    tmp_path, ext_config, mock_image_processor
):
    """后续目录失败不能丢掉已成功目录的映射，也不能汇报整批成功。"""
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    good.mkdir()
    bad.mkdir()
    (good / "page.jpg").write_bytes(b"good")
    (bad / "page.jpg").write_bytes(b"bad")
    (bad / "000.jpg").write_bytes(b"keep")
    good_result = ScanResult()
    good_result.to_copy = [good / "page.jpg"]
    bad_result = ScanResult()
    bad_result.to_copy = [bad / "page.jpg"]
    renamer = Renamer(tmp_path, ext_config, mock_image_processor)
    with patch("koma.core.renamer.Scanner") as scanner:
        scanner.return_value.run.return_value = iter(
            [(good, good_result), (bad, bad_result)]
        )
        with pytest.raises(RenameBatchError) as error:
            renamer.run({"export_csv": True})
    assert error.value.rows == [[str(good), "page.jpg", "000.jpg"]]
    assert (good / "000.jpg").read_bytes() == b"good"
    reports = list(tmp_path.glob("rename_report_*.csv"))
    assert len(reports) == 1
    with reports[0].open(encoding="utf-8-sig", newline="") as stream:
        assert list(csv.reader(stream))[1:] == error.value.rows


def test_archive_publication_retries_racing_collisions(
    tmp_path, ext_config, mock_image_processor
):
    """检查目标后其他进程抢先创建文件时，继续换名且不覆盖。"""
    archive = tmp_path / "comic.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("page.jpg", b"image")
    renamer = Renamer(tmp_path, ext_config, mock_image_processor)
    renamer.archive_handler.seven_zip = None
    collisions = []

    def race(source, target):
        if source.suffix == ".cbz" and len(collisions) < 2:
            target.write_bytes(b"other user")
            collisions.append(target)
        move_no_replace(source, target)

    with (
        patch("koma.core.renamer.move_no_replace", side_effect=race),
        patch("koma.core.renamer.send2trash") as trash,
    ):
        rows = renamer._process_archive(archive, "cbz")
    assert len(rows) == 1
    assert len(collisions) == 2
    assert all(path.read_bytes() == b"other user" for path in collisions)
    assert len(list(tmp_path.glob("*.cbz"))) == 3
    trash.assert_called_once()


def test_archive_noop_does_not_repack_or_trash(
    tmp_path, ext_config, mock_image_processor
):
    """已正确编号的归档保持原样，即使用户选择不同输出格式。"""
    archive = tmp_path / "comic.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("000.jpg", b"image")
    original = archive.read_bytes()
    renamer = Renamer(tmp_path, ext_config, mock_image_processor)
    with (
        patch.object(renamer.archive_handler, "pack") as pack,
        patch("koma.core.renamer.send2trash") as trash,
    ):
        assert renamer._process_archive(archive, "cbz") == []
    pack.assert_not_called()
    trash.assert_not_called()
    assert archive.read_bytes() == original


def test_trash_failure_reports_published_archive_rows(
    tmp_path, ext_config, mock_image_processor
):
    """新包已发布但回收失败时，返回失败状态并保留有效映射。"""
    archive = tmp_path / "comic.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("page.jpg", b"image")
    renamer = Renamer(tmp_path, ext_config, mock_image_processor)
    renamer.archive_handler.seven_zip = None
    with (
        patch("koma.core.renamer.send2trash", side_effect=OSError("回收站不可用")),
        pytest.raises(RenameBatchError) as error,
    ):
        renamer._process_archive(archive, "cbz")
    assert len(error.value.rows) == 1
    assert archive.exists()
    with zipfile.ZipFile(archive.with_suffix(".cbz")) as zf:
        assert zf.read("000.jpg") == b"image"
