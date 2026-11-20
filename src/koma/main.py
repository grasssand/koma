from pathlib import Path

from tkinterdnd2 import TkinterDnD

from koma.config import ConfigManager
from koma.ui import KomaGUI
from koma.utils import logger, setup_file_logging


def _report_fatal_error(exc: BaseException, log_path: Path | None) -> None:
    """
    启动阶段崩溃时的兜底提示。

    打包版是 console=False，若只 logger.critical 而不提示，用户看到的现象
    就是"双击没反应"。这里尽量弹窗告知日志位置；连 Tk 都起不来时退回追加写文件。
    """
    detail = f"应用启动失败：{type(exc).__name__}: {exc}"
    if log_path:
        detail += f"\n\n详细日志：{log_path}"

    try:
        from tkinter import messagebox

        messagebox.showerror("Koma 启动失败", detail)
        return
    except Exception:
        pass

    try:
        if log_path:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(detail + "\n")
    except OSError:
        pass


def main():
    # 先按配置决定是否落盘：启动阶段就崩的话，也只有文件日志能留下痕迹。
    # 这里要独立 load 一次配置 —— 此刻 KomaGUI 还没构造。
    # 配置损坏时 load() 会回退默认值（enable_file_log=True），正好保留诊断能力。
    log_path = None
    try:
        cfg = ConfigManager().load()
        if cfg.app.enable_file_log:
            log_path = setup_file_logging(cfg.config_dir)
    except Exception:
        pass

    try:
        root = TkinterDnD.Tk()
        KomaGUI(root)
        root.mainloop()

    except Exception as e:
        logger.critical(f"应用启动失败: {e}", exc_info=True)
        _report_fatal_error(e, log_path)


if __name__ == "__main__":
    main()
