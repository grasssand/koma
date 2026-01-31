import logging
import sys

LOGGER_NAME = "KOMA"


def get_logger():
    """获取配置好的单例 Logger"""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%m/%d %H:%M:%S"
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        logger.propagate = False

    return logger


logger = get_logger()
