import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from koma.config import ARCHIVE_OUTPUT_FORMATS
from koma.core.renamer import RenameBatchError, Renamer
from koma.ui.base_tab import BaseTab
from koma.utils import logger


class RenameTab(BaseTab):
    def __init__(self, parent, config, processor, status_callback):
        super().__init__(parent, config, processor, status_callback)
        self.path_var = tk.StringVar()
        self.filename_prefix_var = tk.StringVar(value="")
        self.filename_start_index_var = tk.IntVar(value=0)
        self.csv_var = tk.BooleanVar(value=False)
        self.enable_archive_scan_var = tk.BooleanVar(value=False)
        default_fmt = ARCHIVE_OUTPUT_FORMATS[0] if ARCHIVE_OUTPUT_FORMATS else "zip"
        self.pack_fmt_var = tk.StringVar(value=default_fmt)

        self._setup_ui()

    def _setup_ui(self):
        desc = "遍历文件夹，对同文件夹内的所有图片进行【原地重命名】(000, 001...)。\n此操作不可逆！"
        ttk.Label(self, text=desc, foreground="#666").pack(anchor="w", padx=10, pady=15)

        grp = ttk.LabelFrame(self, text="目标文件夹", padding=10)
        grp.pack(fill="x", padx=10, pady=10)

        g1 = ttk.Frame(grp)
        g1.pack(fill="x", pady=10)

        entry = ttk.Entry(g1, textvariable=self.path_var)
        entry.pack(side="left", fill="x", expand=True)
        self._setup_dnd(entry, self.path_var)

        ttk.Button(
            g1, text="选择...", command=lambda: self.select_dir(self.path_var)
        ).pack(side="left", padx=(5, 0))

        g2 = ttk.Frame(grp)
        g2.pack(fill="x", pady=10)
        ttk.Checkbutton(
            g2,
            text="包括压缩包（处理完成将删除原文件至回收站）",
            variable=self.enable_archive_scan_var,
            command=self._toggle_fmt,
        ).pack(side="left")

        ttk.Label(g2, text="重打包格式:").pack(side="left", padx=(10, 5))
        self.cbo_fmt = ttk.Combobox(
            g2,
            textvariable=self.pack_fmt_var,
            values=ARCHIVE_OUTPUT_FORMATS,
            state="disabled",
            width=6,
        )
        self.cbo_fmt.pack(side="left")

        # === 选项区域 ===
        grp_settings = ttk.LabelFrame(self, text="重命名配置", padding=10)
        grp_settings.pack(fill="x", padx=10, pady=5)

        f1 = ttk.Frame(grp_settings)
        f1.pack(fill="x", pady=10)

        ttk.Label(f1, text="重命名前缀:").pack(side="left")
        ttk.Entry(f1, textvariable=self.filename_prefix_var, width=12).pack(
            side="left", padx=10
        )
        ttk.Label(f1, text="起始编号:").pack(side="left")
        ttk.Spinbox(
            f1, from_=0, to=9999, textvariable=self.filename_start_index_var, width=8
        ).pack(side="left", padx=10)

        f2 = ttk.Frame(grp_settings)
        f2.pack(fill="x", pady=10)
        ttk.Checkbutton(f2, text="导出重命名映射表", variable=self.csv_var).pack(
            side="left"
        )

        self.btn_start = ttk.Button(self, text="🎯 开始重命名", command=self._start)
        self.btn_start.pack(side="top", fill="x", padx=40, pady=30, ipady=5)

    def _toggle_fmt(self):
        """联动控制格式选择框的状态"""
        state = "readonly" if self.enable_archive_scan_var.get() else "disabled"
        self.cbo_fmt.config(state=state)

    def _start(self):
        path = self.path_var.get()
        if not path:
            return messagebox.showerror("错误", "请选择路径")

        try:
            options = {
                "export_csv": self.csv_var.get(),
                "prefix": self.filename_prefix_var.get(),
                "start_index": self.filename_start_index_var.get(),
                "enable_archive_scan": self.enable_archive_scan_var.get(),
                "pack_format": self.pack_fmt_var.get(),
            }
        except (tk.TclError, ValueError):
            return messagebox.showerror("错误", "起始编号必须是非负整数")
        if options["start_index"] < 0:
            return messagebox.showerror("错误", "起始编号不能为负数")

        warn_msg = "确定要执行重命名吗？操作不可逆。"
        if options["enable_archive_scan"]:
            warn_msg += "\n\n注意：已勾选处理压缩包，原压缩文件将被移至回收站。"

        if not messagebox.askyesno("警告", warn_msg):
            return

        self.btn_start.config(state="disabled")
        self.start_file_task(self._run_thread, path, options)

    def _run_thread(self, path, options):
        try:
            self.safe_update_status("正在初始化...", indeterminate=True)

            def on_progress(curr, total, msg):
                pct = (curr / total * 100) if total > 0 else 0
                self.call_in_main_thread(lambda: self.update_status(msg, pct, False))

            renamer = Renamer(Path(path), self.config.extensions, self.image_processor)
            renamer.run(options=options, progress_callback=on_progress)
            self.call_in_main_thread(
                lambda: self.update_status("重命名完成", 100, False)
            )
            self.call_in_main_thread(lambda: messagebox.showinfo("成功", "重命名完成"))
        except RenameBatchError as e:
            logger.error(f"重命名未全部完成: {e}", exc_info=True)
            msg = f"{e}\n已完成 {len(e.rows)} 项，存在未完成项目。"
            self.call_in_main_thread(
                lambda: self.update_status("重命名部分失败", 0, False)
            )
            self.call_in_main_thread(lambda: messagebox.showwarning("部分失败", msg))
        except Exception as e:
            logger.error(f"重命名失败: {e}", exc_info=True)
            self.safe_update_status("重命名失败", 0, False)
            msg = str(e)
            self.call_in_main_thread(lambda: messagebox.showerror("错误", msg))
        finally:
            self.call_in_main_thread(lambda: self.btn_start.config(state="normal"))
