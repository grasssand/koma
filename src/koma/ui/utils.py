import logging
import queue
import tkinter as tk
import tkinter.font as tkfont


class TextHandler(logging.Handler):
    """Tkinter 文本框日志处理器"""

    # 文本框最多保留的行数。批量转换动辄上万行日志，
    # 不裁剪会持续吃内存并拖慢滚动。
    MAX_LINES = 2000

    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        self._messages = queue.Queue()
        self.setFormatter(
            logging.Formatter("%(asctime)s | %(message)s", datefmt="%m/%d %H:%M:%S")
        )
        self.text_widget.after(50, self._drain)

    def emit(self, record):
        self._messages.put(self.format(record))

    def _drain(self):
        for _ in range(100):
            try:
                msg = self._messages.get_nowait()
            except queue.Empty:
                break
            self._append(msg)

        try:
            if self.text_widget.winfo_exists():
                self.text_widget.after(50, self._drain)
        except tk.TclError:
            pass

    def _append(self, msg):
        widget = self.text_widget
        widget.configure(state="normal")
        widget.insert(tk.END, msg + "\n")

        # 超出上限时从头部裁剪，保留最新的 MAX_LINES 行
        total_lines = int(widget.index("end-1c").split(".")[0])
        excess = total_lines - self.MAX_LINES
        if excess > 0:
            widget.delete("1.0", f"{excess + 1}.0")

        widget.see(tk.END)
        widget.configure(state="disabled")


def get_sans_font(user_font: str | None = None) -> str:
    """获取系统无衬线字体"""
    available = tkfont.families()
    candidates = [
        user_font,
        "Noto Sans SC",
        "Noto Sans CJK SC",
        "Source Han Sans CN",
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "微软雅黑",
    ]
    for f in candidates:
        if f and f in available:
            return f
    return "TkDefaultFont"


def get_monospace_font(user_font: str | None = None) -> str:
    """获取等宽字体"""
    available = tkfont.families()
    candidates = [
        user_font,
        "Maple Mono NF CN",  # 中文等宽字体
        "Source Code Pro",
        "DejaVu Sans Mono",
        "Cascadia Code",
        "Consolas",
        "Courier New",
    ]
    for f in candidates:
        if f in available:
            return f
    return "TkFixedFont"
