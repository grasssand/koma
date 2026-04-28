import sys
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

import koma
from koma.config import IMG_OUTPUT_FORMATS, ConfigManager, GlobalConfig
from koma.utils import logger


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, config: GlobalConfig, manager: ConfigManager):
        super().__init__(parent)
        self.title("全局设置")
        self.geometry("600x720")

        self.transient(parent)
        self.grab_set()

        self.config = config
        self.manager = manager

        ## UI 变量
        self.win_height_var = tk.IntVar()
        self.win_width_var = tk.IntVar()
        self.font_var = tk.StringVar()
        self.mono_font_var = tk.StringVar()
        self.font_size_var = tk.IntVar()
        self.list_font_size_var = tk.IntVar()

        self.worker_var = tk.IntVar()
        self.format_var = tk.StringVar()
        self.quality_var = tk.IntVar()
        self.lossless_var = tk.BooleanVar()
        self.ad_scan_var = tk.BooleanVar()
        self.editors = {}

        self._setup_ui()
        self._load_values()

        self._center_window()

    def _center_window(self):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"+{x}+{y}")

    def _setup_ui(self):
        # 底部按钮区
        btn_frame = ttk.Frame(self, padding=(10, 10))
        btn_frame.pack(side="bottom", fill="x")

        ttk.Button(btn_frame, text="💾 保存并关闭", command=self._save).pack(
            side="right"
        )
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(
            side="right", padx=5
        )

        # 主布局
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill="both", expand=True)

        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill="both", expand=True)

        self.tab_app = ttk.Frame(notebook, padding=10)
        self.tab_scan = ttk.Frame(notebook, padding=10)
        self.tab_conv = ttk.Frame(notebook, padding=10)
        self.tab_dedupe = ttk.Frame(notebook, padding=10)
        self.tab_ext = ttk.Frame(notebook, padding=10)
        self.tab_about = ttk.Frame(notebook, padding=10)

        notebook.add(self.tab_app, text=" 常规 ")
        notebook.add(self.tab_scan, text=" 扫描清理 ")
        notebook.add(self.tab_conv, text=" 格式转换 ")
        notebook.add(self.tab_dedupe, text=" 归档查重 ")
        notebook.add(self.tab_ext, text=" 过滤规则 ")
        notebook.add(self.tab_about, text=" 关于 ")

        self._init_app_tab()
        self._init_scan_tab()
        self._init_conv_tab()
        self._init_dedupe_tab()
        self._init_ext_tab()
        self._init_about_tab()

    def _init_app_tab(self):
        """常规设置"""
        families = sorted(tkfont.families())

        grp_win = ttk.LabelFrame(self.tab_app, text="启动设置", padding=10)
        grp_win.pack(fill="x", pady=(0, 10))

        f_win = ttk.Frame(grp_win)
        f_win.pack(fill="x", pady=5)

        ttk.Label(f_win, text="窗口大小（宽 x 高）:").pack(side="left")
        ttk.Entry(f_win, textvariable=self.win_width_var, width=6).pack(
            side="left", padx=(10, 5)
        )
        ttk.Label(f_win, text="x").pack(side="left")
        ttk.Entry(f_win, textvariable=self.win_height_var, width=6).pack(
            side="left", padx=5
        )

        grp_font = ttk.LabelFrame(self.tab_app, text="字体与外观", padding=10)
        grp_font.pack(fill="x")

        f1 = ttk.Frame(grp_font)
        f1.pack(fill="x", pady=5)
        ttk.Label(f1, text="界面字体:", width=10).pack(side="left")
        ttk.Combobox(
            f1, textvariable=self.font_var, values=families, state="readonly", height=20
        ).pack(side="left", padx=5, fill="x", expand=True)

        f2 = ttk.Frame(grp_font)
        f2.pack(fill="x", pady=5)
        ttk.Label(f2, text="日志字体:", width=10).pack(side="left")
        ttk.Combobox(
            f2,
            textvariable=self.mono_font_var,
            values=families,
            state="readonly",
            height=20,
        ).pack(side="left", padx=5, fill="x", expand=True)

        f3 = ttk.Frame(grp_font)
        f3.pack(fill="x", pady=5)

        ttk.Label(f3, text="界面字号:").pack(side="left")
        ttk.Spinbox(f3, from_=8, to=24, textvariable=self.font_size_var, width=5).pack(
            side="left", padx=(5, 15)
        )

        ttk.Label(f3, text="列表字号:").pack(side="left")
        ttk.Spinbox(
            f3, from_=8, to=30, textvariable=self.list_font_size_var, width=5
        ).pack(side="left", padx=5)

    def _init_scan_tab(self):
        """扫描清理设置"""
        grp_ad = ttk.LabelFrame(self.tab_scan, text="广告检测", padding=10)
        grp_ad.pack(fill="both", expand=True)

        ttk.Checkbutton(
            grp_ad, text="默认开启广告二维码检测", variable=self.ad_scan_var
        ).pack(anchor="w")

        ttk.Separator(grp_ad, orient="horizontal").pack(fill="x", pady=10)

        header = ttk.Frame(grp_ad)
        header.pack(fill="x")
        ttk.Label(
            header, text="二维码白名单 (包含这些域名的二维码不会被视为广告):"
        ).pack(side="left")
        ttk.Button(
            header, text="🔄 重置", command=lambda: self._reset_section("scanner")
        ).pack(side="right")

        self.editors["qr"] = self._create_text_group(
            grp_ad, "白名单域名列表（一行一个）", lines=30
        )

    def _init_conv_tab(self):
        """格式转换设置"""
        grp = ttk.LabelFrame(self.tab_conv, text="转换器默认参数", padding=10)
        grp.pack(fill="x")

        f1 = ttk.Frame(grp)
        f1.pack(fill="x", pady=5)
        ttk.Label(f1, text="最大线程数:").pack(side="left")
        ttk.Entry(f1, textvariable=self.worker_var, width=8).pack(side="left", padx=5)
        ttk.Label(f1, text="(0 = 自动)", foreground="gray").pack(side="left")

        f2 = ttk.Frame(grp)
        f2.pack(fill="x", pady=5)
        ttk.Label(f2, text="默认格式:").pack(side="left")
        ttk.Combobox(
            f2,
            textvariable=self.format_var,
            values=IMG_OUTPUT_FORMATS,
            state="readonly",
            width=15,
        ).pack(side="left", padx=5)

        f3 = ttk.Frame(grp)
        f3.pack(fill="x", pady=5)
        ttk.Label(f3, text="默认质量:").pack(side="left")
        ttk.Scale(
            f3, from_=1, to=100, variable=self.quality_var, orient="horizontal"
        ).pack(side="left", fill="x", expand=True, padx=5)
        ttk.Label(f3, textvariable=self.quality_var, width=3).pack(side="left")

        ttk.Checkbutton(grp, text="默认启用无损模式", variable=self.lossless_var).pack(
            anchor="w", pady=5
        )

    def _init_dedupe_tab(self):
        """归档查重设置"""
        top_frame = ttk.Frame(self.tab_dedupe)
        top_frame.pack(fill="x", pady=(0, 10))

        ttk.Button(
            top_frame,
            text="🔄 重置",
            command=lambda: self._reset_section("deduplicator"),
        ).pack(side="right")

        grp_regex = ttk.LabelFrame(
            self.tab_dedupe, text="文件夹解析正则 (Python Regex)", padding=10
        )
        grp_regex.pack(fill="both", expand=True)

        info_text = (
            "必须包含以下命名分组 (Named Groups)：\n"
            "  - (?P<artist>...) : 作者/社团 [必须]\n"
            "  - (?P<title>...)  : 作品标题 [必须]\n"
            "  - (?P<series>...) : 系列 [可选]\n\n"
            "示例: (C99) [社团 (作者)] 标题 (Vol.1) [中国翻訳] [DL版]"
        )
        ttk.Label(grp_regex, text=info_text, justify="left", foreground="#444").pack(
            anchor="w", pady=(0, 10)
        )

        self.editors["regex"] = tk.Text(grp_regex, height=4, wrap="char")
        scr = ttk.Scrollbar(grp_regex, command=self.editors["regex"].yview)
        self.editors["regex"].configure(yscrollcommand=scr.set)

        self.editors["regex"].pack(side="left", fill="both", expand=True)
        scr.pack(side="right", fill="y")

    def _init_ext_tab(self):
        """过滤规则设置"""
        top_frame = ttk.Frame(self.tab_ext)
        top_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(
            top_frame,
            text="提示: 扩展名请用空格或换行分隔，例如: .jpg .png",
            foreground="gray",
        ).pack(side="left")
        ttk.Button(
            top_frame,
            text="🔄 重置",
            command=lambda: self._reset_section("extensions"),
        ).pack(side="right")

        self.editors["convert"] = self._create_text_group(
            self.tab_ext, "需要转换的图片格式", lines=4
        )
        self.editors["passthrough"] = self._create_text_group(
            self.tab_ext, "直接复制的图片格式", lines=4
        )
        self.editors["archive"] = self._create_text_group(
            self.tab_ext, "归档文件格式", lines=4
        )
        self.editors["document"] = self._create_text_group(
            self.tab_ext, "文档格式", lines=4
        )
        self.editors["misc_whitelist"] = self._create_text_group(
            self.tab_ext, "杂项文件白名单", lines=4
        )
        self.editors["system_junk"] = self._create_text_group(
            self.tab_ext, "系统垃圾文件", lines=4
        )

    def _init_about_tab(self):
        """关于页面"""
        container = ttk.Frame(self.tab_about)
        container.pack(expand=True, fill="both", padx=20, pady=20)

        if getattr(sys, "frozen", False):
            base_path = Path(sys._MEIPASS) / "koma"  # type: ignore
        else:
            base_path = Path(__file__).parent.parent
        icon_path = base_path / "resources" / "koma.ico"

        self.about_icon = None
        try:
            if icon_path.exists():
                pil_img = Image.open(icon_path)
                pil_img = pil_img.resize((72, 72), Image.Resampling.LANCZOS)
                self.about_icon = ImageTk.PhotoImage(pil_img)
        except Exception:
            pass

        if self.about_icon:
            lbl_icon = ttk.Label(container, image=self.about_icon)
            lbl_icon.pack(pady=(20, 10))
        else:
            ttk.Frame(container, height=20).pack()

        lbl_title = ttk.Label(
            container, text="Koma - 漫画工具箱", font=(self.config.app.font, 18, "bold")
        )
        lbl_title.pack(pady=(30, 5))

        lbl_version = ttk.Label(
            container, text=f"版本: v{koma.__version__}", foreground="gray"
        )
        lbl_version.pack(pady=(0, 20))

        desc = (
            "一个多功能的本地漫画整理工具。\n\n"
            "支持自动化格式转换、广告清理、文件重命名、归档查重。"
        )
        lbl_desc = ttk.Label(
            container,
            text=desc,
            justify="center",
            font=(self.config.app.font, self.config.app.font_size),
        )
        lbl_desc.pack(pady=10)

        f_links = ttk.Frame(container)
        f_links.pack(pady=15)

        lbl_release = ttk.Label(
            f_links, text="⭐ 获取最新版本", foreground="#0066cc", cursor="hand2"
        )
        lbl_release.pack(side="left")
        lbl_release.bind(
            "<Button-1>",
            lambda e: webbrowser.open("https://github.com/grasssand/koma/releases"),
        )

        ttk.Label(f_links, text="  /  ", foreground="gray").pack(side="left")

        lbl_issue = ttk.Label(
            f_links, text="提交 Issue 🐞", foreground="#0066cc", cursor="hand2"
        )
        lbl_issue.pack(side="left")
        lbl_issue.bind(
            "<Button-1>",
            lambda e: webbrowser.open("https://github.com/grasssand/koma/issues"),
        )

        lbl_disclaimer = ttk.Label(
            container,
            text="免责声明：\n本软件仅供学习交流使用。查重与广告清理算法可能存在误判，\n在执行删除操作前，请务必仔细核对文件。",
            justify="center",
            foreground="#888",
        )
        lbl_disclaimer.pack(side="bottom", pady=20)

    def _create_text_group(self, parent, title, lines=4):
        """创建一个带标签和滚动条的文本编辑框"""
        grp = ttk.LabelFrame(parent, text=title, padding=5)
        grp.pack(fill="x", pady=5)

        txt = tk.Text(grp, height=lines, wrap="word")
        scr = ttk.Scrollbar(grp, command=txt.yview)
        txt.configure(yscrollcommand=scr.set)

        txt.pack(side="left", fill="x", expand=True)
        scr.pack(side="right", fill="y")
        return txt

    def _load_values(self):
        """将 self.config 的值填入 UI"""
        # App Settings (Updated)
        self.win_height_var.set(getattr(self.config.app, "height", 800))
        self.win_width_var.set(getattr(self.config.app, "width", 900))
        self.font_var.set(self.config.app.font)
        self.mono_font_var.set(getattr(self.config.app, "monospace_font", "Consolas"))
        self.font_size_var.set(self.config.app.font_size)
        self.list_font_size_var.set(getattr(self.config.app, "list_font_size", 10))

        # Converter
        self.worker_var.set(self.config.converter.max_workers)
        self.format_var.set(self.config.converter.format)
        self.quality_var.set(self.config.converter.quality)
        self.lossless_var.set(self.config.converter.lossless)

        # Deduplicator
        self.editors["regex"].delete("1.0", tk.END)
        self.editors["regex"].insert("1.0", self.config.deduplicator.comic_dir_regex)

        # Extensions
        self._set_text(self.editors["convert"], self.config.extensions.convert)
        self._set_text(self.editors["passthrough"], self.config.extensions.passthrough)
        self._set_text(self.editors["archive"], self.config.extensions.archive)
        self._set_text(self.editors["document"], self.config.extensions.document)
        self._set_text(
            self.editors["misc_whitelist"], self.config.extensions.misc_whitelist
        )
        self._set_text(self.editors["system_junk"], self.config.extensions.system_junk)

        # Scanner
        self.ad_scan_var.set(self.config.scanner.enable_ad_scan)
        self._set_text(self.editors["qr"], self.config.scanner.qr_whitelist, True)

    def _set_text(
        self, editor: tk.Text, data_set: list[str] | set[str], line_break: bool = False
    ):
        """将集合/列表填入文本框"""
        editor.delete("1.0", tk.END)
        separator = "\n" if line_break else " "
        text = separator.join(data_set)
        editor.insert("1.0", text)

    def _get_set_from_text(self, editor: tk.Text) -> set[str]:
        """从文本框解析出集合"""
        content = editor.get("1.0", tk.END).strip()
        if not content:
            return set()
        # 支持逗号、空格、换行符分隔
        content = content.replace("\n", " ").replace(",", " ")
        items = [x.strip() for x in content.split() if x.strip()]
        return set(items)

    def _get_list_from_text(self, editor: tk.Text) -> list[str]:
        """辅助：从文本框解析出列表"""
        return sorted(set(self._get_set_from_text(editor)))

    def _reset_section(self, section_name: str):
        """重置某个配置段到默认值"""
        if not messagebox.askyesno(
            "确认重置", f"确定要将 [{section_name}] 恢复为默认设置吗？"
        ):
            return

        try:
            # 获取默认配置对象
            defaults = self.manager.get_default_section(section_name)

            # 刷新 UI
            if section_name == "extensions":
                self._set_text(self.editors["convert"], defaults.convert)
                self._set_text(self.editors["passthrough"], defaults.passthrough)
                self._set_text(self.editors["archive"], defaults.archive)
                self._set_text(self.editors["document"], defaults.document)
                self._set_text(self.editors["misc_whitelist"], defaults.misc_whitelist)
                self._set_text(self.editors["system_junk"], defaults.system_junk)

            elif section_name == "deduplicator":
                self.editors["regex"].delete("1.0", tk.END)
                self.editors["regex"].insert("1.0", defaults.comic_dir_regex)

            elif section_name == "scanner":
                self.ad_scan_var.set(defaults.enable_ad_scan)
                self._set_text(self.editors["qr"], defaults.qr_whitelist, True)

            messagebox.showinfo("成功", "已恢复默认值，点击【保存】后生效。")

        except Exception as e:
            logger.error(f"重置失败: {e}")
            messagebox.showerror("错误", f"重置失败: {e}")

    def _save(self):
        """保存配置到磁盘"""
        try:
            # App
            try:
                w = int(self.win_width_var.get())
                h = int(self.win_height_var.get())
                if w < 100 or h < 100:
                    raise ValueError("窗口尺寸过小")

                self.config.app.width = w
                self.config.app.height = h
            except (ValueError, tk.TclError):
                messagebox.showwarning("输入错误", "窗口宽度和高度必须是有效的整数！")
                return

            self.config.app.font = self.font_var.get()
            self.config.app.monospace_font = self.mono_font_var.get()
            self.config.app.font_size = self.font_size_var.get()
            self.config.app.list_font_size = self.list_font_size_var.get()

            # Converter
            self.config.converter.max_workers = self.worker_var.get()
            self.config.converter.format = self.format_var.get()
            self.config.converter.quality = self.quality_var.get()
            self.config.converter.lossless = self.lossless_var.get()

            # Deduplicator
            regex_val = self.editors["regex"].get("1.0", "end-1c").strip()
            if regex_val:
                self.config.deduplicator.comic_dir_regex = regex_val

            # Extensions
            self.config.extensions.convert = self._get_set_from_text(
                self.editors["convert"]
            )
            self.config.extensions.passthrough = self._get_set_from_text(
                self.editors["passthrough"]
            )
            self.config.extensions.archive = self._get_set_from_text(
                self.editors["archive"]
            )
            self.config.extensions.document = self._get_set_from_text(
                self.editors["document"]
            )
            self.config.extensions.misc_whitelist = self._get_set_from_text(
                self.editors["misc_whitelist"]
            )
            self.config.extensions.system_junk = self._get_set_from_text(
                self.editors["system_junk"]
            )

            # Scanner
            self.config.scanner.enable_ad_scan = self.ad_scan_var.get()
            self.config.scanner.qr_whitelist = self._get_list_from_text(
                self.editors["qr"]
            )

            self.manager.save(self.config)
            messagebox.showinfo(
                "保存成功", "配置已保存！\n部分设置（如字体）可能需要重启软件才能生效。"
            )
            self.destroy()

        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            messagebox.showerror("保存失败", str(e))
