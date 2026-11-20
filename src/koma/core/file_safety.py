"""文件操作的暂存、发布与文件名边界。"""

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def validate_prefix(prefix: str) -> None:
    """前缀只能组成单一文件名，不能引入路径或 Windows 特殊字符。"""
    if not isinstance(prefix, str) or any(
        char in '<>:"/\\|?*' or ord(char) < 32 for char in prefix
    ):
        raise ValueError("文件名前缀不能包含路径分隔符或非法文件名字符")


@contextmanager
def atomic_output(target: Path) -> Iterator[Path]:
    """在目标所在文件系统写入，成功后替换；失败保留原目标。"""
    target = Path(target).absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".koma-", dir=target.parent) as folder:
        staged = Path(folder) / target.name
        yield staged
        os.replace(staged, target)


def move_no_replace(source: Path, target: Path) -> None:
    """发布同一文件系统上的文件，不覆盖已有对象。"""
    if os.name == "nt":
        os.rename(source, target)
        return

    os.link(source, target)
    try:
        source.unlink()
    except OSError:
        try:
            if os.path.samefile(source, target):
                target.unlink()
        except OSError:
            pass
        raise
