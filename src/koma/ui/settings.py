import tkinter as tk
from tkinter import messagebox, ttk

from koma.config import OUTPUT_FORMATS, _cfg, save_config


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("全局设置")
        self.geometry("600x700")
        self.parent = parent

        self.transient(parent)
        self.grab_set()

        main_frame = ttk.Frame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(side="top", fill="both", expand=True)

        self.init_app_tab()
        self.init_scanner_tab()
        self.init_converter_tab()
        self.init_extensions_tab()

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(side="bottom", fill="x", pady=(10, 0))

        ttk.Button(btn_frame, text="保存并关闭", command=self.save).pack(
            side="right", padx=5
        )
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(
            side="right", padx=5
        )

        self.center_window()

    def center_window(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"+{x}+{y}")

    def init_app_tab(self):
        frame = ttk.Frame(self.notebook, padding=15)
        self.notebook.add(frame, text=" 常规 ")

        grp = ttk.LabelFrame(frame, text="文件列表", padding=10)
        grp.pack(fill="x", pady=5)

        ttk.Label(grp, text="字体名称:").grid(row=0, column=0, sticky="w", pady=5)
        self.font_var = tk.StringVar(value=_cfg.app.font)
        ttk.Entry(grp, textvariable=self.font_var, width=30).grid(
            row=0, column=1, sticky="w", padx=10
        )

        ttk.Label(grp, text="字体大小:").grid(row=1, column=0, sticky="w", pady=5)
        self.font_size_var = tk.IntVar(value=_cfg.app.font_size)
        ttk.Spinbox(
            grp, from_=8, to=30, textvariable=self.font_size_var, width=10
        ).grid(row=1, column=1, sticky="w", padx=10)

    def init_converter_tab(self):
        frame = ttk.Frame(self.notebook, padding=15)
        self.notebook.add(frame, text=" 格式转换 ")

        grp = ttk.LabelFrame(frame, text="默认转换参数", padding=10)
        grp.pack(fill="x", pady=5)

        ttk.Label(grp, text="并发线程:").grid(row=0, column=0, sticky="w", pady=5)
        self.workers_var = tk.IntVar(value=_cfg.converter.max_workers)
        f_work = ttk.Frame(grp)
        f_work.grid(row=0, column=1, sticky="w", padx=10)
        ttk.Spinbox(
            f_work, from_=0, to=64, textvariable=self.workers_var, width=10
        ).pack(side="left")
        ttk.Label(f_work, text="(0 = 自动)").pack(side="left", padx=5)

        ttk.Label(grp, text="默认格式:").grid(row=1, column=0, sticky="w", pady=5)
        self.format_var = tk.StringVar(value=_cfg.converter.format)
        ttk.Combobox(
            grp, textvariable=self.format_var, values=OUTPUT_FORMATS, state="readonly"
        ).grid(row=1, column=1, sticky="ew", padx=10)

        ttk.Label(grp, text="默认质量:").grid(row=2, column=0, sticky="w", pady=5)
        self.quality_var = tk.IntVar(value=_cfg.converter.quality)
        q_frame = ttk.Frame(grp)
        q_frame.grid(row=2, column=1, sticky="ew", padx=10)
        scale = ttk.Scale(
            q_frame, from_=1, to=100, variable=self.quality_var, orient="horizontal"
        )
        scale.pack(side="left", fill="x", expand=True)
        lbl_q = ttk.Label(q_frame, text=str(self.quality_var.get()), width=4)
        lbl_q.pack(side="right", padx=(5, 0))
        scale.configure(command=lambda v: lbl_q.configure(text=str(int(float(v)))))

        self.lossless_var = tk.BooleanVar(value=_cfg.converter.lossless)
        ttk.Checkbutton(grp, text="默认开启无损模式", variable=self.lossless_var).grid(
            row=3, column=1, sticky="w", padx=10, pady=5
        )

    def init_extensions_tab(self):
        tab_frame = ttk.Frame(self.notebook)
        self.notebook.add(tab_frame, text=" 过滤规则 ")
        canvas = tk.Canvas(tab_frame)
        scrollbar = ttk.Scrollbar(tab_frame, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas, padding=15)
        scroll_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def create_list_editor(parent, title, data_set, height=4):
            frame = ttk.LabelFrame(parent, text=title, padding=5)
            frame.pack(fill="x", pady=5)
            txt = tk.Text(frame, height=height, font=("Consolas", 9))
            txt.pack(fill="x", padx=5, pady=5)

            content = ", ".join(sorted(data_set))
            txt.insert("1.0", content)
            return txt

        ttk.Label(
            scroll_frame,
            text="提示：使用英文逗号（,）分隔，修改后需重启生效",
            foreground="gray",
        ).pack(anchor="w", pady=(0, 10))

        self.txt_convert = create_list_editor(
            scroll_frame,
            "需要转换的图片格式",
            _cfg.extensions.convert,
        )
        self.txt_passthrough = create_list_editor(
            scroll_frame,
            "转换时直接复制的图片格式",
            _cfg.extensions.passthrough,
        )
        self.txt_archive = create_list_editor(
            scroll_frame,
            "压缩包/归档格式",
            _cfg.extensions.archive,
        )
        self.txt_document = create_list_editor(
            scroll_frame,
            "文档/电子书格式",
            _cfg.extensions.document,
        )
        self.txt_misc = create_list_editor(
            scroll_frame,
            "杂项文件白名单",
            _cfg.extensions.misc_whitelist,
        )
        self.txt_junk = create_list_editor(
            scroll_frame,
            "系统垃圾文件",
            _cfg.extensions.system_junk,
        )

    def init_scanner_tab(self):
        frame = ttk.Frame(self.notebook, padding=15)
        self.notebook.add(frame, text=" 扫描清理 ")

        self.ad_scan_var = tk.BooleanVar(value=_cfg.scanner.enable_ad_scan)
        ttk.Checkbutton(
            frame, text="启用广告二维码检测", variable=self.ad_scan_var
        ).pack(anchor="w", pady=10)

        # 二维码白名单
        ttk.Label(
            frame, text="二维码域名白名单 (包含这些域名的二维码不会被视为广告)"
        ).pack(anchor="w", pady=(10, 5))

        self.txt_qr = tk.Text(frame, height=10, font=("Consolas", 9))
        self.txt_qr.pack(fill="both", expand=True)
        self.txt_qr.insert("1.0", "\n".join(_cfg.scanner.qr_whitelist))
        ttk.Label(frame, text="每行一个域名", foreground="gray").pack(anchor="w")

    def save(self):
        try:
            _cfg.app.font = self.font_var.get().strip()
            _cfg.app.font_size = self.font_size_var.get()

            _cfg.converter.format = self.format_var.get()
            _cfg.converter.quality = self.quality_var.get()
            _cfg.converter.max_workers = self.workers_var.get()
            _cfg.converter.lossless = self.lossless_var.get()

            def parse_set(text_widget):
                raw = text_widget.get("1.0", "end-1c")
                clean_text = raw.replace("\n", ",")
                return {x.strip().lower() for x in clean_text.split(",") if x.strip()}

            _cfg.extensions.convert = parse_set(self.txt_convert)
            _cfg.extensions.passthrough = parse_set(self.txt_passthrough)
            _cfg.extensions.archive = parse_set(self.txt_archive)
            _cfg.extensions.document = parse_set(self.txt_document)
            _cfg.extensions.misc_whitelist = parse_set(self.txt_misc)
            _cfg.extensions.system_junk = parse_set(self.txt_junk)

            _cfg.scanner.enable_ad_scan = self.ad_scan_var.get()
            qr_raw = self.txt_qr.get("1.0", "end-1c")
            _cfg.scanner.qr_whitelist = [
                line.strip() for line in qr_raw.split("\n") if line.strip()
            ]

            save_config(_cfg)

            messagebox.showinfo(
                "保存成功",
                "配置已更新！\n部分设置（如字体、扩展名）可能需要重启程序才能完全生效。",
            )
            self.destroy()

        except Exception as e:
            messagebox.showerror("保存失败", f"无法保存配置:\n{str(e)}")
            import traceback

            traceback.print_exc()
