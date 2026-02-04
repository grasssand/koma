import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from koma.core.renamer import Renamer
from koma.ui.base_tab import BaseTab
from koma.utils import logger


class RenameTab(BaseTab):
    def __init__(self, parent, config, processor, status_callback):
        super().__init__(parent, config, processor, status_callback)
        self.path_var = tk.StringVar()
        self.csv_var = tk.BooleanVar(value=False)
        self._setup_ui()

    def _setup_ui(self):
        desc = "遍历文件夹，对同文件夹内的所有图片进行【原地重命名】(000, 001...)。\n此操作不可逆！"
        ttk.Label(self, text=desc, foreground="#666").pack(anchor="w", padx=10, pady=15)

        grp = ttk.LabelFrame(self, text="目标文件夹", padding=15)
        grp.pack(fill="x", padx=10, pady=10)

        sub = ttk.Frame(grp)
        sub.pack(fill="x")

        entry = ttk.Entry(sub, textvariable=self.path_var)
        entry.pack(side="left", fill="x", expand=True)
        self._setup_dnd(entry, self.path_var)

        ttk.Button(
            sub, text="选择...", command=lambda: self.select_dir(self.path_var)
        ).pack(side="left", padx=(5, 0))

        ttk.Checkbutton(grp, text="导出重命名映射表", variable=self.csv_var).pack(
            side="left", pady=(10, 0)
        )

        self.btn_start = ttk.Button(self, text="🎯 开始重命名", command=self._start)
        self.btn_start.pack(side="top", fill="x", padx=40, pady=30, ipady=5)

    def _start(self):
        path = self.path_var.get()
        if not path:
            return messagebox.showerror("错误", "请选择路径")
        if not messagebox.askyesno("警告", "确定要执行重命名吗？操作不可逆。"):
            return

        self.btn_start.config(state="disabled")
        threading.Thread(target=self._run_thread, args=(path,), daemon=True).start()

    def _run_thread(self, path):
        try:
            self.update_status("正在初始化...", indeterminate=True)

            def on_progress(curr, total, msg):
                pct = (curr / total * 100) if total > 0 else 0
                self.after(0, lambda: self.update_status(msg, pct, False))

            # 暂时禁用广告检测以确保所有图片都被重命名
            self.config.scanner.enable_ad_scan = False

            renamer = Renamer(
                Path(path),
                self.config.extensions,
                self.image_processor,
                export_csv=self.csv_var.get(),
            )
            renamer.run(progress_callback=on_progress)

            self.after(0, lambda: self.update_status("重命名完成", 100, False))
            messagebox.showinfo("成功", "重命名完成")
        except Exception as e:
            logger.error(f"重命名失败: {e}", exc_info=True)
            self.after(0, lambda: self.update_status("失败", 0, False))
            messagebox.showerror("错误", str(e))
        finally:
            self.after(0, lambda: self.btn_start.config(state="normal"))
