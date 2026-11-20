import logging
import sys
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import scrolledtext, ttk

from PIL import Image, ImageTk

import koma
from koma.config import ConfigManager
from koma.core.image_processor import ImageProcessor
from koma.ui.binder_tab import BinderTab
from koma.ui.convert_tab import ConvertTab
from koma.ui.dedupe_tab import DedupeTab
from koma.ui.rename_tab import RenameTab
from koma.ui.scan_tab import SacnTab
from koma.ui.settings import SettingsDialog
from koma.ui.utils import TextHandler, get_monospace_font, get_sans_font
from koma.utils import get_default_formatter, logger, setup_file_logging


class KomaGUI:
    def __init__(self, root):
        self.cfg_manager = ConfigManager()
        config = self.cfg_manager.load()

        self.root = root
        self.root.title(f"KOMA - 漫画工具箱 v{koma.__version__}")
        self.root.geometry(f"{config.app.width}x{config.app.height}")

        config.app.font = get_sans_font(config.app.font)
        config.app.monospace_font = get_monospace_font(config.app.monospace_font)
        self.config = config
        self.image_processor = ImageProcessor(self.config.scanner)

        self.progress_var = tk.DoubleVar(value=0)
        self.status_var = tk.StringVar(value="就绪")

        self._setup_icon()
        self._setup_ui()
        self._setup_global_font()
        self._setup_logging_redirect()

    def _setup_icon(self):
        """加载应用程序图标"""
        try:
            if getattr(sys, "frozen", False):
                base_path = Path(sys._MEIPASS) / "koma"  # type: ignore
            else:
                base_path = Path(__file__).parent.parent

            icon_path = Path(base_path) / "resources" / "koma.ico"
            if icon_path.exists():
                with Image.open(icon_path) as img:
                    icon = ImageTk.PhotoImage(img)
                self.root.iconphoto(True, icon)

        except Exception as e:
            logger.error(f"加载图标失败: {e}")

    def _setup_ui(self):
        status_bar = ttk.Frame(self.root, padding=(10, 5))
        status_bar.pack(side="bottom", fill="x")

        self.lbl_status = ttk.Label(
            status_bar, textvariable=self.status_var, font=("TkDefaultFont", 9)
        )
        self.lbl_status.pack(side="top", anchor="w", padx=2, pady=(0, 2))

        self.progress = ttk.Progressbar(
            status_bar, variable=self.progress_var, maximum=100
        )
        self.progress.pack(side="top", fill="x")

        paned = ttk.PanedWindow(self.root, orient="vertical")
        paned.pack(fill="both", expand=True)

        main_frame = ttk.Frame(paned)
        paned.add(main_frame, weight=4)

        top_bar = ttk.Frame(main_frame)
        top_bar.pack(fill="x", padx=10, pady=5)
        ttk.Button(top_bar, text="⚙️ 全局设置", command=self._open_settings).pack(
            side="right"
        )

        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=5)

        tabs = [
            (SacnTab, " 🧹 扫描清理 "),
            (RenameTab, " ⚒️ 重命名 "),
            (ConvertTab, " 🎨 格式转换 "),
            (DedupeTab, " 📚 归档查重 "),
            (BinderTab, " 📖 合集装订 "),
        ]

        for tab_class, label in tabs:
            tab_instance = tab_class(
                self.notebook, self.config, self.image_processor, self.update_status
            )
            self.notebook.add(tab_instance, text=label)

        log_frame = ttk.LabelFrame(paned, text="运行日志", padding=5)
        paned.add(log_frame, weight=1)

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=8,
            state="disabled",
            font=(self.config.app.monospace_font, self.config.app.font_size),
        )
        self.log_text.pack(fill="both", expand=True)

    def _setup_global_font(self):
        default_font = tkfont.nametofont("TkDefaultFont")
        default_font.configure(
            family=self.config.app.font, size=self.config.app.font_size
        )

        tkfont.nametofont("TkTextFont").configure(
            family=self.config.app.font, size=self.config.app.font_size
        )
        tkfont.nametofont("TkMenuFont").configure(
            family=self.config.app.font, size=self.config.app.font_size
        )
        tkfont.nametofont("TkHeadingFont").configure(
            family=self.config.app.font, size=self.config.app.font_size
        )
        tkfont.nametofont("TkFixedFont").configure(
            family=self.config.app.monospace_font, size=self.config.app.font_size
        )

        style = ttk.Style()
        style.configure(".", font=(self.config.app.font, self.config.app.font_size))

    def _setup_logging_redirect(self):
        """将标准 logging 输出同时送到 UI 文本框、控制台与日志文件"""
        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        root_logger.setLevel(logging.INFO)

        formatter = get_default_formatter()

        ui_handler = TextHandler(self.log_text)
        ui_handler.setFormatter(formatter)
        root_logger.addHandler(ui_handler)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        # 落盘：打包版 console=False，没有文件日志的话窗口一关就无从排查
        if self.config.app.enable_file_log:
            log_path = setup_file_logging(self.config.config_dir)
            if log_path:
                logger.info(f"📝 运行日志: {log_path}")
        else:
            logger.info("📝 本地日志文件已关闭（设置 → 常规 可开启）")

    def _open_settings(self):
        """打开全局设置对话框"""
        SettingsDialog(self.root, self.config, self.cfg_manager)

    def update_status(
        self, text: str, value: float | None = None, indeterminate: bool | None = None
    ):
        """
        供各子 Tab 调用的统一状态更新入口

        Args:
            text: 状态栏显示的文字
            value: 进度百分比 (0-100)
            indeterminate: 是否开启/关闭进度条流光动画
        """
        if text:
            self.status_var.set(text)

        if value is not None:
            self.progress_var.set(value)
            self.progress["value"] = value

        if indeterminate is not None:
            if indeterminate:
                self.progress.config(mode="indeterminate")
                self.progress.start(10)
            else:
                self.progress.stop()
                self.progress.config(mode="determinate")
