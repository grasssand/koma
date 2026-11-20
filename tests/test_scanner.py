import errno
import shutil
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import pytest
from PIL import Image

from koma.core.image_processor import ImageInfo
from koma.core.scanner import Scanner


@pytest.fixture
def scanner_setup(tmp_path):
    root = tmp_path / "manga"
    root.mkdir()

    (root / "01.jpg").touch()
    (root / "02.png").touch()
    (root / "03.avif").touch()
    (root / "script.txt").touch()  # Junk
    (root / ".hidden").touch()

    return root


def test_scanner_classification(scanner_setup, ext_config, mock_image_processor):
    """测试基本的文件分类逻辑"""
    scanner = Scanner(scanner_setup, ext_config, mock_image_processor)
    results = list(scanner.run())

    assert len(results) == 1
    _, res = results[0]

    convert_names = [p.name for p in res.to_convert]
    copy_names = [p.name for p in res.to_copy]
    junk_names = [p.name for p in res.junk]

    assert "01.jpg" in convert_names
    assert "02.png" in convert_names
    assert "03.avif" in copy_names

    assert "script.txt" in junk_names
    assert ".hidden" in junk_names


def test_scanner_ad_detection_logic(scanner_setup, ext_config, mock_image_processor):
    """测试广告检测的核心逻辑"""
    (scanner_setup / "04.jpg").touch()
    (scanner_setup / "05.jpg").touch()
    (scanner_setup / "06.jpg").touch()

    def side_effect_qrcode(path):
        return bool("05" in path.name or "06" in path.name)

    mock_image_processor.has_ad_qrcode.side_effect = side_effect_qrcode
    mock_image_processor.analyze.return_value = ImageInfo(False, False)

    scanner = Scanner(scanner_setup, ext_config, mock_image_processor)
    # 启用广告扫描
    options = {"enable_ad_scan": True}
    results = list(scanner.run(options=options))

    res = results[0][1]
    ads_names = [p.name for p in res.ads]
    convert_names = [p.name for p in res.to_convert]

    # 验证广告被识别
    assert "06.jpg" in ads_names
    assert "05.jpg" in ads_names
    # 验证正文没有被误判
    assert "04.jpg" in convert_names
    assert "04.jpg" not in ads_names


def test_scanner_stop_on_special(scanner_setup, ext_config, mock_image_processor):
    """测试遇到动图/灰度图停止扫描"""
    (scanner_setup / "end.gif").touch()

    mock_image_processor.analyze.return_value = ImageInfo(is_animated=True)

    scanner = Scanner(scanner_setup, ext_config, mock_image_processor)
    options = {"enable_ad_scan": True}
    list(scanner.run(options=options))

    mock_image_processor.has_ad_qrcode.assert_not_called()


