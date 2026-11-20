import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

logger = logging.getLogger("koma")

LOG_DIR_NAME = "logs"
LOG_FILE_NAME = "koma.log"
LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 3


def get_default_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s", datefmt=" %m/%d %H:%M:%S"
    )


def get_log_file_path(config_dir: Path) -> Path:
    """日志文件路径。与 config.toml 放在同一目录下，便于打包版排查问题。"""
    return Path(config_dir) / LOG_DIR_NAME / LOG_FILE_NAME


def setup_file_logging(config_dir: Path, level=logging.INFO) -> Path | None:
    """
    给 root logger 挂一个滚动文件处理器。

    打包版（pyinstaller console=False）没有 stdout，日志只进 UI 文本框，
    窗口一关就全没了 —— 出问题时无从排查，所以必须落盘。

    Args:
        config_dir: 配置目录（日志写到其下的 logs/ 子目录）
        level: root logger 级别

    Returns:
        日志文件路径；创建失败时返回 None（不应影响程序运行）
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    path = get_log_file_path(config_dir).resolve()

    # 幂等：重复调用不重复挂载
    for handler in root_logger.handlers:
        if (
            isinstance(handler, RotatingFileHandler)
            and Path(handler.baseFilename) == path
        ):
            return path

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning(f"⚠️ 无法创建日志文件 {path}: {e}")
        return None

    handler.setFormatter(get_default_formatter())
    root_logger.addHandler(handler)
    return path


def remove_file_logging() -> None:
    """
    摘掉所有文件日志处理器（设置里关闭「保存本地日志文件」时调用）。

    只停止写入，不删除已有日志文件 —— 那是用户的数据。
    """
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        if isinstance(handler, RotatingFileHandler):
            root_logger.removeHandler(handler)
            handler.close()
