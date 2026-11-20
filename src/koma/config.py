import logging
import os
import re
import sys
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

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
# 窗口大小
height = {app.height}
width = {app.width}
# 界面字体
font = {app_font}
# 日志字体
monospace_font = {app_monospace_font}
# 界面字体大小（整数）
font_size = {app.font_size}
# 文件列表字体大小（整数）
list_font_size = {app.list_font_size}
# 是否保存本地日志文件（路径: <配置目录>/logs/koma.log）
enable_file_log = {app_enable_file_log_str}

[converter]
# 线程并发数
# 设置为 0 则自动使用 CPU 核心数的 75%
max_workers = {converter.max_workers}
# 转换格式，可选: "avif (svt)", "avif (aom)", "webp", "jxl"
format = {converter_format}
# 质量 (1-100)
quality = {converter.quality}
# 无损模式
lossless = {converter_lossless_str}

[deduplicator]
# 查重文件夹/文件名解析正则
comic_dir_regex = {deduplicator_regex}

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
# 是否开启二维码广告图扫描
enable_ad_scan = {scanner_enable_ad_str}
# 是否开启自定义广告图扫描
enable_custom_ad_scan = {scanner_enable_custom_ad_str}
# 是否开启压缩包扫描
enable_archive_scan = {scanner_enable_archive_str}
# 二维码白名单 (包含这些域名的二维码不视为广告)
qr_whitelist = {scanner_qr}
"""


@dataclass
class AppConfig:
    height: int = 800
    width: int = 900
    font: str = "Noto Sans SC"
    monospace_font: str = "Maple Mono NF CN"
    font_size: int = 9
    list_font_size: int = 10
    # 是否把运行日志写到 <配置目录>/logs/koma.log
    enable_file_log: bool = True

    def __post_init__(self):
        if not isinstance(self.height, int) or self.height <= 0:
            self.height = 800
        if not isinstance(self.width, int) or self.width <= 0:
            self.width = 900
        if not isinstance(self.font_size, int) or self.font_size <= 0:
            self.font_size = 9
        if not isinstance(self.list_font_size, int) or self.list_font_size <= 0:
            self.list_font_size = 10
        if not isinstance(self.enable_file_log, bool):
            self.enable_file_log = True


@dataclass
class ConverterConfig:
    max_workers: int = 0
    format: str = "avif (svt)"
    quality: int = 75
    lossless: bool = False
    custom_params: str = ""
    custom_ext: str = ""

    def __post_init__(self):
        if (
            isinstance(self.max_workers, bool)
            or not isinstance(self.max_workers, int)
            or self.max_workers < 0
        ):
            self.max_workers = 0
        if self.format not in IMG_OUTPUT_FORMATS:
            self.format = "avif (svt)"
        if not (1 <= self.quality <= 100):
            self.quality = 75
        if self.custom_params is None:
            self.custom_params = ""
        if self.custom_ext is None:
            self.custom_ext = ""

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
    enable_custom_ad_scan: bool = False
    enable_archive_scan: bool = False
    qr_whitelist: list[str] = field(
        default_factory=lambda: [
            "alice-books.com",
            "bilibili.com",
            "bluesky.social",
            "bookwalker.jp",
            "booth.pm",
            "bsky.app",
            "candypop.jp",
            "ci-en.jp",
            "ci-en.net",
            "cmoa.jp",
            "comicbavel.com",
            "crepu.net",
            "discord.com",
            "discord.gg",
            "dl.getchu.com",
            "dlsite.com",
            "dmm.co.jp",
            "facebook.com",
            "fanbox.cc",
            "fantia.jp",
            "gumroad.com",
            "gyutto.com",
            "ichijinsha.co.jp",
            "instagram.com",
            "kadokawa.co.jp",
            "ko-fi.com",
            "kodansha.co.jp",
            "lofter.com",
            "mandarake.co.jp",
            "mastodon.social",
            "melonbooks.co.jp",
            "misskey.design",
            "misskey.io",
            "patreon.com",
            "pawoo.net",
            "pixiv.net",
            "qq.com",
            "shogakukan.co.jp",
            "shueisha.co.jp",
            "skeb.jp",
            "suruga-ya.jp",
            "t.me",
            "telegram.org",
            "toranoana.jp",
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
    config_dir: Path = field(default_factory=Path)

    @property
    def custom_ad_dir(self) -> Path:
        """获取自定义广告文件夹的路径"""
        return self.config_dir / "custom_ads"


def _toml_string(value: str) -> str:
    """将字符串编码为 TOML 基本字符串。"""
    escapes = {
        "\\": "\\\\",
        '"': '\\"',
        "\b": "\\b",
        "\t": "\\t",
        "\n": "\\n",
        "\f": "\\f",
        "\r": "\\r",
    }
    result = []
    for char in str(value):
        if char in escapes:
            result.append(escapes[char])
        elif ord(char) < 0x20 or ord(char) == 0x7F or 0xD800 <= ord(char) <= 0xDFFF:
            result.append(f"\\u{ord(char):04x}")
        else:
            result.append(char)
    return '"' + "".join(result) + '"'


def _atomic_write(path: Path, content: str) -> None:
    """写入临时文件并原子替换目标文件，失败时保留原文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=path.suffix,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass
        raise


