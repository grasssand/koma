import os
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from natsort import natsort_keygen
from send2trash import send2trash

from koma.config import ARCHIVE_OUTPUT_FORMATS
from koma.core.scanner import Scanner
from koma.ui.base_tab import BaseTab
from koma.ui.utils import get_sans_font
from koma.utils import logger


class SacnTab(BaseTab):
    def __init__(self, parent, config, processor, status_callback):
        super().__init__(parent, config, processor, status_callback)

        # 变量初始化
        self.path_var = tk.StringVar()
        self.ad_scan_var = tk.BooleanVar(value=self.config.scanner.enable_ad_scan)

        self.archive_scan_var = tk.BooleanVar(
            value=self.config.scanner.enable_archive_scan
        )
        self.archive_out_path_var = tk.StringVar()
        self.repack_var = tk.BooleanVar(value=True)
        default_fmt = ARCHIVE_OUTPUT_FORMATS[0] if ARCHIVE_OUTPUT_FORMATS else "zip"
        self.pack_fmt_var = tk.StringVar(value=default_fmt)

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

        # === 扫描配置区域 ===
        path_grp = ttk.LabelFrame(top_frame, text="扫描配置", padding=10)
        path_grp.pack(fill="x", side="top")
        path_grp.columnconfigure(1, weight=1)

        ttk.Label(path_grp, text="路径:").grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(path_grp, textvariable=self.path_var)
        entry.grid(row=0, column=1, sticky="ew", padx=5)
        self._setup_dnd(entry, self.path_var)
        ttk.Button(
            path_grp, text="选择...", command=lambda: self.select_dir(self.path_var)
        ).grid(row=0, column=2)

        chk_frame = ttk.Frame(path_grp)
        chk_frame.grid(row=1, column=0, columnspan=3, sticky="w", pady=(10, 0))

        ttk.Checkbutton(chk_frame, text="检测广告图片", variable=self.ad_scan_var).pack(
            side="left", padx=(0, 15)
        )

        ttk.Separator(chk_frame, orient="vertical").pack(side="left", fill="y", padx=15)

        chk_archive = ttk.Checkbutton(
            chk_frame,
            text="包括压缩包（自动清理删除）",
            variable=self.archive_scan_var,
            command=self._toggle_archive_options,
        )
        chk_archive.pack(side="left")

        self.archive_opts_frame = ttk.Frame(path_grp)
        self.archive_opts_frame.grid(
            row=2, column=0, columnspan=3, sticky="ew", padx=20, pady=5
        )
        self.archive_opts_frame.columnconfigure(1, weight=1)

        ttk.Label(self.archive_opts_frame, text="输出路径:").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Entry(self.archive_opts_frame, textvariable=self.archive_out_path_var).grid(
            row=0, column=1, sticky="ew", padx=5
        )
        ttk.Button(
            self.archive_opts_frame,
            text="选择...",
            command=lambda: self.select_dir(self.archive_out_path_var),
        ).grid(row=0, column=2)

        opts_sub = ttk.Frame(self.archive_opts_frame)
        opts_sub.grid(row=1, column=0, columnspan=3, sticky="w", pady=5)

        ttk.Checkbutton(
            opts_sub,
            text="重新打包",
            variable=self.repack_var,
            command=self._toggle_repack_state,
        ).pack(side="left")

        ttk.Separator(opts_sub, orient="vertical").pack(side="left", fill="y", padx=10)

        ttk.Label(opts_sub, text="格式:").pack(side="left")
        self.cbo_fmt = ttk.Combobox(
            opts_sub,
            textvariable=self.pack_fmt_var,
            values=ARCHIVE_OUTPUT_FORMATS,
            state="readonly",
            width=5,
        )
        self.cbo_fmt.pack(side="left", padx=5)

        # 初始状态隐藏
        self._toggle_archive_options()

        self.btn_scan = ttk.Button(path_grp, text="🔍 开始扫描", command=self._start)
        self.btn_scan.grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=(10, 0), ipady=5
        )

        # === 列表区 ===
        list_frame = ttk.LabelFrame(self, text="待处理文件 (杂项/广告)", padding=10)
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
            self.tree.column(col_id, width=width, anchor=anchor)

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

    def _toggle_archive_options(self):
        if self.archive_scan_var.get():
            self.archive_opts_frame.grid()

            input_path = self.path_var.get()
            if input_path and not self.archive_out_path_var.get():
                try:
                    p = Path(input_path).resolve()
                    stem_name = p.name if p.name else f"{p.drive.strip(':')}_Drive"
                    default_out = p.parent / f"{stem_name}_output"
                    self.archive_out_path_var.set(str(default_out))
                except Exception:
                    pass
        else:
            self.archive_opts_frame.grid_remove()

    def _toggle_repack_state(self):
        state = "readonly" if self.repack_var.get() else "disabled"
        self.cbo_fmt.config(state=state)

    def _start(self):
        path = self.path_var.get()
        if not path:
            return messagebox.showerror("提示", "请选择目标文件夹")

        options = {
            "enable_ad_scan": self.ad_scan_var.get(),
            "enable_archive_scan": self.archive_scan_var.get(),
            "archive_out_path": self.archive_out_path_var.get(),
            "repack": self.repack_var.get(),
            "pack_format": self.pack_fmt_var.get(),
        }

        if options["enable_archive_scan"] and not options["archive_out_path"]:
            return messagebox.showerror("提示", "启用压缩包处理时，必须设置输出路径")

        for item in self.tree.get_children():
            self.tree.delete(item)

        self.btn_scan.config(state="disabled")
        threading.Thread(
            target=self._run_thread, args=(path, options), daemon=True
        ).start()

    def _run_thread(self, path, options):
        try:
            self.update_status("正在扫描...", indeterminate=True)
            self.config.scanner.enable_ad_scan = options["enable_ad_scan"]

            def cb(curr, total, msg):
                self.after(
                    0,
                    lambda: self.update_status(
                        msg, (curr / total * 100) if total else 0
                    ),
                )

            scanner = Scanner(Path(path), self.config.extensions, self.image_processor)

            count_ad, count_junk, count_archive = 0, 0, 0
            for _, res in scanner.run(options=options, progress_callback=cb):
                for f in res.ads:
                    self.after(0, lambda f=f: self._add_item("广告", f))
                    count_ad += 1
                for f in res.junk:
                    self.after(0, lambda f=f: self._add_item("杂项", f))
                    count_junk += 1

                count_archive += res.processed_archives

            msg = f"扫描完成: 发现 {count_ad} 个广告, {count_junk} 个杂项"
            if count_archive > 0:
                msg += f"，已处理 {count_archive} 个压缩包"

            self.after(0, lambda: self.update_status(msg, 100, False))

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
