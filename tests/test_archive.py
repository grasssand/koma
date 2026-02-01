import shutil
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from koma.utils.archive import ArchiveHandler


@pytest.fixture
def archive_handler():
    with patch("shutil.which", return_value=None):
        handler = ArchiveHandler()
        return handler


def test_init_detection():
    """测试初始化时的 7z 检测逻辑"""
    # 系统有 7z
    with patch("shutil.which", return_value="/usr/bin/7z"):
        h = ArchiveHandler()
        assert h.seven_zip == "/usr/bin/7z"

    # 系统无 7z
    with patch("shutil.which", return_value=None):
        h = ArchiveHandler()
        assert h.seven_zip is None


def test_smart_extract_nested(tmp_path, archive_handler):
    """测试解压"""
    archive_path = Path("comic.zip")
    temp_root = tmp_path / "temp"

    container = temp_root / "comic"
    inner = container / "InnerFolder"
    inner.mkdir(parents=True)
    (inner / "01.jpg").touch()

    # 系统垃圾文件应被忽略
    (container / "__MACOSX").mkdir()
    (container / "Thumbs.db").touch()

    with patch.object(archive_handler, "_extract_zipfile", return_value=True):
        result_path = archive_handler.extract(archive_path, temp_root)

        assert result_path == inner
        assert result_path.name == "InnerFolder"


def test_smart_extract_flat(tmp_path, archive_handler):
    """测试智能解压：'散乱'结构 (返回容器目录)"""
    # 模拟结构: temp_root/ArchiveName/01.jpg (直接散在里面)
    archive_path = Path("comic.zip")
    temp_root = tmp_path / "temp"

    container = temp_root / "comic"
    container.mkdir(parents=True)
    (container / "01.jpg").touch()
    (container / "02.jpg").touch()

    with patch.object(archive_handler, "_extract_zipfile", return_value=True):
        result_path = archive_handler.extract(archive_path, temp_root)

        # 期望：返回 container
        assert result_path == container
        assert result_path.name == "comic"


def test_pack_zip_fallback(tmp_path, archive_handler):
    """测试 Python 原生 zip 打包"""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "1.jpg").write_text("fake image")
    (source_dir / "sub").mkdir()
    (source_dir / "sub" / "2.png").write_text("fake png")

    # 垃圾文件 (应被忽略)
    (source_dir / "Thumbs.db").touch()

    output_cbz = tmp_path / "output.cbz"

    # 执行打包
    success = archive_handler.pack(source_dir, output_cbz, fmt="cbz")

    assert success is True
    assert output_cbz.exists()

    # 验证 zip 内容
    with zipfile.ZipFile(output_cbz, "r") as zf:
        names = zf.namelist()
        assert "1.jpg" in names
        assert "sub/2.png" in names
        assert "Thumbs.db" not in names


def test_pack_7z_call(tmp_path):
    """测试当存在 7z 时是否正确构建命令"""
    with patch("shutil.which", return_value="7z"):
        handler = ArchiveHandler()

        with patch("subprocess.run") as mock_run:
            src = tmp_path / "src"
            out = tmp_path / "out.cbz"

            handler.pack(src, out, fmt="cbz", level=0)

            # 验证命令参数
            args, kwargs = mock_run.call_args
            cmd = args[0]

            assert cmd[0] == "7z"
            assert cmd[1] == "a"
            assert "-tzip" in cmd  # cbz -> zip
            assert "-mx=0" in cmd
            assert kwargs["cwd"] == str(src)  # 确保是在源目录内执行


# ==========================================
# 真实环境测试 (Integration Tests)
# 这些测试会真正创建文件并调用解压
# ==========================================


def test_real_zipfile_extract_and_pack(tmp_path):
    """测试 Python 原生 zipfile 的真实读写能力"""
    src_dir = tmp_path / "source"
    src_dir.mkdir()
    (src_dir / "test.txt").write_text("hello world", encoding="utf-8")
    (src_dir / "image.jpg").write_bytes(b"fake image data")

    # 干扰文件
    (src_dir / "Thumbs.db").touch()

    # 测试打包
    archive_path = tmp_path / "output.cbz"
    handler = ArchiveHandler()

    success = handler._pack_zipfile(src_dir, archive_path, level=0)

    assert success is True
    assert archive_path.exists()

    # 验证打包内容
    with zipfile.ZipFile(archive_path, "r") as zf:
        names = zf.namelist()
        assert "test.txt" in names
        assert "image.jpg" in names
        assert "Thumbs.db" not in names  # 应该被过滤

    # 测试解压
    extract_dir = tmp_path / "extracted"
    extract_dir.mkdir()

    success = handler._extract_zipfile(archive_path, extract_dir)

    assert success is True
    assert (extract_dir / "test.txt").read_text(encoding="utf-8") == "hello world"


@pytest.mark.skipif(
    not shutil.which("7z") and not shutil.which("7za"),
    reason="系统未安装 7z，跳过真实 7z 测试",
)
def test_real_7z_extract_and_pack(tmp_path):
    """测试 7-Zip 的真实调用"""
    handler = ArchiveHandler()
    if not handler.seven_zip:
        pytest.skip("ArchiveHandler 未找到 7z 可执行文件")

    src_dir = tmp_path / "src_7z"
    src_dir.mkdir()
    (src_dir / "data.png").write_bytes(b"png data")

    archive_path = tmp_path / "test.7z"

    # 测试 7z 打包
    success = handler.pack(src_dir, archive_path, fmt="7z", level=0)

    assert success is True
    assert archive_path.exists()

    # 测试 7z 解压
    out_dir = tmp_path / "out_7z"
    out_dir.mkdir()

    success = handler.extract(archive_path, out_dir)

    assert (success / "data.png").exists()
