import os
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from natsort import natsort_keygen
from PIL import Image, ImageTk
from send2trash import send2trash

from koma.config import ARCHIVE_OUTPUT_FORMATS
from koma.core.scanner import Scanner
from koma.ui.base_tab import BaseTab
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

        # 视图相关变量
        self.scanned_items = []  # 存储扫描结果字典列表
        self.view_mode = "list"  # "list" | "grid"
        self.image_cache = []  # 图片缓存防止GC

        # 分页与布局参数
        self.loaded_count = 0  # 当前已渲染数量
        self.BATCH_SIZE = 50  # 每次加载数量
        self.grid_row = 0
        self.grid_col = 0
        self.COLUMNS_PER_ROW = 5  # 初始默认值
        self.CARD_WIDTH = 120  # 卡片宽度
        self.CARD_PADDING = 6  # 左右间距总和
        self.SLOT_WIDTH = self.CARD_WIDTH + self.CARD_PADDING

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

        self._toggle_archive_options()

        self.btn_scan = ttk.Button(path_grp, text="🔍 开始扫描", command=self._start)
        self.btn_scan.grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=(10, 0), ipady=5
        )

        # === 底部按钮 ===
        action_frame = ttk.Frame(self, padding=10)
        action_frame.pack(fill="x", side="bottom")
        ttk.Button(action_frame, text="全选", command=self._select_all).pack(
            side="left"
        )
        ttk.Button(action_frame, text="取消选择", command=self._deselect_all).pack(
            side="left", padx=5
        )
        self.btn_delete = ttk.Button(
            action_frame, text="删除选中到回收站", command=self._delete_selected
        )
        self.btn_delete.pack(side="right", padx=5)

        # === 内容显示区 ===
        self.main_content = ttk.LabelFrame(
            self, text="扫描结果（双击打开文件位置）", padding=10
        )
        self.main_content.pack(fill="both", expand=True, padx=10, pady=(0, 5))

        # 切换视图按钮
        self.btn_toggle = ttk.Button(
            self.main_content,
            text="🪟 切换网格视图",
            command=self._toggle_view,
            state="disabled",
        )
        self.btn_toggle.pack(side="top", anchor="e", pady=(0, 5))

        # 列表模式容器
        self.tree_frame = ttk.Frame(self.main_content)
        self.tree_frame.pack(fill="both", expand=True)

        style = ttk.Style()
        style.configure(
            "Treeview",
            font=(self.config.app.font, self.config.app.list_font_size),
            rowheight=int(self.config.app.list_font_size * 2.2),
        )

        all_columns = [item[0] for item in self.columns_config]
        visible_columns = [item[0] for item in self.columns_config if item[4]]
        self.tree = ttk.Treeview(
            self.tree_frame,
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
            self.tree_frame, orient="vertical", command=self.tree.yview
        )
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._on_dblclick)

        # 网格模式容器
        self.grid_container = ttk.Frame(self.main_content)

        self.canvas = tk.Canvas(self.grid_container, bg="white")
        # 绑定大小变化事件
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        self.grid_scrollbar = ttk.Scrollbar(
            self.grid_container, orient="vertical", command=self.canvas.yview
        )
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )

        # 初始窗口
        self.canvas_window_id = self.canvas.create_window(
            (0, 0), window=self.scrollable_frame, anchor="nw"
        )
        self.canvas.configure(yscrollcommand=self.grid_scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.grid_scrollbar.pack(side="right", fill="y")

        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_canvas_resize(self, event):
        """窗口大小改变时计算列数"""
        if self.view_mode != "grid":
            return

        canvas_width = event.width

        slot_w = getattr(self, "SLOT_WIDTH", 130)

        new_cols = max(1, canvas_width // slot_w)

        self.canvas.coords(self.canvas_window_id, 10, 0)

        # 如果列数变化，触发重排
        if new_cols != self.COLUMNS_PER_ROW:
            self.COLUMNS_PER_ROW = new_cols
            self._reflow_grid()

    def _reflow_grid(self):
        """重新排列网格卡片"""
        for i in range(self.COLUMNS_PER_ROW):
            self.scrollable_frame.columnconfigure(i, weight=1, uniform="u_group")

        widgets = self.scrollable_frame.winfo_children()
        r, c = 0, 0
        for widget in widgets:
            if isinstance(widget, ttk.Button) and "加载更多" in str(
                widget.cget("text")
            ):
                if c > 0:
                    r += 1
                    c = 0
                widget.grid(row=r, column=0, columnspan=self.COLUMNS_PER_ROW, pady=20)
                r += 1
            else:
                widget.grid(row=r, column=c, padx=3, pady=3, sticky="nsew")
                c += 1
                if c >= self.COLUMNS_PER_ROW:
                    c = 0
                    r += 1
        self.grid_row = r
        self.grid_col = c

    def _on_mousewheel(self, event):
        if self.view_mode == "grid" and self.canvas.winfo_exists():
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _toggle_view(self):
        """切换视图模式"""
        if self.view_mode == "list":
            self.view_mode = "grid"
            self.tree_frame.pack_forget()
            self.grid_container.pack(fill="both", expand=True)
            self.btn_toggle.config(text="📋 切换列表视图")

            if self.loaded_count == 0 and self.scanned_items:
                self._render_next_batch()
        else:
            self.view_mode = "list"
            self.grid_container.pack_forget()
            self.tree_frame.pack(fill="both", expand=True)
            self.btn_toggle.config(text="🪟 切换网格视图")

    def _render_next_batch(self):
        """渲染下一批网格图片"""
        if hasattr(self, "btn_load_more") and self.btn_load_more:
            self.btn_load_more.destroy()
            self.btn_load_more = None

        total_items = len(self.scanned_items)
        if self.loaded_count >= total_items:
            return

        end_idx = min(self.loaded_count + self.BATCH_SIZE, total_items)
        batch = self.scanned_items[self.loaded_count : end_idx]

        for item in batch:
            self._create_grid_card(item)

        self.loaded_count = end_idx

        if self.loaded_count < total_items:
            self.btn_load_more = ttk.Button(
                self.scrollable_frame,
                text=f"加载更多 ({total_items - self.loaded_count} 个剩余)",
                command=self._render_next_batch,
            )
            if self.grid_col > 0:
                self.grid_row += 1
                self.grid_col = 0

            self.btn_load_more.grid(
                row=self.grid_row, column=0, columnspan=self.COLUMNS_PER_ROW, pady=20
            )
            self.grid_row += 1

    def _create_grid_card(self, item):
        """创建单个网格卡片"""
        path = item["path"]
        category = item["category"]
        is_image = path.suffix.lower() in self.config.extensions.all_supported_img

        # 选中样式
        bg_color = "#e1f5fe" if item["selected"] else "white"
        border_color = "blue" if item["selected"] else "#d9d9d9"
        border_width = 2 if item["selected"] else 1

        card = tk.Frame(
            self.scrollable_frame,
            borderwidth=border_width,
            relief="solid",
            bg=bg_color,
            highlightbackground=border_color,
            highlightthickness=1,
        )
        card.grid(
            row=self.grid_row, column=self.grid_col, padx=3, pady=3, sticky="nsew"
        )
        self.scrollable_frame.columnconfigure(
            self.grid_col, weight=1, uniform="u_group"
        )

        item["widget"] = card

        def on_click(event):
            self._toggle_selection(item, card)

        if is_image and Image:
            try:
                pil_img = Image.open(path)
                pil_img.thumbnail((128, 128))
                tk_img = ImageTk.PhotoImage(pil_img)
                self.image_cache.append(tk_img)
                lbl = tk.Label(card, image=tk_img, bg=bg_color)
                lbl.pack(pady=2)
                lbl.bind("<Button-1>", on_click)
                lbl.bind("<Double-1>", lambda e, p=path: self._on_dblclick(None, p))
            except Exception:
                lbl = tk.Label(card, text="❌", bg=bg_color)
                lbl.pack(pady=20)
                lbl.bind("<Button-1>", on_click)
                lbl.bind("<Double-1>", lambda e, p=path: self._on_dblclick(None, p))
        else:
            txt = "🖼️" if is_image else "📄"
            lbl = tk.Label(
                card,
                text=txt,
                font=(self.config.app.font, 36),
                bg=bg_color,
            )
            lbl.pack(pady=20)
            lbl.bind("<Button-1>", on_click)
            lbl.bind("<Double-1>", lambda e, p=path: self._on_dblclick(None, p))

        # 类别
        fg = "red" if category == "广告" else "blue"
        lbl_cat = tk.Label(
            card,
            text=category,
            fg=fg,
            bg=bg_color,
            font=(self.config.app.font, 14, "bold"),
        )
        lbl_cat.pack()
        lbl_cat.bind("<Button-1>", on_click)
        lbl_cat.bind("<Double-1>", lambda e, p=path: self._on_dblclick(None, p))

        # 文件名
        lbl_name = tk.Label(
            card,
            text=item["name"],
            wraplength=110,
            font=(self.config.app.font, self.config.app.list_font_size),
            bg=bg_color,
        )
        lbl_name.pack(padx=2, pady=(0, 2))
        lbl_name.bind("<Button-1>", on_click)

        card.bind("<Button-1>", on_click)

        # 维护索引
        self.grid_col += 1
        if self.grid_col >= self.COLUMNS_PER_ROW:
            self.grid_col = 0
            self.grid_row += 1

    def _toggle_selection(self, item, card_widget):
        """切换选中状态并更新视觉"""
        item["selected"] = not item["selected"]
        is_sel = item["selected"]

        bg_color = "#e1f5fe" if is_sel else "white"
        border_color = "blue" if is_sel else "#d9d9d9"
        border_width = 2 if is_sel else 1

        try:
            card_widget.config(
                bg=bg_color, highlightbackground=border_color, borderwidth=border_width
            )
            for child in card_widget.winfo_children():
                try:
                    child.config(bg=bg_color)
                except Exception:
                    pass
        except Exception:
            pass

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

        # 清空数据
        for item in self.tree.get_children():
            self.tree.delete(item)

        self.scanned_items.clear()
        self.image_cache.clear()
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.loaded_count = 0
        self.grid_row = 0
        self.grid_col = 0

        # 重置回列表视图
        if self.view_mode == "grid":
            self._toggle_view()
        self.btn_toggle.config(state="disabled")

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

            def on_scan_finished():
                self.btn_scan.config(state="normal")

                # 只有扫描到了结果，才允许切换视图
                if self.scanned_items:
                    self.btn_toggle.config(state="normal")
                else:
                    self.btn_toggle.config(state="disabled")

            self.after(0, on_scan_finished)

    def _add_item(self, type_str, path):
        self.tree.insert(
            "",
            "end",
            values=(type_str, path.name, path.suffix, str(path.parent), str(path)),
        )

        self.scanned_items.append(
            {
                "category": type_str,
                "path": path,
                "name": path.name,
                "selected": False,
                "widget": None,
            }
        )

        # if str(self.btn_toggle["state"]) == "disabled":
        #     self.btn_toggle.config(state="normal")

    def _on_dblclick(self, event, path=None):
        if path is None and event:
            item = self.tree.selection()
            if not item:
                return
            path = self.tree.item(item[0], "values")[4]

        if not path:
            return

        try:
            if os.name == "nt":
                subprocess.run(["explorer", "/select,", str(path)])
            else:
                subprocess.run(["xdg-open", str(Path(path).parent)])
        except Exception:
            pass

    def _select_all(self):
        """全选功能"""
        if self.view_mode == "list":
            self.tree.selection_add(self.tree.get_children())
        else:
            for item in self.scanned_items:
                if not item["selected"]:
                    if item["widget"]:
                        self._toggle_selection(item, item["widget"])
                    else:
                        item["selected"] = True

    def _deselect_all(self):
        """取消所有选择"""
        if self.view_mode == "list":
            selection = self.tree.selection()
            if selection:
                self.tree.selection_remove(selection)
        else:
            for item in self.scanned_items:
                if item["selected"]:
                    if item["widget"]:
                        self._toggle_selection(item, item["widget"])
                    else:
                        item["selected"] = False

    def _delete_selected(self):
        """删除选中项"""
        paths_to_remove = set()

        if self.view_mode == "list":
            items = self.tree.selection()
            if not items:
                return
            if not messagebox.askyesno("确认", f"删除选中的 {len(items)} 个文件？"):
                return

            for item_id in items:
                path_str = self.tree.item(item_id, "values")[4]
                paths_to_remove.add(path_str)
        else:
            selected = [x for x in self.scanned_items if x["selected"]]
            if not selected:
                return
            if not messagebox.askyesno("确认", f"删除选中的 {len(selected)} 个文件？"):
                return

            for item in selected:
                paths_to_remove.add(str(item["path"]))

        deleted_paths = set()
        for path_str in paths_to_remove:
            try:
                send2trash(path_str)
                deleted_paths.add(path_str)
            except Exception as e:
                logger.error(f"删除失败: {e}")

        if not deleted_paths:
            return

        tree_items_to_delete = []
        for item_id in self.tree.get_children():
            p_str = self.tree.item(item_id, "values")[4]
            if p_str in deleted_paths:
                tree_items_to_delete.append(item_id)

        for item_id in tree_items_to_delete:
            self.tree.delete(item_id)

        new_scanned_items = []
        deleted_widget_count = 0

        for item in self.scanned_items:
            if str(item["path"]) in deleted_paths:
                if item.get("widget"):
                    try:
                        if item["widget"].winfo_exists():
                            item["widget"].destroy()
                            deleted_widget_count += 1
                    except Exception:
                        pass
            else:
                new_scanned_items.append(item)

        self.scanned_items = new_scanned_items
        self.loaded_count = max(0, self.loaded_count - deleted_widget_count)

        self._reflow_grid()

    def _refresh_grid_view(self):
        """删除后强制刷新网格"""
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.grid_row = 0
        self.grid_col = 0
        self.loaded_count = 0
        self._render_next_batch()

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
