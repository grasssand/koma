import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from koma.config import ARCHIVE_EXTS, DOCUMENT_EXTS, SUPPORTED_IMAGE_EXTS
from koma.core import Binder
from koma.utils import logger


class BinderFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.output_path_var = tk.StringVar()

        self.on_status_update = None
        self._create_widgets()

    def set_status_callback(self, callback):
        self.on_status_update = callback

    def _create_widgets(self):
        list_frame = ttk.LabelFrame(self, text="合集内容", padding=5)
        list_frame.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        columns = ("type", "path")
        self.tree = ttk.Treeview(
            list_frame, columns=columns, show="headings", selectmode="extended"
        )
        self.tree.heading("type", text="类型")
        self.tree.heading("path", text="文件路径")
        self.tree.column("type", width=60, stretch=False, anchor="center")
        self.tree.column("path", width=400, anchor="w")

        scrollbar_y = ttk.Scrollbar(
            list_frame, orient="vertical", command=self.tree.yview
        )
        scrollbar_x = ttk.Scrollbar(
            list_frame, orient="horizontal", command=self.tree.xview
        )
        self.tree.configure(
            yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set
        )

        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        scrollbar_x.grid(row=1, column=0, sticky="ew")

        control_frame = ttk.Frame(self, padding=5)
        control_frame.grid(row=0, column=1, sticky="ns", padx=(0, 10), pady=10)

        self.btn_add_file = ttk.Button(
            control_frame, text="📄 添加文件", command=self._add_files
        )
        self.btn_add_file.pack(side="top", fill="x", pady=2)

        self.btn_add_folder = ttk.Button(
            control_frame, text="📂 添加文件夹", command=self._add_folder
        )
        self.btn_add_folder.pack(side="top", fill="x", pady=(0, 15))

        ttk.Separator(control_frame, orient="horizontal").pack(fill="x", pady=10)

        self.btn_up = ttk.Button(
            control_frame, text="▲ 上移", command=self._move_up, width=10
        )
        self.btn_up.pack(side="top", pady=2)
        self.btn_down = ttk.Button(
            control_frame, text="▼ 下移", command=self._move_down, width=10
        )
        self.btn_down.pack(side="top", pady=2)

        ttk.Separator(control_frame, orient="horizontal").pack(fill="x", pady=10)

        self.btn_remove = ttk.Button(
            control_frame, text="✕ 移除", command=self._remove_item, width=10
        )
        self.btn_remove.pack(side="top", pady=2)
        self.btn_clear = ttk.Button(
            control_frame, text="🗑 清空", command=self._clear_all, width=10
        )
        self.btn_clear.pack(side="top", pady=2)

        opt_frame = ttk.LabelFrame(self, text="输出设置", padding=10)
        opt_frame.grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10)
        )

        ttk.Label(opt_frame, text="保存位置:").pack(side="left")

        entry = ttk.Entry(opt_frame, textvariable=self.output_path_var)
        entry.pack(side="left", fill="x", expand=True, padx=5)

        btn_browse = ttk.Button(opt_frame, text="选择...", command=self._select_output)
        btn_browse.pack(side="left")

        self.btn_start = ttk.Button(
            self, text="🚀 开始装订", command=self._start_binding, state="normal"
        )
        self.btn_start.grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=40, pady=(0, 30), ipady=5
        )

    def _get_file_type_icon(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if path.is_dir():
            return "文件夹"
        elif suffix in ARCHIVE_EXTS:
            return "归档"
        elif suffix in DOCUMENT_EXTS:
            return "文档"
        elif suffix in SUPPORTED_IMAGE_EXTS:
            return "图片"
        return "?"

    def _add_to_tree(self, path: Path):
        current_items = [
            self.tree.item(item)["values"][1] for item in self.tree.get_children()
        ]
        if str(path) in current_items:
            return
        self.tree.insert("", "end", values=(self._get_file_type_icon(path), str(path)))

    def _add_files(self):
        all_exts = SUPPORTED_IMAGE_EXTS | ARCHIVE_EXTS | DOCUMENT_EXTS
        filetypes = [
            ("All Supported", " ".join(f"*{ext}" for ext in all_exts)),
            ("All Files", "*.*"),
        ]
        files = filedialog.askopenfilenames(title="选择文件", filetypes=filetypes)
        if files:
            for f in files:
                self._add_to_tree(Path(f))
            # 自动填充：如果输出路径为空，默认设置为第一个文件的父目录
            if not self.output_path_var.get():
                first_parent = Path(files[0]).parent / (Path(files[0]).stem + " 合集")
                self.output_path_var.set(str(first_parent))

    def _add_folder(self):
        folder = filedialog.askdirectory(title="选择文件夹")
        if folder:
            self._add_to_tree(Path(folder))
            if not self.output_path_var.get():
                self.output_path_var.set(
                    str(Path(folder).parent / (Path(folder).name + " 合集"))
                )

    def _remove_item(self):
        for item in self.tree.selection():
            self.tree.delete(item)

    def _clear_all(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

    def _move_up(self):
        selected = self.tree.selection()
        for item in selected:
            idx = self.tree.index(item)
            if idx > 0:
                self.tree.move(item, self.tree.parent(item), idx - 1)
        if selected:
            self.tree.see(selected[0])

    def _move_down(self):
        selected = list(self.tree.selection())
        selected.reverse()
        count = len(self.tree.get_children())
        for item in selected:
            idx = self.tree.index(item)
            if idx < count - 1:
                self.tree.move(item, self.tree.parent(item), idx + 1)
        if selected:
            self.tree.see(selected[0])

    def _select_output(self):
        path = filedialog.askdirectory(title="选择保存合集的文件夹")
        if path:
            self.output_path_var.set(path)

    def _toggle_ui_state(self, state: str):
        widgets = [
            self.btn_start,
            self.btn_up,
            self.btn_down,
            self.btn_remove,
            self.btn_clear,
            self.btn_add_file,
            self.btn_add_folder,
        ]
        for btn in widgets:
            btn.config(state=state)

    def _update_status(self, text: str, value: float = 0):
        if self.on_status_update:
            self.on_status_update(text, value)

    def _start_binding(self):
        items = self.tree.get_children()
        if not items:
            return messagebox.showwarning("提示", "请先添加要处理的文件或文件夹！")

        input_paths = [Path(self.tree.item(item)["values"][1]) for item in items]

        output_dir_str = self.output_path_var.get()
        if not output_dir_str:
            output_dir_str = filedialog.askdirectory(
                title="选择合集输出位置（将创建新文件夹）"
            )
            if not output_dir_str:
                return
            self.output_path_var.set(output_dir_str)

        output_dir = Path(output_dir_str)
        if output_dir.exists() and any(output_dir.iterdir()):
            if not messagebox.askyesno(
                "覆盖警告",
                f"输出目录 '{output_dir.name}' 非空。\n继续操作可能会覆盖同名文件，确定要继续吗？",
            ):
                return

        # 防止用户把输出目录设为输入目录之一
        if output_dir in input_paths:
            if not messagebox.askyesno(
                "警告",
                "输出目录包含在输入列表中，这可能导致无限循环或数据损坏。\n确定要继续吗？",
            ):
                return

        self._toggle_ui_state("disabled")
        self._update_status("正在初始化装订...", 0)

        threading.Thread(
            target=self._run_task_thread, args=(input_paths, output_dir), daemon=True
        ).start()

    def _run_task_thread(self, input_paths, output_dir):
        assembler = Binder(output_dir)

        def progress_cb(curr, total, msg):
            pct = (curr / total) * 100 if total > 0 else 0
            self.after(0, lambda: self._update_status(msg, pct))

        try:
            assembler.run(input_paths, progress_callback=progress_cb)
            self.after(0, lambda: self._on_task_complete(True))
        except Exception as e:
            error_msg = str(e)
            logger.error(f"装订失败: {error_msg}", exc_info=True)
            self.after(0, lambda: self._on_task_complete(False, error_msg))

    def _on_task_complete(self, success, error_msg=""):
        self._toggle_ui_state("normal")
        if success:
            self._update_status("✅ 装订完成！", 100)
            messagebox.showinfo(
                "成功", f"合集装订已完成！\n路径: {self.output_path_var.get()}"
            )
        else:
            self._update_status("❌ 发生错误", 0)
            messagebox.showerror("错误", f"任务执行失败:\n{error_msg}")
