import logging
import os
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILENAME = "config.toml"

# 图片输出格式
IMG_OUTPUT_FORMATS = ["avif (svt)", "avif (aom)", "webp", "jxl"]

# 归档输出格式
ARCHIVE_OUTPUT_FORMATS = ["zip", "cbz", "7z", "cb7"]

# 文件名查重匹配正则
DEFAULT_COMIC_REGEX = (
    r"(\((?P<event>[^([]+)\))?"
    r"\s*"
    r"(\[(?P<artist>[^]]+)\])?"
    r"\s*"
    r"(?P<title>[^([]+)"
    r"\s*"
    r"(\((?P<series>[^[]+))?"
    r"\s*"
    r"(\[(?P<language>[^]]+)\])?"
    r"\s*"
    r"(?P<tail>.*)?"
)

# 默认 TOML 模版
TOML_TEMPLATE = """# ==========================================
# KOMA 工具箱配置文件
# ==========================================

[app]
# 文件列表字体
font = "{app.font}"
# 文件列表字体大小（整数）
font_size = {app.font_size}

[converter]
# 线程并发数
# 设置为 0 则自动使用 CPU 核心数的 75%
max_workers = {converter.max_workers}
# 转换格式，可选: "avif (svt)", "avif (aom)", "webp", "jxl"
format = "{converter.format}"
# 质量 (1-100)
quality = {converter.quality}
# 无损模式
lossless = {converter_lossless_str}

[deduplicator]
# 查重文件夹/文件名解析正则
comic_dir_regex = '''{deduplicator.comic_dir_regex}'''

[extensions]
# 需要转换的格式
convert = {ext_convert}
# 直接复制的格式
passthrough = {ext_passthrough}
# 归档文件格式
archive = {ext_archive}
# 文档格式
document = {ext_document}

# 杂项文件白名单
misc_whitelist = {ext_misc}
# 系统垃圾文件
system_junk = {ext_junk}

[scanner]
# 是否开启广告扫描
enable_ad_scan = {scanner_enable_ad_str}
# 是否开启压缩包扫描
enable_archive_scan = {scanner_enable_archive_str}
# 二维码白名单 (包含这些域名的二维码不视为广告)
qr_whitelist = {scanner_qr}
"""


@dataclass
class AppConfig:
    font: str = "Noto Sans SC"
    font_size: int = 10

    def __post_init__(self):
        if not isinstance(self.font_size, int) or self.font_size <= 0:
            self.font_size = 10


@dataclass
class ConverterConfig:
    max_workers: int = 0
    format: str = "avif (svt)"
    quality: int = 75
    lossless: bool = False

    def __post_init__(self):
        if self.format not in IMG_OUTPUT_FORMATS:
            self.format = "avif (svt)"
        if not (1 <= self.quality <= 100):
            self.quality = 75

    @property
    def actual_workers(self) -> int:
        """计算实际使用的线程数"""
        if self.max_workers > 0:
            return self.max_workers
        count = os.cpu_count() or 4
        # 默认使用 75% 的核心，避免卡死系统
        return max(1, int(count * 0.75))


@dataclass
class DeduplicatorConfig:
    comic_dir_regex: str = DEFAULT_COMIC_REGEX

    def __post_init__(self):
        try:
            re.compile(self.comic_dir_regex)
        except re.error:
            self.comic_dir_regex = DEFAULT_COMIC_REGEX


@dataclass
class ExtensionsConfig:
    convert: set[str] = field(
        default_factory=lambda: {
            ".jpg",
            ".jpeg",
            ".png",
            ".bmp",
            ".gif",
            ".tif",
            ".tiff",
        }
    )
    passthrough: set[str] = field(
        default_factory=lambda: {".avif", ".webp", ".jxl", ".heic"}
    )
    archive: set[str] = field(
        default_factory=lambda: {
            ".zip",
            ".cbz",
            ".rar",
            ".cbr",
            ".7z",
            ".cb7",
            ".tar",
            ".gz",
            ".tgz",
            ".bz2",
            ".tbz2",
            ".xz",
            ".txz",
            ".zst",
        }
    )
    document: set[str] = field(
        default_factory=lambda: {".pdf", ".epub", ".azw3", ".mobi"}
    )
    misc_whitelist: set[str] = field(
        default_factory=lambda: {"comicinfo.xml", "readme.md", "readme.txt"}
    )
    system_junk: set[str] = field(
        default_factory=lambda: {".ds_store", "thumbs.db", "__macosx", "desktop.ini"}
    )

    def __post_init__(self):
        for field_name in self.__dataclass_fields__:
            val = getattr(self, field_name)
            if isinstance(val, list):
                setattr(self, field_name, set(val))

    @property
    def all_supported_img(self) -> set[str]:
        """所有支持的图片格式"""
        return self.convert | self.passthrough


