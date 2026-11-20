import logging
import shutil
import sys
import tomllib
from pathlib import Path

import pytest

import koma.config as config_module
from koma.config import (
    DEFAULT_COMIC_REGEX,
    AppConfig,
    ConfigManager,
    ConverterConfig,
    GlobalConfig,
    ScannerConfig,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_CONFIG = PROJECT_ROOT / "config.example.toml"


def test_load_missing_file_returns_defaults(tmp_path):
    """配置文件不存在时返回默认配置，而不是报错"""
    manager = ConfigManager()
    manager.config_path = tmp_path / "not_here.toml"

    cfg = manager.load()

    assert isinstance(cfg, GlobalConfig)
    assert cfg.app.width == 900
    assert cfg.converter.format == "avif (svt)"
    # config_dir 必须指向配置文件所在目录（custom_ads 图库依赖它）
    assert cfg.config_dir == tmp_path


def test_load_invalid_toml_falls_back_to_defaults(tmp_path, caplog):
    """配置文件语法损坏时降级为默认值，不应崩溃"""
    bad = tmp_path / "config.toml"
    bad.write_text("this is = = not valid toml", encoding="utf-8")

    manager = ConfigManager()
    manager.config_path = bad

    with caplog.at_level(logging.ERROR):
        cfg = manager.load()

    assert cfg.app.width == 900
    assert "加载配置文件失败" in caplog.text


def test_save_load_roundtrip(tmp_path):
    """save 写出的文件能被 load 原样读回"""
    manager = ConfigManager()
    manager.config_path = tmp_path / "config.toml"

    cfg = manager.get_default_config()
    cfg.app.width = 1234
    cfg.app.height = 567
    cfg.app.font_size = 13
    cfg.app.enable_file_log = False
    cfg.converter.format = "webp"
    cfg.converter.quality = 88
    cfg.converter.lossless = True
    cfg.scanner.enable_ad_scan = True
    cfg.scanner.enable_custom_ad_scan = True
    cfg.scanner.enable_archive_scan = True
    cfg.extensions.convert = {".jpg", ".webp"}
    cfg.scanner.qr_whitelist = ["example.com", "aaa.com"]

    manager.save(cfg)
    assert manager.config_path.exists()

    loaded = manager.load()

    assert loaded.app.width == 1234
    assert loaded.app.height == 567
    assert loaded.app.font_size == 13
    assert loaded.app.enable_file_log is False
    assert loaded.converter.format == "webp"
    assert loaded.converter.quality == 88
    assert loaded.converter.lossless is True
    assert loaded.scanner.enable_ad_scan is True
    assert loaded.scanner.enable_custom_ad_scan is True
    assert loaded.scanner.enable_archive_scan is True
    assert loaded.extensions.convert == {".jpg", ".webp"}
    # 列表写出时会排序
    assert loaded.scanner.qr_whitelist == ["aaa.com", "example.com"]
    # 正则中的反斜杠需能原样往返
    assert loaded.deduplicator.comic_dir_regex == DEFAULT_COMIC_REGEX


def test_get_default_section():
    """按名字取默认子配置，未知段落抛 ValueError"""
    manager = ConfigManager()

    assert manager.get_default_section("converter").format == "avif (svt)"
    assert manager.get_default_section("app").width == 900

    with pytest.raises(ValueError):
        manager.get_default_section("not_a_section")


def test_example_config_uses_correct_types():
    """
    config.example.toml 里的数值必须是整数。

    若写成字符串（height = "800"），AppConfig.__post_init__ 的 isinstance 校验
    会判定非法并静默回退成默认值 —— 用户照着示例改窗口尺寸会发现设置无效。
    """
    with open(EXAMPLE_CONFIG, "rb") as f:
        raw = tomllib.load(f)

    app_raw = raw["app"]
    for key in ("height", "width", "font_size", "list_font_size"):
        assert isinstance(app_raw[key], int), f"[app].{key} 必须写成整数，不能加引号"

    cfg = AppConfig(**app_raw)
    # 值必须原样保留，而不是被回退成默认值
    for key in ("height", "width", "font_size", "list_font_size"):
        assert getattr(cfg, key) == app_raw[key]


def test_example_config_is_complete(tmp_path):
    """示例配置应当是一个完整、可直接使用的配置"""
    with open(EXAMPLE_CONFIG, "rb") as f:
        raw = tomllib.load(f)

    for section in ("app", "converter", "deduplicator", "extensions", "scanner"):
        assert section in raw, f"示例配置缺少 [{section}] 段"

    target = tmp_path / "config.toml"
    shutil.copy(EXAMPLE_CONFIG, target)

    manager = ConfigManager()
    manager.config_path = target
    cfg = manager.load()

    assert cfg.app.height == raw["app"]["height"]
    assert cfg.deduplicator.comic_dir_regex == raw["deduplicator"]["comic_dir_regex"]
    assert cfg.scanner.qr_whitelist == raw["scanner"]["qr_whitelist"]


def test_example_config_whitelist_matches_defaults():
    """
    config.example.toml 的二维码白名单必须与 config.py 的默认值一致。

    白名单在「config.py 默认值 / config.example.toml / 用户 config.toml」三处各有一份，
    而用户 config.toml 会覆盖默认值 —— 只改一处的话，改动对已有配置文件的环境不生效。
    """
    with open(EXAMPLE_CONFIG, "rb") as f:
        raw = tomllib.load(f)

    assert raw["scanner"]["qr_whitelist"] == list(ScannerConfig().qr_whitelist)


def test_default_whitelist_is_sorted_and_unique():
    """白名单保持排序且无重复，便于人工比对三处副本"""
    whitelist = list(ScannerConfig().qr_whitelist)

    assert whitelist == sorted(whitelist)
    assert len(whitelist) == len(set(whitelist))
    # 白名单项必须是可匹配的域名，不能是裸关键词
    assert all("." in d for d in whitelist), (
        "白名单项应为域名，裸关键词在 host 匹配下永远失效"
    )


def test_enable_file_log_is_bool():
    """enable_file_log 必须是布尔值，非法类型回退默认（开启）"""
    assert AppConfig(enable_file_log=False).enable_file_log is False
    assert AppConfig(enable_file_log=True).enable_file_log is True
    # 写成字符串/数字属于配置错误，回退默认而不是按真值判断
    assert AppConfig(enable_file_log="false").enable_file_log is True
    assert AppConfig(enable_file_log=0).enable_file_log is True


def test_example_config_has_enable_file_log():
    """示例配置必须带上日志开关，且能被正确读成布尔值"""
    with open(EXAMPLE_CONFIG, "rb") as f:
        raw = tomllib.load(f)

    assert isinstance(raw["app"]["enable_file_log"], bool)

    cfg = AppConfig(**raw["app"])
    assert cfg.enable_file_log == raw["app"]["enable_file_log"]


def test_get_app_dir_source_mode_is_project_root():
    """
    源码运行时「程序所在目录」必须是项目根，而不是 src/koma。

    回归背景：旧实现用 Path(__file__).parent.parent，算出来是 src/koma，
    而仓库根的 config.toml 在 src/koma/../../ —— 只有 cwd 恰好是仓库根时
    才会被读到，从别处启动会静默用默认配置。
    """
    assert ConfigManager._get_app_dir() == PROJECT_ROOT


def test_get_app_dir_frozen_uses_executable_dir(monkeypatch, tmp_path):
    """打包版「程序所在目录」是 exe 所在目录"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Koma.exe"))

    assert ConfigManager._get_app_dir() == tmp_path


def test_find_config_path_env_override(tmp_path, monkeypatch):
    """KOMA_CONFIG 环境变量优先于所有候选路径"""
    target = tmp_path / "custom.toml"
    monkeypatch.setenv("KOMA_CONFIG", str(target))

    assert ConfigManager._find_config_path("config.toml") == target


def test_find_config_path_prefers_user_config_dir(tmp_path, monkeypatch):
    """用户配置目录存在时优先于程序目录"""
    monkeypatch.delenv("KOMA_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    user_cfg = tmp_path / "koma" / "config.toml"
    user_cfg.parent.mkdir(parents=True)
    user_cfg.write_text("[app]\n", encoding="utf-8")

    assert ConfigManager._find_config_path("config.toml") == user_cfg


def test_save_escapes_all_string_fields(tmp_path):
    """引号、反斜杠、控制字符与中文均可安全往返。"""
    manager = ConfigManager()
    manager.config_path = tmp_path / "config.toml"
    cfg = manager.get_default_config()
    text = '中文 "字体" \\路径\n\t\r\b\f\x00\x1f\x7f'
    regex = r"(?P<artist>'''[\w\s]+)\"(?P<title>.*)\\"
    cfg.app.font = text
    cfg.app.monospace_font = text
    cfg.deduplicator.comic_dir_regex = regex
    for field_name in cfg.extensions.__dataclass_fields__:
        setattr(cfg.extensions, field_name, {text, "普通"})
    cfg.scanner.qr_whitelist = [text, "example.com"]

    manager.save(cfg)

    loaded = manager.load()
    assert loaded.app.font == text
    assert loaded.app.monospace_font == text
    assert loaded.deduplicator.comic_dir_regex == regex
    assert loaded.extensions == cfg.extensions
    assert loaded.scanner.qr_whitelist == sorted(cfg.scanner.qr_whitelist)


@pytest.mark.parametrize("failure_point", ["sync", "replace"])
def test_save_failure_preserves_original_file(
    tmp_path, monkeypatch, caplog, failure_point
):
    """同步或替换失败时保留原配置、清理临时文件并向调用者抛出错误。"""
    manager = ConfigManager()
    manager.config_path = tmp_path / "config.toml"
    manager.save(manager.get_default_config())
    original = manager.config_path.read_bytes()
    candidate = manager.get_default_config()
    candidate.app.width = 1400

    if failure_point == "sync":

        def fail_sync(fd):
            raise OSError("写入失败")

        monkeypatch.setattr(config_module.os, "fsync", fail_sync)
    else:

        def fail_replace(source, target):
            assert Path(source).parent == target.parent
            assert Path(source) != target
            assert tomllib.loads(Path(source).read_text(encoding="utf-8"))
            raise OSError("替换失败")

        monkeypatch.setattr(config_module.os, "replace", fail_replace)

    caplog.clear()
    with caplog.at_level(logging.INFO), pytest.raises(OSError):
        manager.save(candidate)

    assert manager.config_path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [manager.config_path]
    assert "配置已保存至" not in caplog.text


def test_save_creates_missing_parent(tmp_path):
    """首次保存会创建父目录，并只留下最终配置文件。"""
    manager = ConfigManager()
    manager.config_path = tmp_path / "新配置" / "config.toml"

    manager.save(manager.get_default_config())

    assert manager.load().app.width == 900
    assert list(manager.config_path.parent.iterdir()) == [manager.config_path]


@pytest.mark.parametrize("value", [-1, 1.5, "2", True, False, None])
def test_invalid_max_workers_falls_back_to_auto(value, monkeypatch):
    """线程数仅接受非布尔的非负整数，非法类型回退到自动模式。"""
    monkeypatch.setattr(config_module.os, "cpu_count", lambda: 8)

    cfg = ConverterConfig(max_workers=value)

    assert cfg.max_workers == 0
    assert type(cfg.max_workers) is int
    assert cfg.actual_workers == 6


@pytest.mark.parametrize("value", [0, 1, 8])
def test_valid_max_workers_is_preserved(value, monkeypatch):
    """自动模式与显式并发数均保留原有整数值。"""
    monkeypatch.setattr(config_module.os, "cpu_count", lambda: 8)

    cfg = ConverterConfig(max_workers=value)

    assert cfg.max_workers == value
    assert cfg.actual_workers == (value or 6)


@pytest.mark.parametrize("value", ["-1", "1.5", '"2"', "true", "false"])
def test_load_invalid_max_workers_retains_other_config(tmp_path, value):
    """非法并发数只回退该字段，不丢弃其它有效设置。"""
    manager = ConfigManager()
    manager.config_path = tmp_path / "config.toml"
    manager.config_path.write_text(
        f"[app]\nwidth = 1234\n[converter]\nmax_workers = {value}\n",
        encoding="utf-8",
    )

    cfg = manager.load()

    assert cfg.app.width == 1234
    assert cfg.converter.max_workers == 0


@pytest.mark.parametrize("value", [-1, 1.5, "2", True, False, None])
def test_save_rejects_mutated_invalid_max_workers(tmp_path, value):
    """直接编辑配置对象也不能将非法线程数写入磁盘。"""
    manager = ConfigManager()
    manager.config_path = tmp_path / "config.toml"
    cfg = manager.get_default_config()
    manager.save(cfg)
    original = manager.config_path.read_bytes()
    cfg.converter.max_workers = value

    with pytest.raises(ValueError, match="最大线程数"):
        manager.save(cfg)

    assert manager.config_path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [manager.config_path]


def test_save_replaces_only_after_staged_config_is_complete(tmp_path, monkeypatch):
    """原文件直到完整的新 TOML 准备好后才会被替换。"""
    manager = ConfigManager()
    manager.config_path = tmp_path / "config.toml"
    cfg = manager.get_default_config()
    manager.save(cfg)
    original = manager.config_path.read_bytes()
    cfg.app.width = 1600
    original_replace = config_module.os.replace
    replacements = []

    def replace_complete_file(source, target):
        assert target.read_bytes() == original
        assert source.parent == target.parent
        assert source.suffix == target.suffix
        assert tomllib.loads(source.read_text(encoding="utf-8"))["app"]["width"] == 1600
        replacements.append(source)
        original_replace(source, target)

    monkeypatch.setattr(config_module.os, "replace", replace_complete_file)

    manager.save(cfg)

    assert len(replacements) == 1
    assert manager.load().app.width == 1600
    assert list(tmp_path.iterdir()) == [manager.config_path]


def test_save_invalid_string_preserves_original_file(tmp_path):
    """无法表示为合法 Unicode 的字符串不会破坏已有配置。"""
    manager = ConfigManager()
    manager.config_path = tmp_path / "config.toml"
    cfg = manager.get_default_config()
    manager.save(cfg)
    original = manager.config_path.read_bytes()
    cfg.app.font = "\ud800"

    with pytest.raises(tomllib.TOMLDecodeError):
        manager.save(cfg)

    assert manager.config_path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [manager.config_path]
