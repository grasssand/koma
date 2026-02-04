import logging
import tkinter as tk
import tkinter.font as tkfont


class TextHandler(logging.Handler):
    """Tkinter 文本框日志处理器"""

    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        self.setFormatter(
            logging.Formatter("%(asctime)s | %(message)s", datefmt="%m/%d %H:%M:%S")
        )

    def emit(self, record):
        msg = self.format(record)
        self.text_widget.after(0, self._append, msg)

    def _append(self, msg):
        self.text_widget.configure(state="normal")
        self.text_widget.insert(tk.END, msg + "\n")
        self.text_widget.see(tk.END)
        self.text_widget.configure(state="disabled")


def get_sans_font(user_font: str | None = None) -> str:
    """获取系统无衬线字体"""
    available = set(tkfont.families())
    candidates = [
        user_font,
        "Noto Sans CJK SC",
        "Source Han Sans CN",
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "PingFang SC",
        "Heiti SC",
        "Segoe UI",
        "Helvetica",
        "Arial",
    ]
    for f in candidates:
        if f and f in available:
            return f
    return "TkDefaultFont"


def get_monospace_font() -> str:
    """获取等宽字体"""
    available = set(tkfont.families())
    candidates = [
        "Maple Mono NF CN",  # 等宽中文字体
        "Source Code Pro",
        "DejaVu Sans Mono",
        "Consolas",
        "Cascadia Code",
        "Menlo",
        "Courier New",
    ]
    for f in candidates:
        if f in available:
            return f
    return "TkFixedFont"