@dataclass
class ScannerConfig:
    enable_ad_scan: bool = False
    enable_archive_scan: bool = False
    qr_whitelist: list[str] = field(
        default_factory=lambda: [
            "bilibili.com",
            "bluesky",
            "booth.pm",
            "bsky.app",
            "ci-en.jp",
            "ci-en.net",
            "crepu.net",
            "discord.com",
            "discord.gg",
            "dlsite.com",
            "dmm.co.jp",
            "facebook.com",
            "fanbox.cc",
            "fantia.jp",
            "gumroad.com",
            "instagram.com",
            "ko-fi.com",
            "lofter.com",
            "mastodon.social",
            "melonbooks.co.jp",
            "misskey.design",
            "misskey.io",
            "patreon.com",
            "pawoo.net",
            "pixiv.net",
            "qq.com",
            "skeb.jp",
            "t.me",
            "telegram.org",
            "tumblr.com",
            "twitter.com",
            "weibo.com",
            "wordpress.com",
            "x.com",
            "youtube.com",
        ]
    )


@dataclass
class GlobalConfig:
    """根配置对象"""

    app: AppConfig = field(default_factory=AppConfig)
    converter: ConverterConfig = field(default_factory=ConverterConfig)
    deduplicator: DeduplicatorConfig = field(default_factory=DeduplicatorConfig)
    extensions: ExtensionsConfig = field(default_factory=ExtensionsConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)


class ConfigManager:
    def __init__(self, filename: str = CONFIG_FILENAME):
        self.config_path = self._find_config_path(filename)

    @staticmethod
    def _find_config_path(filename: str) -> Path:
        """
        定位配置文件路径。
        优先级: 用户配置目录 > 程序所在目录 > 当前工作目录
        """
        if getattr(sys, "frozen", False):
            app_dir = Path(sys.executable).parent
        else:
            app_dir = Path(__file__).parent.parent

        xdg_home = os.environ.get("XDG_CONFIG_HOME")
        user_config_dir = (
            Path(xdg_home) / "koma" if xdg_home else Path.home() / ".config" / "koma"
        )

        candidates = [
            user_config_dir / filename,
            app_dir / filename,
            Path.cwd() / filename,
        ]

        for path in candidates:
            if path.exists():
                return path

        # 如果都不存在，默认使用第一个路径（用户配置目录）
        return candidates[0]

    def load(self) -> GlobalConfig:
        """
        加载配置。
        如果文件不存在或解析错误，返回默认配置。
        """
        if not self.config_path.exists():
            return self.get_default_config()

        try:
            with open(self.config_path, "rb") as f:
                raw_data = tomllib.load(f)

            return GlobalConfig(
                app=AppConfig(**raw_data.get("app", {})),
                converter=ConverterConfig(**raw_data.get("converter", {})),
                deduplicator=DeduplicatorConfig(**raw_data.get("deduplicator", {})),
                extensions=ExtensionsConfig(**raw_data.get("extensions", {})),
                scanner=ScannerConfig(**raw_data.get("scanner", {})),
            )
        except Exception as e:
            logging.error(f"❌ 加载配置文件失败: {e}，将使用默认配置")
            return self.get_default_config()

    def save(self, cfg: GlobalConfig) -> None:
        """将配置对象保存到磁盘"""

        def fmt_list(items) -> str:
            quoted = [f'"{x}"' for x in sorted(items)]
            return "[\n    " + ",\n    ".join(quoted) + "\n]"

        # 使用模版填充数据
        content = TOML_TEMPLATE.format(
            app=cfg.app,
            converter=cfg.converter,
            converter_lossless_str="true" if cfg.converter.lossless else "false",
            deduplicator=cfg.deduplicator,
            scanner_enable_ad_str="true" if cfg.scanner.enable_ad_scan else "false",
            scanner_enable_archive_str="true"
            if cfg.scanner.enable_archive_scan
            else "false",
            ext_convert=fmt_list(cfg.extensions.convert),
            ext_passthrough=fmt_list(cfg.extensions.passthrough),
            ext_archive=fmt_list(cfg.extensions.archive),
            ext_document=fmt_list(cfg.extensions.document),
            ext_misc=fmt_list(cfg.extensions.misc_whitelist),
            ext_junk=fmt_list(cfg.extensions.system_junk),
            scanner_qr=fmt_list(cfg.scanner.qr_whitelist),
        )

        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                f.write(content)
            logging.info(f"💾 配置已保存至: {self.config_path}")
        except Exception as e:
            logging.error(f"❌ 保存配置失败: {e}")

    def get_default_config(self) -> GlobalConfig:
        """获取一份全新的默认配置"""
        return GlobalConfig()

    def get_default_section(self, section_name: str):
        """
        获取某个子配置段的默认值。

        Usage:
            default_scanner = manager.get_default_section("scanner")
        """
        defaults = GlobalConfig()
        if hasattr(defaults, section_name):
            return getattr(defaults, section_name)
        raise ValueError(f"Config section '{section_name}' not found")
