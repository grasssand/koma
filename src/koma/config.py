import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import tomllib

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%m/%d %H:%M:%S",
)

CONFIG_FILENAME = "config.toml"
OUTPUT_FORMATS = ["avif (svt)", "avif (aom)", "webp", "jxl"]
COMIC_TITLE_RE = re.compile(
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
    r"(?P<tail>.*)?"  # tail
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
enable_ad_scan = {scanner_enable_str}
# 二维码白名单 (包含这些域名的二维码不视为广告)
qr_whitelist = {scanner_qr}
"""


@dataclass
class AppConfig:
    font: str = "Noto Sans SC"
    font_size: int = 10

    def __post_init__(self):
        if not isinstance(self.font_size, int) or self.font_size <= 0:
            logging.warning(f"AppConfig: font_size '{self.font_size}' 无效，重置为 10")
            self.font_size = 10


@dataclass
class ConverterConfig:
    max_workers: int = 0
    format: str = "avif (svt)"
    quality: int = 75
    lossless: bool = False

    def __post_init__(self):
        if self.format not in OUTPUT_FORMATS:
            logging.warning(f"ConverterConfig: 不支持格式 '{self.format}'，重置默认")
            self.format = "avif (svt)"
        if not (1 <= self.quality <= 100):
            self.quality = 75

    @property
    def actual_workers(self) -> int:
        if self.max_workers > 0:
            return self.max_workers
        count = os.cpu_count() or 4
        return max(1, int(count * 0.75))


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
        default_factory=lambda: {"comicinfo.xml", "readme.txt", "readme.md"}
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
        return self.convert | self.passthrough


@dataclass
class ScannerConfig:
    enable_ad_scan: bool = False
    qr_whitelist: list[str] = field(
        default_factory=lambda: [
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
            "instagram.com",
        ]
    )


@dataclass
class GlobalConfig:
    app: AppConfig = field(default_factory=AppConfig)
    converter: ConverterConfig = field(default_factory=ConverterConfig)
    extensions: ExtensionsConfig = field(default_factory=ExtensionsConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)


class ConfigManager:
    _instance = None
    config_path: Path
    data: GlobalConfig

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.config_path = cls._find_config_path()
            cls._instance.data = cls._instance._load()
        return cls._instance

    @staticmethod
    def _find_config_path() -> Path:
        """定位配置文件路径"""
        if getattr(sys, "frozen", False):
            app_dir = Path(sys.executable).parent
        else:
            app_dir = Path(__file__).parent.parent

        xdg_home = os.environ.get("XDG_CONFIG_HOME")
        user_config_dir = (
            Path(xdg_home) / "koma" if xdg_home else Path.home() / ".config" / "koma"
        )

        candidates = [
            user_config_dir / CONFIG_FILENAME,
            app_dir / CONFIG_FILENAME,
            Path.cwd() / CONFIG_FILENAME,
        ]

        for path in candidates:
            if path.exists():
                return path

        return candidates[0]

    def _load(self) -> GlobalConfig:
        """加载或创建默认配置"""
        if not self.config_path.exists():
            self._create_default()
            logging.info(f"📄 已创建默认配置: {self.config_path}")
            return GlobalConfig()

        try:
            with open(self.config_path, "rb") as f:
                raw_data = tomllib.load(f)

            logging.info(f"✅ 已加载配置文件: {self.config_path}")
            return GlobalConfig(
                app=AppConfig(**raw_data.get("app", {})),
                converter=ConverterConfig(**raw_data.get("converter", {})),
                extensions=ExtensionsConfig(**raw_data.get("extensions", {})),
                scanner=ScannerConfig(**raw_data.get("scanner", {})),
            )
        except Exception as e:
            logging.error(f"❌ 加载配置文件失败: {e}，使用默认配置")
            return GlobalConfig()

    def _create_default(self):
        """创建默认配置文件"""
        default_cfg = GlobalConfig()
        self.save(default_cfg)

    def save(self, cfg: GlobalConfig | None = None):
        """保存配置到磁盘"""
        if cfg is None:
            cfg = self.data

        def fmt_list(items):
            quoted = [f'"{x}"' for x in sorted(items)]
            return "[\n    " + ",\n    ".join(quoted) + "\n]"

        content = TOML_TEMPLATE.format(
            app=cfg.app,
            converter=cfg.converter,
            converter_lossless_str="true" if cfg.converter.lossless else "false",
            scanner_enable_str="true" if cfg.scanner.enable_ad_scan else "false",
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

            self.data = cfg
            logging.info(f"💾 配置已保存至: {self.config_path}")
        except Exception as e:
            logging.error(f"❌ 保存配置失败: {e}")


_manager = ConfigManager()
_cfg = _manager.data


def save_config(cfg: GlobalConfig):
    _manager.save(cfg)


def find_config_path():
    return _manager.config_path


# 导出变量
FONT = _cfg.app.font
FONT_SIZE = _cfg.app.font_size

MAX_WORKERS = _cfg.converter.actual_workers
CONVERTER_CFG = {
    "format": _cfg.converter.format,
    "quality": _cfg.converter.quality,
    "lossless": _cfg.converter.lossless,
}

CONVERT_EXTS = _cfg.extensions.convert
PASSTHROUGH_EXTS = _cfg.extensions.passthrough
SUPPORTED_IMAGE_EXTS = _cfg.extensions.all_supported_img
ARCHIVE_EXTS = _cfg.extensions.archive
DOCUMENT_EXTS = _cfg.extensions.document
MISC_WHITELIST_FILES = _cfg.extensions.misc_whitelist
SYSTEM_JUNK_FILES = _cfg.extensions.system_junk

ENABLE_AD_SCAN = _cfg.scanner.enable_ad_scan
QR_WHITELIST = _cfg.scanner.qr_whitelist
