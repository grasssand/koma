import os
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILENAME = "config.toml"
OUTPUT_FORMATS = ["avif (svt)", "avif (aom)", "webp", "jxl"]

COMIC_TITLE_RE = re.compile(
    r"(\((?P<event>[^([]+)\))?"  # event
    r"\s*"
    r"(\[(?P<artist>[^]]+)\])?"  # artist
    r"\s*"
    r"(?P<title>[^([]+)"  # title
    r"\s*"
    r"(\((?P<series>[^[]+))?"  # series
    r"\s*"
    r"(\[(?P<language>[^]]+)\])?"  # language
    r"(?P<tail>.*)?"  # tail
)

DEFAULT_TOML_CONTENT = """# ==========================================
# KOMA 工具箱配置文件
# ==========================================

[app]
# 文件列表字体
font = "Noto Sans SC"
# 文件列表字体大小（整数）
font_size = 10

[converter]
# 线程并发数
# 设置为 0 则自动使用 CPU 核心数的 75%
max_workers = 0
# 转换格式，可选: "avif (svt)", "avif (aom)", "webp", "jxl"
format = "avif (svt)"
# 质量 (1-100)
quality = 75
# 无损模式
lossless = false

[extensions]
# 需要转换的格式
convert = [
    ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff"
]
# 直接复制的格式
passthrough = [
    ".avif", ".webp", ".jxl", ".heic"
]
# 归档文件格式
archive = [
    ".zip", ".cbz", ".rar", ".cbr", ".7z", ".cb7", ".pdf", ".epub",
    ".tar", ".cbt", ".gz", ".tgz", ".bz2", ".tbz2", ".xz", ".txz", ".zst",
]

[scanner]
# 是否开启广告扫描
enable_ad_scan = false
# 二维码白名单 (包含这些域名的二维码不视为广告)
qr_whitelist = [
    "x.com",
    "twitter.com",
    "pixiv.net",
    "fanbox.cc",
    "fantia.jp",
    "dlsite.com",
    "dmm.co.jp",
    "melonbooks.co.jp",
    "booth.pm",
    "patreon.com",
    "ko-fi.com",
    "qq.com",
    "weibo.com",
    "bilibili.com",
    "youtube.com",
    "instagram.com"
]
"""


def find_config_path() -> Path:
    """
    搜索并返回配置文件路径。
    """
    if getattr(sys, "frozen", False):
        app_dir = Path(sys.executable).parent
    else:
        app_dir = Path(__file__).parent.parent

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        user_config_dir = Path(xdg_config_home) / "koma"
    else:
        user_config_dir = Path.home() / ".config" / "koma"

    search_paths = [
        user_config_dir / CONFIG_FILENAME,
        app_dir / CONFIG_FILENAME,
        Path.cwd() / CONFIG_FILENAME,
    ]

    for path in search_paths:
        if path.exists():
            return path

    return search_paths[0]


@dataclass
class AppConfig:
    font: str = "Noto Sans SC"
    font_size: int = 10

    def __post_init__(self):
        if self.font_size <= 0 or not isinstance(self.font_size, int):
            print(f"⚠️ 配置警告: font_size '{self.font_size}' 无效，重置为 10")
            self.font_size = 10


@dataclass
class ConverterConfig:
    max_workers: int = 0
    format: str = "avif (svt)"
    quality: int = 75
    lossless: bool = False

    def __post_init__(self):
        if self.max_workers <= 0:
            count = os.cpu_count() or 4
            self.max_workers = max(1, int(count * 0.75))
        if self.format not in OUTPUT_FORMATS:
            print(f"⚠️ 配置警告: 不支持格式 '{self.format}'，重置为 'avif (svt)'")
            self.format = "avif (svt)"
        if not (1 <= self.quality <= 100):
            print(f"⚠️ 配置警告: 质量 '{self.quality}' 超出范围，重置为 75")
            self.quality = 75


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
            ".pdf",
            ".epub",
        }
    )

    def __post_init__(self):
        if isinstance(self.convert, list):
            self.convert = set(self.convert)
        if isinstance(self.passthrough, list):
            self.passthrough = set(self.passthrough)
        if isinstance(self.archive, list):
            self.archive = set(self.archive)

    @property
    def all_supported(self) -> set[str]:
        return self.convert | self.passthrough


@dataclass
class ScannerConfig:
    enable_ad_scan: bool = False
    qr_whitelist: list[str] = field(
        default_factory=lambda: ["x.com", "twitter.com", "pixiv.net"]
    )


@dataclass
class GlobalConfig:
    app: AppConfig = field(default_factory=AppConfig)
    converter: ConverterConfig = field(default_factory=ConverterConfig)
    extensions: ExtensionsConfig = field(default_factory=ExtensionsConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)


def load_config() -> GlobalConfig:
    toml_path = find_config_path()
    user_data = {}

    if not toml_path.exists():
        try:
            toml_path.parent.mkdir(parents=True, exist_ok=True)
            with open(toml_path, "w", encoding="utf-8") as f:
                f.write(DEFAULT_TOML_CONTENT)
            print(f"⚠️ 未找到配置文件，已生成默认配置: {toml_path}")
        except Exception as e:
            print(f"❌ 无法写入默认配置文件: {e}，将使用默认值")

    else:
        try:
            with open(toml_path, "rb") as f:
                user_data = tomllib.load(f)

            # 配置迁移
            app_data = user_data.get("app", {})
            converter_data = user_data.setdefault("converter", {})
            if "max_workers" in app_data:
                old_val = app_data.pop("max_workers")
                if converter_data.get("max_workers", 0) == 0:
                    converter_data["max_workers"] = old_val

            user_data["app"] = app_data
            print(f"✅ 已加载配置文件: {toml_path}")
        except Exception as e:
            print(f"❌ 配置文件加载失败: {e}，将使用默认值")

    cfg = GlobalConfig(
        app=AppConfig(**user_data.get("app", {})),
        converter=ConverterConfig(**user_data.get("converter", {})),
        extensions=ExtensionsConfig(**user_data.get("extensions", {})),
        scanner=ScannerConfig(**user_data.get("scanner", {})),
    )

    return cfg


_cfg = load_config()

FONT = _cfg.app.font
FONT_SIZE = _cfg.app.font_size

MAX_WORKERS = _cfg.converter.max_workers
CONVERTER_CFG = {
    "format": _cfg.converter.format,
    "quality": _cfg.converter.quality,
    "lossless": _cfg.converter.lossless,
}

CONVERT_EXTS = _cfg.extensions.convert
PASSTHROUGH_EXTS = _cfg.extensions.passthrough
SUPPORTED_IMAGE_EXTS = _cfg.extensions.all_supported
ARCHIVE_EXTS = _cfg.extensions.archive

ENABLE_AD_SCAN = _cfg.scanner.enable_ad_scan
QR_WHITELIST = _cfg.scanner.qr_whitelist
