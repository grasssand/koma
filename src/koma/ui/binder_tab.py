import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from tkinterdnd2 import DND_FILES

from koma.core.archive import ArchiveHandler
from koma.core.binder import Binder
from koma.ui.base_tab import BaseTab
from koma.ui.utils import get_sans_font
from koma.utils import logger


class BinderTab(BaseTab):
    def __init__(self, parent, config, processor, status_callback):
        super().__init__(parent, config, processor, status_callback)
        self.out_var = tk.StringVar()
        self._setup_ui()

    def _setup_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        ttk.Label(
            self,
            text="将多个文件、文件夹、压缩包按顺序合并整理到新文件夹。",
            foreground="#666",
        ).grid(row=0, sticky="w", padx=10, pady=15)

        # 列表区
        list_frame = ttk.LabelFrame(self, text="合集内容（支持拖拽排序）", padding=5)
        list_frame.grid(row=1, sticky="nsew", padx=10)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(list_frame, columns=("type", "path"), show="headings")
        self.tree.heading("type", text="类型")
        self.tree.column("type", width=60, anchor="center", stretch=False)
        self.tree.heading("path", text="路径")
        self.tree.column("path", width=400, anchor="w")

        self._setup_tree_dnd()

        scr = ttk.Scrollbar(list_frame, command=self.tree.yview)
        self.tree.config(yscrollcommand=scr.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scr.grid(row=0, column=1, sticky="ns")

        # 鼠标拖拽行
        self.tree.bind("<ButtonPress-1>", self._on_drag_start)
        self.tree.bind("<B1-Motion>", self._on_drag_motion)
        self.tree.bind("<ButtonRelease-1>", self._on_drag_release)
        self.drag_item = None
        self.drag_ghost = None

        # 初始化拖拽状态变量
        self.drag_source_item = None
        # 按钮区
        btn_frame = ttk.Frame(list_frame)
        btn_frame.grid(row=0, column=2, sticky="ns", padx=5)
        ttk.Button(btn_frame, text="📄 添加文件", command=self._add_file).pack(
            fill="x", pady=2
        )
        ttk.Button(btn_frame, text="📁 添加目录", command=self._add_dir).pack(
            fill="x", pady=2
        )
        ttk.Separator(btn_frame).pack(fill="x", pady=5)
        ttk.Button(btn_frame, text="▲ 上移", command=self._up).pack(fill="x", pady=2)
        ttk.Button(btn_frame, text="▼ 下移", command=self._down).pack(fill="x", pady=2)
        ttk.Button(btn_frame, text="❌ 移除", command=self._remove).pack(
            fill="x", pady=2
        )
        ttk.Button(btn_frame, text="⚠️ 清空", command=self._clear_all).pack(
            fill="x", pady=2
        )

        # 输出区
        out_frame = ttk.Frame(self, padding=10)
        out_frame.grid(row=2, sticky="ew")
        ttk.Label(out_frame, text="保存位置:").pack(side="left")
        e = ttk.Entry(out_frame, textvariable=self.out_var)
        e.pack(side="left", fill="x", expand=True, padx=5)
        self._setup_dnd(e, self.out_var)
        ttk.Button(
            out_frame,
            text="...",
            width=4,
            command=lambda: self.select_dir(self.out_var),
        ).pack(side="left")

        self.btn_run = ttk.Button(self, text="📦 开始装订", command=self._start)
        self.btn_run.grid(row=3, sticky="ew", padx=40, pady=(0, 20), ipady=5)

    def _on_drag_start(self, event):
        """鼠标按下：生成美化版的幽灵窗口"""
        item = self.tree.identify_row(event.y)
        if not item:
            return

        self.drag_item = item

        vals = self.tree.item(item, "values")
        if not vals:
            return

        file_type = vals[0]
        file_path = vals[1]

        icon = "📂" if "目录" in str(file_type) or "." not in str(file_type) else "📄"
        display_text = f" {icon} {Path(file_path).name} "

        self.drag_ghost = tk.Toplevel(self)
        self.drag_ghost.overrideredirect(True)
        self.drag_ghost.attributes("-alpha", 0.90)
        self.drag_ghost.attributes("-topmost", True)

        border_frame = tk.Frame(
            self.drag_ghost,
            bg="#0078D7",
            padx=1,
            pady=1,
        )
        border_frame.pack(fill="both", expand=True)

        inner_frame = tk.Frame(border_frame, bg="#191724")
        inner_frame.pack(fill="both", expand=True)

        # 标签：白字，微软雅黑/Arial
        lbl = tk.Label(
            inner_frame,
            text=display_text,
            bg="#1f1d2e",
            fg="#e0def4",
            font=(get_sans_font(), 10),
            pady=5,
            padx=10,
        )
        lbl.pack()

        self.drag_ghost.geometry(f"+{event.x_root + 12}+{event.y_root + 12}")

    def _on_drag_motion(self, event):
        """拖拽中：移动幽灵，高亮目标"""
        if not self.drag_ghost:
            return

        self.drag_ghost.geometry(f"+{event.x_root + 15}+{event.y_root + 10}")

        target = self.tree.identify_row(event.y)

        if target:
            self.tree.selection_set(target)

    def _on_drag_release(self, event):
        """松开鼠标：执行移动，销毁幽灵"""
        if self.drag_ghost:
            self.drag_ghost.destroy()
            self.drag_ghost = None

        if not self.drag_item:
            return

        target = self.tree.identify_row(event.y)

        if target and target != self.drag_item:
            idx = self.tree.index(target)
            self.tree.move(self.drag_item, "", idx)

        elif not target:
            self.tree.move(self.drag_item, "", "end")

        self.tree.selection_set(self.drag_item)
        self.drag_item = None

    def _setup_tree_dnd(self):
        self.tree.drop_target_register(DND_FILES)  # type: ignore
        self.tree.dnd_bind("<<Drop>>", self._on_tree_drop)  # type: ignore

    def _on_tree_drop(self, event):
        if not event.data:
            return
        paths = self.tk.splitlist(event.data)
        for p in paths:
            self._insert_path(Path(p))

    def _insert_path(self, path: Path):
        icon = "📁" if path.is_dir() else "📄"
        self.tree.insert("", "end", values=(icon, str(path)))
        if not self.out_var.get():
            name = path.stem if path.is_file() else path.name
            self.out_var.set(str(path.parent / f"(合集) {name}"))

    def _add_file(self):
        files = filedialog.askopenfilenames()
        for f in files:
            self._insert_path(Path(f))

    def _add_dir(self):
        d = filedialog.askdirectory()
        if d:
            self._insert_path(Path(d))

    def _remove(self):
        for item in self.tree.selection():
            self.tree.delete(item)

    def _up(self):
        for item in self.tree.selection():
            idx = self.tree.index(item)
            if idx > 0:
                self.tree.move(item, self.tree.parent(item), idx - 1)

    def _down(self):
        items = list(self.tree.selection())
        items.reverse()
        last = len(self.tree.get_children()) - 1
        for item in items:
            idx = self.tree.index(item)
            if idx < last:
                self.tree.move(item, self.tree.parent(item), idx + 1)

    def _clear_all(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

    def _start(self):
        items = self.tree.get_children()
        if not items:
            return messagebox.showwarning("提示", "列表为空")

        out = self.out_var.get()
        if not out:
            return messagebox.showerror("错误", "请设置输出路径")

        inputs = [Path(self.tree.item(i)["values"][1]) for i in items]

        self.btn_run.config(state="disabled")
        threading.Thread(
            target=self._run_thread, args=(inputs, out), daemon=True
        ).start()

    def _run_thread(self, inputs, out):
        try:
            self.update_status("正在初始化...", 0)
            archive_handler = ArchiveHandler(self.config.extensions)
            binder = Binder(Path(out), self.config.extensions, archive_handler)

            def cb(c, t, m):
                val = (c / t * 100) if t and t > 0 else 0
                self.after(0, lambda: self.update_status(m, val))

            binder.run(inputs, progress_callback=cb)

            self.after(0, lambda: self.update_status("装订完成", 100))
            messagebox.showinfo("成功", "装订完成")
        except Exception as e:
            msg = str(e)
            logger.error(f"装订错误: {msg}", exc_info=True)
            self.after(0, lambda: self.update_status(f"失败: {msg}", 0))
            messagebox.showerror("错误", msg)
        finally:
            self.after(0, lambda: self.btn_run.config(state="normal"))
            self.after(0, lambda: self.update_status("", None, False))