class ConfigManager:
    def __init__(self, filename: str = CONFIG_FILENAME):
        self.config_path = self._find_config_path(filename)

    @staticmethod
    def _get_app_dir() -> Path:
        """
        程序所在目录。

        - 打包版：exe 所在目录
        - 源码运行：**项目根**（config.py → src/koma → src → 项目根）

        旧实现用的是 `Path(__file__).parent.parent`，得到的是 `src/koma`，
        而仓库根的 config.toml 在 `src/koma/../../` —— 结果只有 cwd 恰好是
        仓库根时才会被读到，从别处启动会静默用默认配置。
        """
        if getattr(sys, "frozen", False):
            return Path(sys.executable).parent
        return Path(__file__).resolve().parents[2]

    @staticmethod
    def _find_config_path(filename: str) -> Path:
        """
        定位配置文件路径。

        优先级: KOMA_CONFIG 环境变量 > 用户配置目录 > 程序所在目录 > 当前工作目录
        """
        # 环境变量显式指定时直接采用（便于测试与多实例）
        env_override = os.environ.get("KOMA_CONFIG")
        if env_override:
            return Path(env_override)

        app_dir = ConfigManager._get_app_dir()

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

            cfg = GlobalConfig(
                app=AppConfig(**raw_data.get("app", {})),
                converter=ConverterConfig(**raw_data.get("converter", {})),
                deduplicator=DeduplicatorConfig(**raw_data.get("deduplicator", {})),
                extensions=ExtensionsConfig(**raw_data.get("extensions", {})),
                scanner=ScannerConfig(**raw_data.get("scanner", {})),
            )
            cfg.config_dir = self.config_path.parent
            return cfg
        except Exception as e:
            logger.error(f"❌ 加载配置文件失败: {e}，将使用默认配置")
            return self.get_default_config()

    def save(self, cfg: GlobalConfig) -> None:
        """原子保存配置；校验或写入失败时保留原文件并向调用者抛出异常。"""
        if (
            isinstance(cfg.converter.max_workers, bool)
            or not isinstance(cfg.converter.max_workers, int)
            or cfg.converter.max_workers < 0
        ):
            raise ValueError("最大线程数必须是非负整数（0 表示自动）")

        def fmt_list(items) -> str:
            quoted = [_toml_string(x) for x in sorted(items)]
            return "[\n    " + ",\n    ".join(quoted) + "\n]"

        # 使用模版填充数据
        content = TOML_TEMPLATE.format(
            app=cfg.app,
            app_font=_toml_string(cfg.app.font),
            app_monospace_font=_toml_string(cfg.app.monospace_font),
            app_enable_file_log_str="true" if cfg.app.enable_file_log else "false",
            converter=cfg.converter,
            converter_format=_toml_string(cfg.converter.format),
            converter_lossless_str="true" if cfg.converter.lossless else "false",
            deduplicator_regex=_toml_string(cfg.deduplicator.comic_dir_regex),
            scanner_enable_ad_str="true" if cfg.scanner.enable_ad_scan else "false",
            scanner_enable_custom_ad_str="true"
            if cfg.scanner.enable_custom_ad_scan
            else "false",
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
        # 确保任何非法输入都在替换原文件之前失败。
        tomllib.loads(content)

        _atomic_write(self.config_path, content)
        logger.info(f"💾 配置已保存至: {self.config_path}")

    def get_default_config(self) -> GlobalConfig:
        """获取一份全新的默认配置"""
        cfg = GlobalConfig()
        cfg.config_dir = self.config_path.parent
        return cfg

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
