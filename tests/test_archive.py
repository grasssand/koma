import shutil
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from koma.core.archive import ArchiveHandler

MINIMAL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xff"
    b"\xff?\x00\x05\xfe\x02\xfe\xa75\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
def handler_no_7z(ext_config):
    """强制使用 Python 原生 Zip 的 Handler"""
    with (
        patch("shutil.which", return_value=None),
        patch.object(ArchiveHandler, "_find_7z", return_value=None),
    ):
        return ArchiveHandler(ext_config)


@pytest.fixture
def handler_with_7z(ext_config):
    """强制认为有 7z 的 Handler"""
    with patch.object(ArchiveHandler, "_find_7z", return_value="/usr/bin/7z"):
        return ArchiveHandler(ext_config)


def test_init_detection(ext_config):
    """测试初始化时的 7z 检测逻辑"""
    with patch("shutil.which", return_value="/bin/7z"):
        h = ArchiveHandler(ext_config)
        assert h.seven_zip == "/bin/7z"


def test_extract_smart_folder_nested(tmp_path, handler_no_7z):
    """测试智能解压：嵌套结构"""
    archive_path = tmp_path / "comic.zip"
    temp_root = tmp_path / "temp"

    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("InnerFolder/01.jpg", b"image")
        zf.writestr("__MACOSX/info", b"junk")
        zf.writestr("Thumbs.db", b"junk")

    result_path = handler_no_7z.extract(archive_path, temp_root)

    assert result_path.name == "InnerFolder"
    assert result_path.is_relative_to(temp_root)
    assert (result_path / "01.jpg").read_bytes() == b"image"


def test_extract_smart_folder_flat(tmp_path, handler_no_7z):
    """测试智能解压：散乱结构"""
    archive_path = tmp_path / "comic.zip"
    temp_root = tmp_path / "temp"

    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("01.jpg", b"first")
        zf.writestr("02.jpg", b"second")

    result_path = handler_no_7z.extract(archive_path, temp_root)

    assert result_path.name == "comic"
    assert result_path.is_relative_to(temp_root)
    assert (result_path / "01.jpg").read_bytes() == b"first"


def test_7z_command_generation(tmp_path, handler_with_7z):
    """测试 7z 命令生成是否正确"""
    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "out.cbz"

    with patch("subprocess.run") as mock_run:
        handler_with_7z.pack(src, out, fmt="cbz", level="normal")

        args, kwargs = mock_run.call_args
        cmd = args[0]

        assert cmd[0] == "/usr/bin/7z"
        assert "a" in cmd
        assert "-tzip" in cmd  # cbz 对应 zip
        assert "-mx=5" in cmd
        assert kwargs["cwd"] == str(src)


def test_real_zip_pack_filtering(tmp_path, handler_no_7z):
    """测试真实打包：验证垃圾文件过滤功能"""
    src_dir = tmp_path / "source"
    src_dir.mkdir()

    (src_dir / "01.jpg").write_bytes(b"image")
    (src_dir / "info.txt").write_text("info")
    (src_dir / "Thumbs.db").touch()
    (src_dir / "desktop.ini").touch()
    (src_dir / ".ds_store").touch()

    out_cbz = tmp_path / "output.cbz"

    success = handler_no_7z.pack(src_dir, out_cbz, fmt="cbz")

    assert success is True
    assert out_cbz.exists()

    with zipfile.ZipFile(out_cbz, "r") as zf:
        names = zf.namelist()
        assert "01.jpg" in names
        assert "info.txt" in names
        # 确认垃圾文件没被打包进去
        assert "Thumbs.db" not in names
        assert "desktop.ini" not in names
        assert ".ds_store" not in names


def test_real_zip_extract(tmp_path, handler_no_7z):
    """测试真实解压"""
    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("folder/a.txt", "content a")
        zf.writestr("b.txt", "content b")

    extract_root = tmp_path / "extract_root"
    result_path = handler_no_7z.extract(zip_path, extract_root)

    assert result_path.name == "test"
    assert (result_path / "folder" / "a.txt").read_text() == "content a"
    assert (result_path / "b.txt").read_text() == "content b"


def test_extract_cover_native_zip(tmp_path, handler_no_7z):
    """测试原生 zipfile 提取封面，自然排序"""
    zip_path = tmp_path / "test_cover.cbz"

    with zipfile.ZipFile(zip_path, "w") as zf:
        # 故意打乱写入顺序，测试 natsort 是否生效
        zf.writestr("02.png", MINIMAL_PNG)
        zf.writestr("01.png", MINIMAL_PNG)
        zf.writestr("info.txt", b"text data")

    img = handler_no_7z.extract_cover(zip_path)

    assert img is not None
    assert img.size == (1, 1)  # 成功解析出真实的图像属性
    assert img.format in ("PNG", None)


