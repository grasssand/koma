import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, ttk

from tkinterdnd2 import DND_FILES

from koma.config import GlobalConfig
from koma.core.image_processor import ImageProcessor
from koma.utils import logger


class BaseTab(ttk.Frame):
    def __init__(
        self,
        parent,
        config: GlobalConfig,
        image_processor: ImageProcessor,
        status_callback: Callable | None = None,
    ):
        super().__init__(parent)
        self.config = config
        self.image_processor = image_processor
        self.status_callback = status_callback

    def update_status(
        self, text: str, value: float | None = None, indeterminate: bool | None = None
    ):
        """汇报状态给主窗口"""
        if self.status_callback:
            self.status_callback(text, value, indeterminate)

    def safe_update_status(
        self, text: str, value: float | None = None, indeterminate: bool | None = None
    ):
        """跨线程安全的更新方法"""
        if self.after:
            self.after(0, lambda: self.update_status(text, value, indeterminate))

    def _setup_dnd(self, widget, target):
        """为控件绑定文件拖拽 (DND)"""
        if not hasattr(widget, "drop_target_register"):
            widget.drop_target_register = lambda *args: widget.tk.call(
                "::dnd::drop_target_register", widget._w, *args
            )
            widget.dnd_bind = lambda seq, func, add=None: widget._bind(
                ("bind", seq), func, add
            )

        try:
            widget.drop_target_register(DND_FILES)

            def handle_drop(event):
                if not event.data:
                    return
                paths = self.tk.splitlist(event.data)

                if isinstance(target, tk.StringVar):
                    if paths:
                        target.set(paths[0])
                elif callable(target):
                    target(paths)

            widget.dnd_bind("<<Drop>>", handle_drop)

        except Exception as e:
            logger.error(f"拖拽文件失败: {e}")

    def _on_drop(self, event, string_var):
        data = event.data
        if not data:
            return

        paths = self.tk.splitlist(data)
        if paths:
            p = Path(paths[0])
            string_var.set(str(p))

    def select_dir(self, string_var: tk.StringVar):
        """通用目录选择"""
        initial = string_var.get()
        if not initial or not Path(initial).exists():
            initial = None

        p = filedialog.askdirectory(initialdir=initial)
        if p:
            native_path = Path(p)
            string_var.set(str(native_path))