@pytest.fixture
def archive_options(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    return {
        "enable_archive_scan": True,
        "archive_out_path": str(output),
        "repack": True,
        "pack_format": "cbz",
    }


def test_scanner_skip_clean_archive(
    scanner_setup, ext_config, mock_image_processor, archive_options
):
    """测试：如果压缩包内没有清理任何文件，应该跳过重打包"""
    (scanner_setup / "clean.zip").touch()

    with (
        patch("koma.core.scanner.ArchiveHandler"),
        patch.object(
            Scanner, "_clean_directory_recursive", return_value=0
        ) as mock_clean,
    ):
        scanner = Scanner(scanner_setup, ext_config, mock_image_processor)
        results = list(scanner.run(options=archive_options))

        processed_count = 0
        for _, res in results:
            processed_count += res.processed_archives

        assert processed_count == 0

        scanner.archive_handler.pack.assert_not_called()  # type: ignore
        mock_clean.assert_called()


def test_scanner_process_dirty_archive(
    scanner_setup, ext_config, mock_image_processor, archive_options
):
    """脏包成功发布后才计入成功，原包保持不变。"""
    archive = scanner_setup / "dirty.zip"
    with ZipFile(archive, "w") as zf:
        zf.writestr("page.jpg", b"page")
        zf.writestr("ad.url", b"junk")
    original = archive.read_bytes()
    scanner = Scanner(scanner_setup, ext_config, mock_image_processor)
    scanner.archive_handler.seven_zip = None
    results = list(scanner.run(options=archive_options))
    assert sum(res.processed_archives for _, res in results) == 1
    assert sum(res.failed_archives for _, res in results) == 0
    assert archive.read_bytes() == original
    with ZipFile(Path(archive_options["archive_out_path"]) / "dirty.cbz") as zf:
        assert zf.namelist() == ["page.jpg"]
        assert zf.read("page.jpg") == b"page"


def test_scanner_archive_disk_space_check(
    scanner_setup, ext_config, mock_image_processor, archive_options, caplog
):
    """测试：磁盘空间不足时跳过处理"""
    (scanner_setup / "big.zip").touch()

    # 模拟 zip 文件大小 100MB
    with patch.object(Path, "stat") as mock_stat:
        mock_stat.return_value.st_size = 100 * 1024 * 1024

        # 模拟磁盘剩余空间 10MB (不足 2.5倍)
        with patch("shutil.disk_usage") as mock_usage:
            mock_usage.return_value.free = 10 * 1024 * 1024

            scanner = Scanner(scanner_setup, ext_config, mock_image_processor)
            list(scanner.run(options=archive_options))

            # 验证错误日志
            assert "磁盘空间不足" in caplog.text


def test_scanner_infinite_loop_prevention(
    scanner_setup, ext_config, mock_image_processor
):
    """测试：输出目录在输入目录内部时，应避免递归扫描输出目录"""
    output_dir = scanner_setup / "output"
    output_dir.mkdir()

    (output_dir / "should_ignore.jpg").touch()
    (scanner_setup / "normal.jpg").touch()

    options = {
        "enable_archive_scan": True,
        "archive_out_path": str(output_dir),
    }

    scanner = Scanner(scanner_setup, ext_config, mock_image_processor)
    results = list(scanner.run(options=options))

    # 收集所有扫描到的文件
    all_files = []
    for _, res in results:
        all_files.extend(res.to_convert)
        all_files.extend(res.to_copy)

    file_names = [f.name for f in all_files]

    assert "normal.jpg" in file_names
    assert "should_ignore.jpg" not in file_names


def test_process_archive_runtime_disk_full(
    scanner_setup, ext_config, mock_image_processor, archive_options, caplog
):
    """测试在处理过程中（如解压/移动时）突然发生磁盘空间不足异常 (Errno 28)"""
    (scanner_setup / "bomb.zip").touch()

    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value.free = 10**12  # 1TB free

        with patch("koma.core.scanner.ArchiveHandler") as MockHandlerClass:
            mock_handler_instance = MockHandlerClass.return_value

            disk_full_error = OSError(errno.ENOSPC, "No space left on device")
            mock_handler_instance.extract.side_effect = disk_full_error

            scanner = Scanner(scanner_setup, ext_config, mock_image_processor)

            list(scanner.run(options=archive_options))

            assert "磁盘空间耗尽" in caplog.text
            assert "bomb.zip" in caplog.text


def test_process_archive_generic_io_error(
    scanner_setup, ext_config, mock_image_processor, archive_options, caplog
):
    """测试普通 IO 错误"""
    (scanner_setup / "corrupt.zip").touch()

    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value.free = 10**12

        with patch("koma.core.scanner.ArchiveHandler") as MockHandlerClass:
            mock_handler_instance = MockHandlerClass.return_value

            perm_error = OSError(errno.EACCES, "Permission denied")
            mock_handler_instance.extract.side_effect = perm_error

            scanner = Scanner(scanner_setup, ext_config, mock_image_processor)
            list(scanner.run(options=archive_options))

            assert "处理压缩包IO错误" in caplog.text
            assert "磁盘空间耗尽" not in caplog.text


def test_clean_directory_recursive_real_logic(
    ext_config, mock_image_processor, tmp_path
):
    """
    测试 _clean_directory_recursive 的内部逻辑：
    验证循环、删除垃圾、删除广告、计数是否正确。
    """
    target_dir = tmp_path / "extract_temp"
    target_dir.mkdir()

    # 垃圾文件 (should be deleted)
    junk_file = target_dir / "thumbs.db"
    junk_file.touch()

    # 广告图片 (should be deleted)
    ad_file = target_dir / "zz_ad.jpg"
    ad_file.touch()

    # 正常图片 (should keep)
    normal_file = target_dir / "01_chapter.jpg"
    normal_file.touch()

    # 子文件夹里的垃圾
    sub_dir = target_dir / "subdir"
    sub_dir.mkdir()
    sub_junk = sub_dir / ".DS_Store"
    sub_junk.touch()

    # 模拟广告检测
    def side_effect_qrcode(path):
        return "ad" in path.name

    mock_image_processor.has_ad_qrcode.side_effect = side_effect_qrcode
    mock_image_processor.analyze.return_value = ImageInfo(False, False)

    scanner = Scanner(tmp_path, ext_config, mock_image_processor)

    deleted_count = scanner._clean_directory_recursive(target_dir, True, False)

    # 预期删除: thumbs.db, ad_01.jpg, .DS_Store
    assert deleted_count == 3

    # 验证文件物理状态
    assert not junk_file.exists(), "垃圾文件未被删除"
    assert not ad_file.exists(), "广告文件未被删除"
    assert not sub_junk.exists(), "子文件夹垃圾未被删除"
    assert normal_file.exists(), "正常文件被误删"


@pytest.fixture
def custom_ad_dir(tmp_path):
    """生成一个包含两张测试广告的自定义图库目录"""
    ad_dir = tmp_path / "custom_ads"
    ad_dir.mkdir()

    # 生成一张具有明显特征的广告图 (左半白，右半黑)
    img_pattern = Image.new("L", (100, 100), color=255)
    for y in range(100):
        for x in range(50, 100):  # 将右半边涂黑
            img_pattern.putpixel((x, y), 0)
    img_pattern.save(ad_dir / "pattern_ad.jpg")

    # 生成一张纯黑色的广告图
    img_black = Image.new("RGB", (50, 50), "black")
    img_black.save(ad_dir / "black_ad.png")

    return str(ad_dir)


def test_scanner_custom_ad_matching(
    scanner_setup, ext_config, mock_image_processor, custom_ad_dir
):
    """测试自定义广告"""

    # 复制广告图
    shutil.copy(
        Path(custom_ad_dir) / "pattern_ad.jpg", scanner_setup / "08_pattern_ad.jpg"
    )

    # 放一张正常的白色的图片
    Image.new("RGB", (50, 50), "white").save(scanner_setup / "09_white_page.jpg")
    # 放一张正常的灰色图片
    Image.new("RGB", (50, 50), "gray").save(scanner_setup / "01_normal_page.jpg")

    mock_image_processor.analyze.return_value = ImageInfo(False, False)
    mock_image_processor.has_ad_qrcode.return_value = False

    scanner = Scanner(scanner_setup, ext_config, mock_image_processor)
    options = {
        "enable_ad_scan": True,
        "enable_custom_ad_scan": True,
        "custom_ad_dir": custom_ad_dir,
    }

    results = list(scanner.run(options=options))
    res = results[0][1]

    ads_names = [p.name for p in res.ads]
    convert_names = [p.name for p in res.to_convert]

    # 应被识别为广告
    assert "08_pattern_ad.jpg" in ads_names

    # 不被视为广告
    assert "09_white_page.jpg" not in ads_names
    assert "09_white_page.jpg" in convert_names

    assert "01_normal_page.jpg" not in ads_names
    assert "01_normal_page.jpg" in convert_names


def test_archive_repack_keeps_dotted_stem(tmp_path, ext_config, mock_image_processor):
    """带小数点的归档名完整保留。"""
    source = tmp_path / "src"
    source.mkdir()
    with ZipFile(source / "C99 doujin v1.2.zip", "w") as zf:
        zf.writestr("page.jpg", b"page")
        zf.writestr("ad.url", b"junk")
    scanner = Scanner(source, ext_config, mock_image_processor)
    scanner.archive_handler.seven_zip = None
    options = {
        "enable_archive_scan": True,
        "archive_out_path": str(tmp_path / "out"),
        "repack": True,
        "pack_format": "cbz",
    }
    list(scanner.run(options))
    with ZipFile(tmp_path / "out" / "C99 doujin v1.2.cbz") as zf:
        assert zf.read("page.jpg") == b"page"


def test_system_junk_config_is_honoured(tmp_path, ext_config, mock_image_processor):
    """
    system_junk 必须真正生效：即使扩展名被加进支持列表，也要判为垃圾。
    （旧实现只按扩展名判断，这个配置项形同摆设）
    """
    # 把 .db 加进可转换格式，模拟"扩展名本身合法"的情况
    ext_config.convert.add(".db")

    scanner = Scanner(tmp_path, ext_config, mock_image_processor)

    assert scanner._is_junk(tmp_path / "Thumbs.db") is True
    assert scanner._is_junk(tmp_path / "desktop.ini") is True
    # 白名单优先级不受影响
    assert scanner._is_junk(tmp_path / "ComicInfo.xml") is False


def test_macosx_dir_is_collected_as_junk(tmp_path, ext_config, mock_image_processor):
    """__MACOSX 是目录，必须整体列为待清理项，且不再被递归扫描"""
    work_dir = tmp_path / "manga"
    work_dir.mkdir()
    (work_dir / "01.jpg").touch()

    macosx = work_dir / "__MACOSX"
    macosx.mkdir()
    (macosx / "._01.jpg").touch()

    scanner = Scanner(work_dir, ext_config, mock_image_processor)
    results = list(scanner.run())

    assert len(results) == 1
    _, res = results[0]

    junk_names = [p.name for p in res.junk]
    assert "__MACOSX" in junk_names
    # 目录被整体跳过，内部文件不再单独列出
    assert "._01.jpg" not in junk_names
    # 正常图片不受影响
    assert [p.name for p in res.to_convert] == ["01.jpg"]


def test_ad_detection_covers_first_image(tmp_path, ext_config, mock_image_processor):
    """单页文件夹也要检测广告（旧实现 range(len-1, 0, -1) 永远漏掉索引 0）"""
    work_dir = tmp_path / "single_page"
    work_dir.mkdir()
    (work_dir / "only.jpg").touch()

    mock_image_processor.has_ad_qrcode.return_value = True

    scanner = Scanner(work_dir, ext_config, mock_image_processor)
    results = list(scanner.run(options={"enable_ad_scan": True}))

    assert len(results) == 1
    _, res = results[0]
    assert [p.name for p in res.ads] == ["only.jpg"]


def test_failed_repack_preserves_existing_output(
    tmp_path, ext_config, mock_image_processor
):
    source = tmp_path / "source"
    source.mkdir()
    with ZipFile(source / "book.zip", "w") as zf:
        zf.writestr("ad.url", b"junk")
    output = tmp_path / "out"
    output.mkdir()
    old = output / "book.zip"
    old.write_bytes(b"old output")
    scanner = Scanner(source, ext_config, mock_image_processor)

    def fail_pack(content, staged, **kwargs):
        staged.write_bytes(b"partial")
        return False

    with patch.object(scanner.archive_handler, "pack", side_effect=fail_pack):
        results = list(
            scanner.run({"enable_archive_scan": True, "archive_out_path": str(output)})
        )
    assert sum(res.processed_archives for _, res in results) == 0
    assert sum(res.failed_archives for _, res in results) == 1
    assert old.read_bytes() == b"old output"
    assert sorted(p.name for p in output.iterdir()) == ["book.zip"]


@pytest.mark.parametrize("repack", [True, False])
def test_scanner_output_conflicts_keep_both_versions(
    tmp_path, ext_config, mock_image_processor, repack
):
    source = tmp_path / "source"
    source.mkdir()
    with ZipFile(source / "book.zip", "w") as zf:
        zf.writestr("page.jpg", b"new page")
        zf.writestr("ad.url", b"junk")
    output = tmp_path / "out"
    output.mkdir()
    if repack:
        (output / "book.zip").write_bytes(b"old archive")
    else:
        (output / "book").mkdir()
        (output / "book" / "page.jpg").write_bytes(b"old page")
    scanner = Scanner(source, ext_config, mock_image_processor)
    scanner.archive_handler.seven_zip = None
    results = list(
        scanner.run(
            {
                "enable_archive_scan": True,
                "archive_out_path": str(output),
                "repack": repack,
            }
        )
    )
    assert sum(res.processed_archives for _, res in results) == 1
    if repack:
        assert (output / "book.zip").read_bytes() == b"old archive"
        new = next(output.glob("book_*.zip"))
        with ZipFile(new) as zf:
            assert zf.read("page.jpg") == b"new page"
    else:
        assert (output / "book" / "page.jpg").read_bytes() == b"old page"
        new = next(output.glob("book_*"))
        assert (new / "page.jpg").read_bytes() == b"new page"


def test_clean_failure_is_not_reported_as_clean_archive(
    tmp_path, ext_config, mock_image_processor
):
    with ZipFile(tmp_path / "book.zip", "w") as zf:
        zf.writestr("junk.url", b"junk")
    scanner = Scanner(tmp_path, ext_config, mock_image_processor)
    with patch.object(
        scanner, "_clean_directory_recursive", side_effect=PermissionError("denied")
    ):
        results = list(
            scanner.run(
                {"enable_archive_scan": True, "archive_out_path": str(tmp_path / "out")}
            )
        )
    assert sum(res.failed_archives for _, res in results) == 1
    assert not (tmp_path / "out").exists()