def test_extract_cover_7z_fallback(tmp_path, handler_with_7z):
    """测试 7z 内存提取封面 (针对 rar/7z)"""
    archive_path = tmp_path / "test_cover.rar"
    archive_path.touch()

    # 伪造 7z l -slt (列表信息输出)
    mock_list_res = MagicMock()
    mock_list_res.returncode = 0
    mock_list_res.stdout = "Path = 02.png\nPath = 01.png\nPath = info.txt\n"

    # 伪造 7z e -so (内存流提取)
    mock_ext_res = MagicMock()
    mock_ext_res.returncode = 0
    mock_ext_res.stdout = MINIMAL_PNG

    with patch("subprocess.run", side_effect=[mock_list_res, mock_ext_res]) as mock_run:
        img = handler_with_7z.extract_cover(archive_path)

        assert img is not None
        assert img.size == (1, 1)

        assert mock_run.call_count == 2

        # 验证第一次调用是列出文件
        args_list = mock_run.call_args_list[0][0][0]
        assert "l" in args_list
        assert "-slt" in args_list

        # 验证第二次调用是解压，并且精准抓取了 "01.png"
        args_ext = mock_run.call_args_list[1][0][0]
        assert "e" in args_ext
        assert "-so" in args_ext
        assert "01.png" in args_ext


def test_extract_cover_no_images(tmp_path, handler_no_7z):
    """测试当压缩包内没有合法图片时返回 None"""
    zip_path = tmp_path / "no_images.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("info.txt", b"text data")
        zf.writestr("data.bin", b"binary data")

    img = handler_no_7z.extract_cover(zip_path)
    assert img is None


has_7z = shutil.which("7z") is not None


@pytest.mark.skipif(not has_7z, reason="系统未安装 7z，跳过真实 7z 测试")
def test_real_7z_pack_and_extract(tmp_path, ext_config):
    """真实调用系统 7z 进行打包和解压"""
    handler = ArchiveHandler(ext_config)

    src_dir = tmp_path / "src_7z"
    src_dir.mkdir()
    (src_dir / "cover.jpg").write_bytes(b"data")
    (src_dir / "junk.db").touch()  # 假设这不是垃圾文件

    archive_path = tmp_path / "test.7z"
    success_pack = handler.pack(src_dir, archive_path, fmt="7z")
    assert success_pack is True
    assert archive_path.exists()

    extract_root = tmp_path / "out_7z"
    result_path = handler.extract(archive_path, extract_root)

    assert result_path.name == "test"
    assert (result_path / "cover.jpg").exists()
    assert (result_path / "cover.jpg").read_bytes() == b"data"


@pytest.mark.parametrize(
    ("name", "safe"),
    [
        ("01.jpg", True),
        ("folder/01.jpg", True),
        ("folder/sub/01.jpg", True),
        ("../evil.txt", False),
        ("folder/../../evil.txt", False),
        ("/abs.txt", False),
        ("C:/evil.txt", False),
        ("..\\evil.txt", False),
    ],
)
def test_is_safe_member(tmp_path, name, safe):
    """zip-slip 成员名校验：绝对路径 / 上跳 / 盘符都要拒绝"""
    assert ArchiveHandler._is_safe_member(tmp_path.resolve(), name) is safe


def test_extract_rejects_zip_slip(tmp_path, handler_no_7z):
    """含 ../ 越界路径的压缩包必须整体拒绝解压，不能只跳过那一条"""
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../escaped.txt", "pwned")
        zf.writestr("ok.txt", "fine")

    extract_root = tmp_path / "extract_root"

    with pytest.raises(RuntimeError):
        handler_no_7z.extract(zip_path, extract_root)

    # 越界目标不能出现
    assert not (extract_root / "escaped.txt").exists()
    # 整个包被拒绝，正常成员也不应写出
    assert not (extract_root / "evil" / "ok.txt").exists()


def test_extract_rejects_absolute_member(tmp_path, handler_no_7z):
    """绝对路径成员同样必须被拒绝"""
    zip_path = tmp_path / "abs_evil.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("/abs_escaped.txt", "pwned")
        zf.writestr("ok.txt", "fine")

    extract_root = tmp_path / "extract_root"

    with pytest.raises(RuntimeError):
        handler_no_7z.extract(zip_path, extract_root)

    assert not (extract_root / "abs_evil" / "ok.txt").exists()


def test_extract_normal_zip_still_works(tmp_path, handler_no_7z):
    """回归：加了校验之后，正常的多层目录压缩包仍能解压"""
    zip_path = tmp_path / "normal.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("a/b/c.txt", "deep")
        zf.writestr("top.txt", "top")

    extract_root = tmp_path / "extract_root"
    result_path = handler_no_7z.extract(zip_path, extract_root)

    assert (result_path / "a" / "b" / "c.txt").read_text() == "deep"
    assert (result_path / "top.txt").read_text() == "top"


