from pathlib import Path
from unittest.mock import patch

import pytest

from koma.core.command_generator import CommandGenerator


@pytest.fixture(autouse=True)
def mock_ffmpeg():
    with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        yield


def test_no_ffmpeg_error():
    """测试未找到 FFmpeg 时的报错"""
    with patch("shutil.which", return_value=None):
        with pytest.raises(FileNotFoundError, match="未找到 FFmpeg"):
            CommandGenerator("avif", 75, False)


def test_avif_svt_normal():
    """测试 AVIF (SVT) 有损"""
    gen = CommandGenerator("avif (svt)", 75, False)
    cmd = gen.generate(Path("in.png"), Path("out.avif"), is_anim=False, is_gray=False)
    cmd_str = " ".join(cmd)

    assert "-c:v libsvtav1" in cmd_str
    assert "-crf 35" in cmd_str


def test_avif_svt_lossless():
    """测试 AVIF (SVT) 无损"""
    gen = CommandGenerator("avif (svt)", 75, True)
    cmd = gen.generate(Path("in.png"), Path("out.avif"), is_anim=False, is_gray=False)
    cmd_str = " ".join(cmd)

    assert "-c:v libsvtav1" in cmd_str
    assert "-crf 0" in cmd_str
    assert "lossless=1" in cmd_str


def test_avif_aom_normal():
    """测试 AVIF (AOM) 有损"""
    gen = CommandGenerator("avif (aom)", 75, False)
    cmd = gen.generate(Path("in.png"), Path("out.avif"), is_anim=False, is_gray=False)
    cmd_str = " ".join(cmd)

    assert "-c:v libaom-av1" in cmd_str
    assert "-crf 23" in cmd_str
    assert "-cpu-used 6" in cmd_str


def test_avif_aom_lossless():
    """测试 AVIF (AOM) 无损"""
    gen = CommandGenerator("avif (aom)", 75, True)
    cmd = gen.generate(Path("in.png"), Path("out.avif"), is_anim=False, is_gray=False)
    cmd_str = " ".join(cmd)

    assert "-c:v libaom-av1" in cmd_str
    assert "-crf 0" in cmd_str


def test_webp_lossless_anim():
    """测试 WebP 无损 + 动图"""
    gen = CommandGenerator("webp", 80, True)
    cmd = gen.generate(Path("in.gif"), Path("out.webp"), is_anim=True, is_gray=False)
    cmd_str = " ".join(cmd)

    assert "-c:v libwebp_anim" in cmd_str
    assert "-lossless 1" in cmd_str


def test_webp_lossy_static():
    """测试 WebP 有损 + 静态"""
    gen = CommandGenerator("webp", 60, False)  # Lossless=False
    cmd = gen.generate(Path("in.png"), Path("out.webp"), is_anim=False, is_gray=False)
    cmd_str = " ".join(cmd)

    assert "-c:v libwebp" in cmd_str
    assert "-q:v 60" in cmd_str


def test_jxl_normal():
    """测试 JXL 有损"""
    gen = CommandGenerator("jxl", 85, False)
    cmd = gen.generate(Path("in.png"), Path("out.jxl"), is_anim=False, is_gray=False)
    cmd_str = " ".join(cmd)

    assert "-distance 1.0" in cmd_str


def test_jxl_lossless():
    """测试 JXL 无损"""
    gen = CommandGenerator("jxl", 85, True)
    cmd = gen.generate(Path("in.png"), Path("out.jxl"), is_anim=False, is_gray=False)
    cmd_str = " ".join(cmd)

    assert "-distance 0.0" in cmd_str
