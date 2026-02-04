import os
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from natsort import natsort_keygen
from send2trash import send2trash

from koma.core.scanner import Scanner
from koma.ui.base_tab import BaseTab
from koma.ui.utils import get_sans_font
from koma.utils import logger


class SacnTab(BaseTab):
    def __init__(self, parent, config, processor, status_callback):
        super().__init__(parent, config, processor, status_callback)

        self.path_var = tk.StringVar()
        self.ad_scan_var = tk.BooleanVar(value=self.config.scanner.enable_ad_scan)
        self.columns_config = [
            ("category", "类别", 60, "center", True),
            ("name", "文件名", 250, "w", True),
            ("type", "类型", 60, "w", True),
            ("path", "位置", 400, "w", True),
            ("abspath", "完整路径", 0, "w", False),
        ]
        self.header_map = {item[0]: item[1] for item in self.columns_config}

        self._setup_ui()

    def _setup_ui(self):
        desc = "遍历文件夹，扫描并清理其中的广告图片及垃圾文件。"
        ttk.Label(self, text=desc, foreground="#666").pack(
            anchor="w", padx=10, pady=(15, 5)
        )

        # 顶部设置区
        top_frame = ttk.Frame(self)
        top_frame.pack(fill="x", padx=10, pady=10)

        path_grp = ttk.LabelFrame(top_frame, text="扫描目标", padding=10)
        path_grp.pack(fill="x", side="top")
        path_grp.columnconfigure(1, weight=1)

        ttk.Label(path_grp, text="路径:").grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(path_grp, textvariable=self.path_var)
        entry.grid(row=0, column=1, sticky="ew", padx=5)
        self._setup_dnd(entry, self.path_var)

        ttk.Button(
            path_grp, text="选择...", command=lambda: self.select_dir(self.path_var)
        ).grid(row=0, column=2)

        ttk.Checkbutton(path_grp, text="检测广告图片", variable=self.ad_scan_var).grid(
            row=1, column=1, sticky="w", pady=(10, 5)
        )

        self.btn_scan = ttk.Button(path_grp, text="🔍 开始扫描", command=self._start)
        self.btn_scan.grid(
            row=2, column=0, columnspan=3, sticky="ew", pady=(5, 0), ipady=5
        )

        # 列表区
        list_frame = ttk.LabelFrame(
            self, text="杂项文件（双击打开文件位置）", padding=10
        )
        list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        font_name = get_sans_font(self.config.app.font)
        font_size = self.config.app.font_size
        style = ttk.Style()
        style.configure("Treeview", font=(font_name, font_size))

        all_columns = [item[0] for item in self.columns_config]
        visible_columns = [item[0] for item in self.columns_config if item[4]]
        self.tree = ttk.Treeview(
            list_frame,
            columns=all_columns,
            displaycolumns=visible_columns,
            show="headings",
            selectmode="extended",
        )
        for col_id, text, width, anchor, _ in self.columns_config:
            self.tree.heading(
                col_id,
                text=text,
                command=lambda c=col_id: self._sort_tree(c, False),
            )
            self.tree.column(col_id, width=width, anchor=anchor)  # type: ignore

        scrollbar = ttk.Scrollbar(
            list_frame, orient="vertical", command=self.tree.yview
        )
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", self._on_dblclick)

        # 底部按钮
        action_frame = ttk.Frame(self, padding=10)
        action_frame.pack(fill="x", side="bottom")
        ttk.Button(action_frame, text="全选", command=self._select_all).pack(
            side="left"
        )
        self.btn_delete = ttk.Button(
            action_frame, text="删除选中到回收站", command=self._delete_selected
        )
        self.btn_delete.pack(side="right", padx=5)

    def _start(self):
        path = self.path_var.get()
        if not path:
            return messagebox.showerror("提示", "请选择目标文件夹")

        for item in self.tree.get_children():
            self.tree.delete(item)

        self.btn_scan.config(state="disabled")
        threading.Thread(target=self._run_thread, args=(path,), daemon=True).start()

    def _run_thread(self, path):
        try:
            self.update_status("正在扫描...", indeterminate=True)
            self.config.scanner.enable_ad_scan = self.ad_scan_var.get()

            def cb(curr, total, msg):
                self.after(
                    0,
                    lambda: self.update_status(
                        msg, (curr / total * 100) if total else 0
                    ),
                )

            scanner = Scanner(Path(path), self.config.extensions, self.image_processor)

            count_ad, count_junk = 0, 0
            for _, res in scanner.run(progress_callback=cb):
                for f in res.ads:
                    self.after(0, lambda f=f: self._add_item("广告", f))
                    count_ad += 1
                for f in res.junk:
                    self.after(0, lambda f=f: self._add_item("杂项", f))
                    count_junk += 1

            self.after(
                0,
                lambda: self.update_status(
                    f"扫描完成: 发现 {count_ad} 个广告, {count_junk} 个杂项", 100, False
                ),
            )
        except Exception as e:
            logger.error(f"扫描出错: {e}")
            self.update_status("扫描出错")
        finally:
            self.after(0, lambda: self.btn_scan.config(state="normal"))

    def _add_item(self, type_str, path):
        self.tree.insert(
            "",
            "end",
            values=(type_str, path.name, path.suffix, str(path.parent), str(path)),
        )

    def _on_dblclick(self, event):
        item = self.tree.selection()
        if not item:
            return
        path = self.tree.item(item[0], "values")[4]
        try:
            if os.name == "nt":
                subprocess.run(["explorer", "/select,", path])
            else:
                subprocess.run(["xdg-open", str(Path(path).parent)])
        except Exception:
            pass

    def _select_all(self):
        self.tree.selection_add(self.tree.get_children())

    def _delete_selected(self):
        items = self.tree.selection()
        if not items:
            return
        if not messagebox.askyesno("确认", f"删除选中的 {len(items)} 个文件？"):
            return

        for item in items:
            path = self.tree.item(item, "values")[4]
            try:
                send2trash(path)
                self.tree.delete(item)
            except Exception as e:
                logger.error(f"删除失败: {e}")

    def _sort_tree(self, col, reverse):
        """对结果列表进行自然排序"""
        res = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]
        key_func = natsort_keygen()
        res.sort(key=lambda t: key_func(t[0]), reverse=reverse)

        for index, (_, k) in enumerate(res):
            self.tree.move(k, "", index)

        for c_id, text in self.header_map.items():
            self.tree.heading(
                c_id, text=text, command=lambda _c=c_id: self._sort_tree(_c, False)
            )

        arrow = "▼" if reverse else "▲"
        new_text = f"{self.header_map[col]} {arrow}"

        self.tree.heading(
            col, text=new_text, command=lambda: self._sort_tree(col, not reverse)
        )