@pytest.mark.parametrize("nested", [False, True])
def test_extract_same_name_uses_independent_workspaces(tmp_path, handler_no_7z, nested):
    """同名压缩包和重复提取均不能复用旧容器。"""
    output = tmp_path / "output"
    roots = []
    for index in range(2):
        source = tmp_path / str(index)
        source.mkdir()
        archive = source / "comic.zip"
        name = "pages/01.jpg" if nested else "01.jpg"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(name, str(index))
        roots.append(handler_no_7z.extract(archive, output))
    assert roots[0] != roots[1]
    assert all(root.name == ("pages" if nested else "comic") for root in roots)
    assert (roots[0] / "01.jpg").read_text() == "0"
    assert (roots[1] / "01.jpg").read_text() == "1"


def test_extract_does_not_reuse_existing_container_link(tmp_path, handler_no_7z):
    """用户已有的同名链接目录不能成为解压容器。"""
    outside = tmp_path / "existing"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    output = tmp_path / "output"
    output.mkdir()
    try:
        (output / "comic").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("当前环境不允许创建目录链接")
    archive = tmp_path / "comic.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("01.jpg", b"image")
    root = handler_no_7z.extract(archive, output)
    assert root.name == "comic"
    assert root != output / "comic"
    assert list(outside.iterdir()) == [outside / "keep.txt"]


def test_extract_rejects_linked_output_root(tmp_path, handler_no_7z):
    """工作区自身是链接时应在写入前拒绝。"""
    outside = tmp_path / "existing"
    outside.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("当前环境不允许创建目录链接")
    with pytest.raises(RuntimeError, match="链接"):
        handler_no_7z.extract(tmp_path / "comic.zip", linked)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("use_7z", [False, True])
def test_pack_fails_on_directory_enumeration_error(
    tmp_path, handler_no_7z, monkeypatch, use_7z
):
    """读取目录失败不能静默发布一个残缺的归档。"""
    source = tmp_path / "source"
    source.mkdir()
    handler_no_7z.seven_zip = "7z" if use_7z else None

    def denied_walk(self, *, on_error=None):
        assert on_error is not None
        on_error(PermissionError("目录不可读"))
        yield

    monkeypatch.setattr(Path, "walk", denied_walk)
    with patch.object(handler_no_7z, "_run_subprocess") as run:
        assert not handler_no_7z.pack(source, tmp_path / "output.zip")
    run.assert_not_called()


def test_7z_pack_resolves_relative_output(tmp_path, handler_with_7z, monkeypatch):
    """切换到源目录执行 7z 前，输出路径必须先转为绝对路径。"""
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    with patch.object(handler_with_7z, "_run_subprocess", return_value=True) as run:
        assert handler_with_7z.pack(source, Path("output.cbz"), fmt="cbz")
    command = run.call_args.args[0]
    assert command[2] == str(tmp_path / "output.cbz")
    assert run.call_args.kwargs["cwd"] == str(source)


def test_7z_extraction_rejects_link_entries_before_extracting(
    tmp_path, handler_with_7z
):
    """仅使用目录清单模拟链接条目，不构造恶意归档。"""
    listing = b"Path = pages\r\nSymbolic Link = existing\r\n\r\n"
    with (
        patch("subprocess.run", return_value=MagicMock(stdout=listing)),
        patch.object(handler_with_7z, "_run_subprocess") as extract,
        pytest.raises(RuntimeError, match="链接"),
    ):
        handler_with_7z.extract(tmp_path / "comic.7z", tmp_path / "output")
    extract.assert_not_called()
    assert list((tmp_path / "output").iterdir()) == []


def test_extraction_does_not_unwrap_linked_directory(tmp_path, handler_no_7z):
    """模拟后端返回链接目录，必须拒绝而非把链接当内容根目录。"""
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "keep.txt").write_text("keep")
    probe = tmp_path / "probe"
    try:
        probe.symlink_to(existing, target_is_directory=True)
    except OSError:
        pytest.skip("当前环境不允许创建目录链接")
    probe.unlink()

    def extracted_link(archive, container):
        (container / "pages").symlink_to(existing, target_is_directory=True)
        return True

    with (
        patch.object(handler_no_7z, "_extract_zipfile", side_effect=extracted_link),
        pytest.raises(RuntimeError, match="链接"),
    ):
        handler_no_7z.extract(tmp_path / "comic.zip", tmp_path / "output")
    assert (existing / "keep.txt").read_text() == "keep"
    assert list((tmp_path / "output").iterdir()) == []


def test_7z_listing_accepts_windows_member_separators(tmp_path, handler_with_7z):
    """7z 清单在 Windows 使用反斜杠，安全子目录仍应能提取。"""
    listing = b"Path = pages\\01.jpg\r\nAttributes = A\r\n\r\n"
    output = tmp_path / "output"
    output.mkdir()
    with (
        patch("subprocess.run", return_value=MagicMock(stdout=listing)),
        patch.object(handler_with_7z, "_run_subprocess", return_value=True) as extract,
    ):
        assert handler_with_7z._extract_7z(tmp_path / "comic.7z", output)
    assert extract.call_args.args[0][1] == "x"
    assert f"-o{output.resolve()}" in extract.call_args.args[0]
