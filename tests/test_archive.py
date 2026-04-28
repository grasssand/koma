import shutil
import zipfile
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

    container = temp_root / "comic"
    inner = container / "InnerFolder"
    inner.mkdir(parents=True)
    (inner / "01.jpg").touch()

    # 模拟垃圾文件
    (container / "__MACOSX").mkdir()
    (container / "Thumbs.db").touch()

    with patch.object(handler_no_7z, "_extract_zipfile", return_value=True):
        result_path = handler_no_7z.extract(archive_path, temp_root)

        assert result_path == inner
        assert result_path.name == "InnerFolder"


def test_extract_smart_folder_flat(tmp_path, handler_no_7z):
    """测试智能解压：散乱结构"""
    archive_path = tmp_path / "comic.zip"
    temp_root = tmp_path / "temp"

    container = temp_root / "comic"
    container.mkdir(parents=True)
    (container / "01.jpg").touch()
    (container / "02.jpg").touch()

    with patch.object(handler_no_7z, "_extract_zipfile", return_value=True):
        result_path = handler_no_7z.extract(archive_path, temp_root)

        assert result_path == container
        assert result_path.name == "comic"


def test_7z_command_generation(tmp_path, handler_with_7z):
    """测试 7z 命令生成是否正确"""
    src = tmp_path / "src"
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
