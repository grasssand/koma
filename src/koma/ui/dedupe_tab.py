import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from koma.ui.base_tab import BaseTab
from koma.ui.dedupe_window import DedupeWindow
from koma.utils import logger


class DedupeTab(BaseTab):
    def __init__(self, parent, config, processor, status_callback):
        super().__init__(parent, config, processor, status_callback)

        self.mode_var = tk.StringVar(value="filename")
        self.threshold_var = tk.IntVar(value=85)

        self._setup_ui()

    def _setup_ui(self):
        desc = '扫描文件夹和归档文件 (zip, cbz...)，查找重复的作品。\n支持解析 "[社团/作者] 作品名 (系列)" 格式。'
        ttk.Label(self, text=desc, foreground="#666").pack(anchor="w", padx=10, pady=15)

        grp = ttk.LabelFrame(self, text="查重目标列表（支持拖拽添加）", padding=10)
        grp.pack(fill="both", expand=True, padx=10, pady=5)

        btn_frame = ttk.Frame(grp)
        btn_frame.pack(side="right", fill="y")

        self.listbox = tk.Listbox(
            grp, height=6, selectmode="extended", activestyle="none"
        )
        scr = ttk.Scrollbar(grp, command=self.listbox.yview)
        self.listbox.config(yscrollcommand=scr.set)

        self.listbox.pack(side="left", fill="both", expand=True)
        scr.pack(side="left", fill="y")

        self._setup_dnd()

        ttk.Button(btn_frame, text="📁 添加目录", command=self._add).pack(
            fill="x", pady=2
        )
        ttk.Button(btn_frame, text="❌ 移除", command=self._remove).pack(
            fill="x", pady=2
        )
        ttk.Button(
            btn_frame, text="⚠️ 清空", command=lambda: self.listbox.delete(0, tk.END)
        ).pack(fill="x", pady=2)

        # 查重方式设置
        grp_settings = ttk.LabelFrame(self, text="查重方式", padding=10)
        grp_settings.pack(fill="x", padx=10, pady=5)

        # 模式单选
        f_mode = ttk.Frame(grp_settings)
        f_mode.pack(fill="x")
        ttk.Radiobutton(
            f_mode,
            text="文件名 (快速)",
            variable=self.mode_var,
            value="filename",
            command=self._toggle_threshold,
        ).pack(side="left", padx=(0, 15))

        ttk.Radiobutton(
            f_mode,
            text="封面相似度",
            variable=self.mode_var,
            value="cover",
            command=self._toggle_threshold,
        ).pack(side="left")

        # 阈值设置
        ttk.Label(f_mode, text="  阈值:").pack(side="left", padx=(10, 0))

        self.scale_threshold = ttk.Scale(
            f_mode,
            from_=80,
            to=99,
            variable=self.threshold_var,
            orient="horizontal",
            length=100,
            command=lambda e: self.threshold_var.set(int(float(e))),
        )
        self.scale_threshold.pack(side="left", padx=5)
        self.lbl_threshold_val = ttk.Label(
            f_mode, textvariable=self.threshold_var, width=4
        )
        self.lbl_threshold_val.pack(side="left")
        self.lbl_hint = ttk.Label(
            f_mode, text="(80 - 99，值越小越宽松)", foreground="#666"
        )
        self.lbl_hint.pack(side="left")

        # 初始化阈值框的显示状态
        self._toggle_threshold()

        self.btn_run = ttk.Button(self, text="🔍 开始分析", command=self._start)
        self.btn_run.pack(fill="x", padx=40, pady=20, ipady=5)

    def _toggle_threshold(self):
        """控制阈值输入框的启用/禁用"""
        if self.mode_var.get() == "cover":
            self.scale_threshold.config(state="normal")
        else:
            self.scale_threshold.config(state="disabled")

    def _setup_dnd(self):
        """配置 Listbox 的拖拽接收"""
        super()._setup_dnd(self.listbox, self._handle_dropped_paths)

    def _handle_dropped_paths(self, paths):
        for p_str in paths:
            path = Path(p_str)
            if path.is_dir():
                self._insert_path(path)

    def _insert_path(self, path: Path):
        """添加路径到列表="""
        path_str = str(path)
        current_items = self.listbox.get(0, tk.END)

        if path_str not in current_items:
            self.listbox.insert(tk.END, path_str)

    def _add(self):
        p = filedialog.askdirectory()
        if p:
            self._insert_path(Path(p))

    def _remove(self):
        for idx in reversed(self.listbox.curselection()):
            self.listbox.delete(idx)

    def _start(self):
        paths = [Path(p) for p in self.listbox.get(0, tk.END)]
        if not paths:
            return messagebox.showwarning("提示", "请先添加文件夹")

        valid = [p for p in paths if p.exists()]
        if not valid:
            return messagebox.showerror("错误", "所有路径均无效")

        try:
            mode = self.mode_var.get()
            threshold = self.threshold_var.get()
            DedupeWindow(self.winfo_toplevel(), valid, self.config, mode, threshold)
        except Exception as e:
            logger.error(f"启动查重失败: {e}")
            messagebox.showerror("错误", str(e))
