import logging
import os
import shutil
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from send2trash import send2trash

from koma.config import CONVERTER_CFG, ENABLE_AD_SCAN, OUTPUT_FORMATS
from koma.core import Converter, Renamer, Scanner
from koma.ui.dedupe import DedupeWindow
from koma.ui.utils import get_monospace_font, get_sans_font
from koma.utils import logger


class TextHandler(logging.Handler):
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record):
        msg = self.format(record)
        self.text_widget.after(0, self.append_text, msg)

    def append_text(self, msg):
        self.text_widget.configure(state="normal")
        self.text_widget.insert(tk.END, msg + "\n")
        self.text_widget.see(tk.END)
        self.text_widget.configure(state="disabled")


class KomaGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("KOMA - 漫画工具箱")
        self.root.geometry("920x680")

        if not shutil.which("ffmpeg"):
            # messagebox.showwarning(
            #     "环境缺失", "未检测到 FFmpeg！\n[格式转换] 功能将无法使用。"
            # )
            logger.warning("未检测到 FFmpeg！格式转换功能将无法使用。")

        self.init_vars()
        self.create_widgets()
        self.setup_logging()
        self.toggle_quality_state()

    def init_vars(self):
        self.clean_path_var = tk.StringVar()
        self.clean_ad_scan_var = tk.BooleanVar(value=ENABLE_AD_SCAN)

        self.rename_path_var = tk.StringVar()

        self.input_path_var = tk.StringVar()
        self.output_path_var = tk.StringVar()
        self.format_var = tk.StringVar(value=CONVERTER_CFG["format"])
        self.quality_var = tk.IntVar(value=CONVERTER_CFG["quality"])
        self.lossless_var = tk.BooleanVar(value=CONVERTER_CFG["lossless"])
        self.conv_skip_ad_var = tk.BooleanVar(value=ENABLE_AD_SCAN)

        self.dedupe_path_var = tk.StringVar()

        self.progress_var = tk.DoubleVar(value=0)
        self.status_var = tk.StringVar(value="准备就绪")

    def create_widgets(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill="both", expand=True)

        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=5)

        self.tab_clean = ttk.Frame(self.notebook)
        self.tab_rename = ttk.Frame(self.notebook)
        self.tab_convert = ttk.Frame(self.notebook)
        self.tab_dedupe = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_clean, text=" 🧹 扫描清理 ")
        self.notebook.add(self.tab_rename, text=" ⚒️ 重命名 ")
        self.notebook.add(self.tab_convert, text=" 🎨 格式转换 ")
        self.notebook.add(self.tab_dedupe, text=" 📚 归档查重 ")

        self.setup_clean_tab()
        self.setup_rename_tab()
        self.setup_convert_tab()
        self.setup_dedupe_tab()

        self.setup_statusbar()
        log_frame = ttk.LabelFrame(self.root, text="运行日志", padding=5)
        log_frame.pack(fill="x", side="bottom", padx=10, pady=5)
        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=8, state="disabled", font=(get_monospace_font(), 9)
        )
        self.log_text.pack(fill="both", expand=True)

    def setup_clean_tab(self):
        """扫描清理"""
        frame = self.tab_clean

        top_frame = ttk.Frame(frame)
        top_frame.pack(fill="x", padx=10, pady=10)

        path_grp = ttk.LabelFrame(top_frame, text="扫描目标", padding=10)
        path_grp.pack(fill="x", side="top")

        sub = ttk.Frame(path_grp)
        sub.pack(fill="x")
        ttk.Entry(sub, textvariable=self.clean_path_var).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(
            sub, text="选择...", command=lambda: self.select_dir(self.clean_path_var)
        ).pack(side="left", padx=(5, 0))

        opt_grp = ttk.Frame(path_grp)
        opt_grp.pack(fill="x", pady=(10, 0))

        ttk.Checkbutton(
            opt_grp, text="检测广告图片", variable=self.clean_ad_scan_var
        ).pack(side="left")

        self.btn_scan = ttk.Button(
            opt_grp, text="🔍 开始扫描", command=self.start_clean_scan
        )
        self.btn_scan.pack(side="right", padx=5)

        list_frame = ttk.LabelFrame(
            frame, text="杂项文件（双击打开文件位置）", padding=10
        )
        list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        columns = ("type", "name", "ext", "folder", "abspath")
        self.tree_clean = ttk.Treeview(
            list_frame, columns=columns, show="headings", selectmode="extended"
        )

        self.tree_clean.heading("type", text="类别")
        self.tree_clean.heading("name", text="文件名")
        self.tree_clean.heading("ext", text="文件类型")
        self.tree_clean.heading("folder", text="位置")
        self.tree_clean.heading("abspath", text="完整路径")

        self.tree_clean.column("type", width=20, anchor="center")
        self.tree_clean.column("name", width=100, anchor="w")
        self.tree_clean.column("ext", width=40, anchor="w")
        self.tree_clean.column("folder", width=250, anchor="w")
        self.tree_clean.column("abspath", width=0, stretch=False)  # 隐藏路径列
        self.tree_clean["displaycolumns"] = ("type", "name", "ext", "folder")

        scrollbar = ttk.Scrollbar(
            list_frame, orient="vertical", command=self.tree_clean.yview
        )
        self.tree_clean.configure(yscrollcommand=scrollbar.set)

        self.tree_clean.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 绑定双击事件
        self.tree_clean.bind("<Double-1>", self.on_clean_list_dblclick)

        action_frame = ttk.Frame(frame, padding=10)
        action_frame.pack(fill="x", side="bottom")

        ttk.Button(action_frame, text="全选", command=self.clean_select_all).pack(
            side="left"
        )

        self.btn_delete = ttk.Button(
            action_frame, text="删除选中到回收站", command=self.clean_delete_selected
        )
        self.btn_delete.pack(side="right", padx=5)

    def setup_rename_tab(self):
        """重命名"""
        frame = self.tab_rename

        desc = (
            "对文件夹内的图片进行【原地重命名】 (000, 001, 002 ...)。\n此操作不可逆！"
        )
        ttk.Label(frame, text=desc, foreground="#666").pack(
            anchor="w", padx=20, pady=15
        )

        grp = ttk.LabelFrame(frame, text="目标文件夹", padding=15)
        grp.pack(fill="x", padx=20, pady=5)

        sub = ttk.Frame(grp)
        sub.pack(fill="x")
        ttk.Entry(sub, textvariable=self.rename_path_var).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(
            sub, text="选择...", command=lambda: self.select_dir(self.rename_path_var)
        ).pack(side="left", padx=(5, 0))

        self.btn_rename = ttk.Button(
            frame, text="执行重命名整理", command=self.start_rename
        )
        self.btn_rename.pack(side="top", fill="x", padx=40, pady=30, ipady=5)

    def setup_convert_tab(self):
        """格式转换"""
        frame = self.tab_convert

        grp_path = ttk.LabelFrame(frame, text="路径设置", padding=10)
        grp_path.pack(fill="x", padx=10, pady=10)

        ttk.Label(grp_path, text="输入文件夹:").grid(row=0, column=0, sticky="w")
        ttk.Entry(grp_path, textvariable=self.input_path_var).grid(
            row=0, column=1, sticky="ew", padx=5
        )
        ttk.Button(grp_path, text="浏览", command=self.select_convert_input).grid(
            row=0, column=2
        )

        ttk.Label(grp_path, text="输出文件夹:").grid(
            row=1, column=0, sticky="w", pady=5
        )
        ttk.Entry(grp_path, textvariable=self.output_path_var).grid(
            row=1, column=1, sticky="ew", padx=5, pady=5
        )
        ttk.Button(
            grp_path, text="浏览", command=lambda: self.select_dir(self.output_path_var)
        ).grid(row=1, column=2)

        ttk.Checkbutton(
            grp_path, text="跳过广告图片", variable=self.conv_skip_ad_var
        ).grid(row=2, column=1, sticky="w", pady=(5, 0))
        grp_path.columnconfigure(1, weight=1)

        grp_param = ttk.LabelFrame(frame, text="转换参数", padding=10)
        grp_param.pack(fill="x", padx=10, pady=5)

        # 格式
        f_row = ttk.Frame(grp_param)
        f_row.pack(fill="x", pady=5)
        ttk.Label(f_row, text="格式: ").pack(side="left")
        ttk.Combobox(
            f_row,
            textvariable=self.format_var,
            values=OUTPUT_FORMATS,
            state="readonly",
            width=12,
        ).pack(side="left", padx=5)
        ttk.Label(
            f_row,
            text="💡 无损推荐 jxl，有损推荐 avif（aom 转换更慢，但质量比 svt-av1 稍好）",
            foreground="gray",
        ).pack(side="left", padx=5)

        # 质量
        q_row = ttk.Frame(grp_param)
        q_row.pack(fill="x", pady=5)
        ttk.Label(q_row, text="质量: ").pack(side="left")

        self.scale = ttk.Scale(
            q_row,
            from_=1,
            to=100,
            variable=self.quality_var,
            orient="horizontal",
            command=lambda v: self.quality_var.set(int(float(v))),  # 强制转整
        )
        self.scale.pack(side="left", fill="x", expand=True, padx=5)

        self.lbl_quality = ttk.Label(q_row, textvariable=self.quality_var, width=3)
        self.lbl_quality.pack(side="left")

        # 无损
        o_row = ttk.Frame(grp_param)
        o_row.pack(fill="x", pady=5)
        self.chk_lossless = ttk.Checkbutton(
            o_row,
            text="无损模式 (Lossless)",
            variable=self.lossless_var,
            command=self.toggle_quality_state,
        )
        self.chk_lossless.pack(side="left")

        self.btn_convert = ttk.Button(
            frame, text="开始转换", command=self.start_convert
        )
        self.btn_convert.pack(fill="x", padx=20, pady=20, ipady=5)

    # 切换质量条状态
    def toggle_quality_state(self):
        if self.lossless_var.get():
            self.scale.configure(state="disabled")
            self.lbl_quality.configure(state="disabled")
        else:
            self.scale.configure(state="normal")
            self.lbl_quality.configure(state="normal")

    def setup_dedupe_tab(self):
        """归档查重"""
        frame = self.tab_dedupe

        desc = (
            "扫描多个文件夹内的归档文件 (zip, rar, cbz...) 和文件夹。\n"
            '自动识别 "[社团 / 作者] 作品名 (系列)" 等信息，找出重复文件。'
        )
        ttk.Label(frame, text=desc, foreground="#666").pack(
            anchor="w", padx=20, pady=15
        )

        grp = ttk.LabelFrame(frame, text="查重目标文件夹", padding=10)
        grp.pack(fill="both", expand=True, padx=20, pady=5)

        btn_frame = ttk.Frame(grp)
        btn_frame.pack(side="right", fill="y", padx=(5, 0))

        list_frame = ttk.Frame(grp)
        list_frame.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        self.dedupe_listbox = tk.Listbox(
            list_frame,
            selectmode="extended",
            height=6,
            yscrollcommand=scrollbar.set,
            font=(get_sans_font(), 9),
            activestyle="none",
        )
        scrollbar.config(command=self.dedupe_listbox.yview)

        self.dedupe_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        ttk.Button(btn_frame, text="添加文件夹", command=self.add_dedupe_path).pack(
            fill="x", pady=2
        )
        ttk.Button(btn_frame, text="移除选中", command=self.remove_dedupe_path).pack(
            fill="x", pady=2
        )
        ttk.Button(
            btn_frame,
            text="清空列表",
            command=lambda: self.dedupe_listbox.delete(0, tk.END),
        ).pack(fill="x", pady=2)

        action_frame = ttk.Frame(frame)
        action_frame.pack(fill="x", padx=40, pady=20)

        self.btn_dedupe = ttk.Button(
            action_frame, text="🔍 开始查重分析", command=self.start_dedupe_scan
        )
        self.btn_dedupe.pack(fill="x", ipady=5)

        # ttk.Label(frame, text="* 扫描结果将在新窗口中显示", foreground="gray").pack(
        #     pady=(0, 20)
        # )

    def add_dedupe_path(self):
        path = filedialog.askdirectory()
        if path:
            abs_path = str(Path(path).absolute())

            current_paths = self.dedupe_listbox.get(0, tk.END)
            if abs_path not in current_paths:
                self.dedupe_listbox.insert(tk.END, abs_path)

    def remove_dedupe_path(self):
        selection = self.dedupe_listbox.curselection()
        if not selection:
            return

        for index in reversed(selection):
            self.dedupe_listbox.delete(index)

    def setup_logging(self):
        """配置日志重定向"""
        text_handler = TextHandler(self.log_text)

        formatter = logging.Formatter(
            "%(asctime)s | %(message)s", datefmt="%m/%d %H:%M:%S"
        )
        text_handler.setFormatter(formatter)

        logger.addHandler(text_handler)
        logger.setLevel(logging.INFO)

    def setup_statusbar(self):
        bar = ttk.Frame(self.root, padding=(10, 0))
        bar.pack(side="bottom", fill="x")

        self.progress = ttk.Progressbar(bar, variable=self.progress_var, maximum=100)
        self.progress.pack(side="bottom", fill="x", pady=(0, 5))

        self.lbl_status = ttk.Label(
            bar, textvariable=self.status_var, font=(get_sans_font(), 9)
        )
        self.lbl_status.pack(side="left")

    def select_dir(self, var):
        p = filedialog.askdirectory()
        if p:
            var.set(p)

    def select_convert_input(self):
        p = filedialog.askdirectory()
        if p:
            self.input_path_var.set(p)
            if not self.output_path_var.get():
                self.output_path_var.set(
                    str(Path(p).parent / (Path(p).name + "_output"))
                )

    def update_status(
        self, text: str, value: float | None = None, indeterminate: bool | None = None
    ):
        self.root.after(0, lambda: self._ui_update(text, value, indeterminate))

    def _ui_update(self, text: str, value: float | None, indeterminate: bool | None):
        if text:
            self.status_var.set(text)
        if value is not None:
            self.progress_var.set(value)
        if indeterminate is not None:
            if indeterminate:
                self.progress.config(mode="indeterminate")
                self.progress.start(10)
            else:
                self.progress.stop()
                self.progress.config(mode="determinate")

    def toggle_ui(self, enable: bool):
        state = "normal" if enable else "disabled"

        if hasattr(self, "btn_scan"):
            self.btn_scan.config(state=state)
        if hasattr(self, "btn_rename"):
            self.btn_rename.config(state=state)
        if hasattr(self, "btn_convert"):
            self.btn_convert.config(state=state)
        if hasattr(self, "btn_delete"):
            self.btn_delete.config(state=state)

    def start_clean_scan(self):
        """逻辑：扫描清理"""
        path = self.clean_path_var.get()
        if not path:
            return messagebox.showerror("提示", "请选择目标文件夹")

        for item in self.tree_clean.get_children():
            self.tree_clean.delete(item)

        self.toggle_ui(False)
        threading.Thread(
            target=self._clean_scan_thread, args=(path,), daemon=True
        ).start()

    def _clean_scan_thread(self, path: Path):
        try:
            self.update_status("正在扫描...", indeterminate=True)
            root_path = Path(path)
            count_ad = 0
            count_junk = 0

            scanner = Scanner(
                root_path, enable_ad_detection=self.clean_ad_scan_var.get()
            ).run()

            for root, result in scanner:
                if result.ads:
                    for f in result.ads:
                        self.root.after(0, lambda f=f: self._add_tree_item("广告", f))
                        count_ad += 1

                if hasattr(result, "junk") and result.junk:
                    for f in result.junk:
                        self.root.after(0, lambda f=f: self._add_tree_item("杂项", f))
                        count_junk += 1

            msg = f"扫描完成: 发现 {count_ad} 个疑似广告图片, {count_junk} 个杂项。"
            self.update_status(msg, 100, indeterminate=False)

        except Exception as e:
            logger.error(e)
            self.update_status(f"错误: {e}")
        finally:
            self.toggle_ui(True)

    def _add_tree_item(self, type_str: str, f_path: Path):
        self.tree_clean.insert(
            "",
            "end",
            values=(
                type_str,
                f_path.name,
                f_path.suffix,
                f_path.parent,
                f_path,
            ),
        )

    def on_clean_list_dblclick(self, event):
        item = self.tree_clean.selection()
        if not item:
            return
        file_path = self.tree_clean.item(item[0], "values")[3]
        try:
            if os.name == "nt":
                os.startfile(file_path)
            else:
                subprocess.run(["xdg-open", file_path])
        except Exception as e:
            logger.error(f"无法打开预览: {e}")

    def clean_select_all(self):
        for item in self.tree_clean.get_children():
            self.tree_clean.selection_add(item)

    def clean_delete_selected(self):
        items = self.tree_clean.selection()
        if not items:
            return messagebox.showinfo("提示", "请先选择要删除的文件")

        if not messagebox.askyesno(
            "删除确认", f"确定要将选中的 {len(items)} 个文件移入回收站吗？"
        ):
            return

        count = 0
        for item in items:
            path = self.tree_clean.item(item, "values")[4]
            try:
                send2trash(path)
                self.tree_clean.delete(item)
                count += 1
            except Exception as e:
                logger.error(f"删除失败 {path}: {e}")
        self.update_status(f"已删除 {count} 个文件")

    def start_rename(self):
        """逻辑：重命名"""
        path = self.rename_path_var.get()
        if not path:
            return messagebox.showerror("提示", "请选择目标文件夹")
        if not messagebox.askyesno("确认", "确定要执行原地重命名吗？\n此操作不可逆！"):
            return

        self.toggle_ui(False)
        threading.Thread(target=self._rename_thread, args=(path,), daemon=True).start()

    def _rename_thread(self, path: Path):
        try:
            self.update_status("正在重命名...", indeterminate=True)
            Renamer(Path(path), enable_ad_detection=False).run()
            self.update_status("✅ 重命名完成", 100, indeterminate=False)
            messagebox.showinfo("成功", "重命名完成")
        except Exception as e:
            logger.error(e)
            messagebox.showerror("错误", str(e))
        finally:
            self.toggle_ui(True)

    def start_convert(self):
        """逻辑：格式转换"""
        inp, out = self.input_path_var.get(), self.output_path_var.get()
        if not inp or not out:
            return messagebox.showerror("提示", "请设置输入输出路径")

        self.toggle_ui(False)
        threading.Thread(
            target=self._convert_thread, args=(inp, out), daemon=True
        ).start()

    def _convert_thread(self, inp: str | Path, out: str | Path):
        try:
            inp_path, out_path = Path(inp), Path(out)

            self.update_status("正在预估任务量...", indeterminate=True)
            total = sum(
                [
                    len([f for f in files if not f.startswith(".")])
                    for _, _, files in os.walk(inp_path)
                ]
            )
            if total == 0:
                self.toggle_ui(True)
                return messagebox.showinfo("提示", "目录为空")

            self.update_status("正在初始化...", indeterminate=False)
            converter = Converter(
                inp_path,
                out_path,
                self.format_var.get(),
                self.quality_var.get(),
                self.lossless_var.get(),
            )

            should_skip = self.conv_skip_ad_var.get()

            # 转换时的扫描逻辑
            def gen():
                scan_enable = should_skip
                scanner = Scanner(inp_path, enable_ad_detection=scan_enable)
                for root, res in scanner.run():
                    if not should_skip and res.ads:
                        res.to_convert.extend(res.ads)
                        res.ads.clear()
                    yield root, res

            def cb(done, name):
                pct = min(100, (done / total) * 100)
                self.update_status(f"处理中: {name}", pct)

            converter.run(gen(), progress_callback=cb)

            self.update_status("🎉 转换完成！", 100)
            messagebox.showinfo("成功", f"处理完成！\n输出: {out}")

        except Exception as e:
            logger.error(e)
            messagebox.showerror("错误", str(e))
        finally:
            self.toggle_ui(True)

    def start_dedupe_scan(self):
        raw_paths = self.dedupe_listbox.get(0, tk.END)

        if not raw_paths:
            return messagebox.showerror("提示", "请至少添加一个目标文件夹！")

        valid_paths = []
        for p in raw_paths:
            path_obj = Path(p)
            if path_obj.exists():
                valid_paths.append(path_obj)
            else:
                logger.warning(f"跳过不存在的路径: {p}")

        if not valid_paths:
            return messagebox.showerror("错误", "列表中的路径均无效或不存在")

        try:
            DedupeWindow(self.root, valid_paths)
        except Exception as e:
            logger.error(f"无法启动查重窗口: {e}")
            messagebox.showerror("错误", f"启动失败: {e}")
