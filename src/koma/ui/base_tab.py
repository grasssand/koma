import queue
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, ttk

from tkinterdnd2 import DND_FILES

from koma.config import GlobalConfig
from koma.core.image_processor import ImageProcessor
from koma.utils import logger

_FILE_TASK_LOCK = threading.Lock()
_ACTIVE_TASKS_LOCK = threading.Lock()
_ACTIVE_FILE_TASKS = 0


def active_file_tasks() -> int:
    with _ACTIVE_TASKS_LOCK:
        return _ACTIVE_FILE_TASKS


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
        self._ui_thread_id = threading.get_ident()
        self._ui_queue = queue.Queue()
        self._ui_root = self.winfo_toplevel()
        self._ui_root.after(20, self._drain_ui_queue)

    def call_in_main_thread(self, callback: Callable, *, wait: bool = False):
        """将 GUI 回调投递到主线程执行。"""
        if threading.get_ident() == self._ui_thread_id:
            callback()
            return

        completed = threading.Event() if wait else None
        self._ui_queue.put((callback, completed))
        if completed:
            completed.wait()

    def _drain_ui_queue(self):
        for _ in range(100):
            try:
                callback, completed = self._ui_queue.get_nowait()
            except queue.Empty:
                break

            try:
                callback()
            except Exception:
                logger.exception("执行界面回调失败")
            finally:
                if completed:
                    completed.set()

        try:
            self._ui_root.after(20, self._drain_ui_queue)
        except tk.TclError:
            pass

    def start_file_task(self, target: Callable, *args, **kwargs):
        """串行执行文件任务，并在任务结束前刷新已投递的界面更新。"""
        global _ACTIVE_FILE_TASKS
        with _ACTIVE_TASKS_LOCK:
            _ACTIVE_FILE_TASKS += 1

        def run():
            global _ACTIVE_FILE_TASKS
            try:
                with _FILE_TASK_LOCK:
                    target(*args, **kwargs)
            finally:
                self.call_in_main_thread(lambda: None, wait=True)
                with _ACTIVE_TASKS_LOCK:
                    _ACTIVE_FILE_TASKS -= 1

        thread = threading.Thread(target=run, daemon=False)
        try:
            thread.start()
        except Exception:
            with _ACTIVE_TASKS_LOCK:
                _ACTIVE_FILE_TASKS -= 1
            raise

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
        self.call_in_main_thread(lambda: self.update_status(text, value, indeterminate))

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

    def select_dir(self, string_var: tk.StringVar):
        """通用目录选择"""
        initial = string_var.get()
        if not initial or not Path(initial).exists():
            initial = None

        p = filedialog.askdirectory(initialdir=initial)
        if p:
            native_path = Path(p)
            string_var.set(str(native_path))
