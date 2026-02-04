import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from koma.config import OUTPUT_FORMATS
from koma.core.converter import Converter
from koma.core.scanner import Scanner
from koma.ui.base_tab import BaseTab
from koma.utils import logger


class ConvertTab(BaseTab):
    def __init__(self, parent, config, processor, status_callback):
        super().__init__(parent, config, processor, status_callback)

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.format_var = tk.StringVar(value=self.config.converter.format)
        self.quality_var = tk.IntVar(value=self.config.converter.quality)
        self.lossless_var = tk.BooleanVar(value=self.config.converter.lossless)
        self.skip_ad_var = tk.BooleanVar(value=self.config.scanner.enable_ad_scan)

        self.input_var.trace_add("write", self._on_input_change)

        self._setup_ui()

    def _setup_ui(self):
        desc = "将文件夹内图片批量转换格式，并保持原有目录结构。"
        ttk.Label(self, text=desc, foreground="#666").pack(anchor="w", padx=10, pady=15)

        grp_path = ttk.LabelFrame(self, text="路径设置", padding=10)
        grp_path.pack(fill="x", padx=10, pady=5)
        grp_path.columnconfigure(1, weight=1)

        ttk.Label(grp_path, text="输入:").grid(row=0, column=0, sticky="w")
        e_in = ttk.Entry(grp_path, textvariable=self.input_var)
        e_in.grid(row=0, column=1, sticky="ew", padx=5)
        self._setup_dnd(e_in, self.input_var)
        ttk.Button(
            grp_path,
            text="...",
            width=4,
            command=lambda: self.select_dir(self.input_var),
        ).grid(row=0, column=2)

        ttk.Label(grp_path, text="输出:").grid(row=1, column=0, sticky="w", pady=5)
        e_out = ttk.Entry(grp_path, textvariable=self.output_var)
        e_out.grid(row=1, column=1, sticky="ew", padx=5)
        self._setup_dnd(e_out, self.output_var)
        ttk.Button(
            grp_path,
            text="...",
            width=4,
            command=lambda: self.select_dir(self.output_var),
        ).grid(row=1, column=2)

        ttk.Checkbutton(grp_path, text="跳过广告图片", variable=self.skip_ad_var).grid(
            row=2, column=1, sticky="w"
        )

        grp_param = ttk.LabelFrame(self, text="转换参数", padding=10)
        grp_param.pack(fill="x", padx=10, pady=5)

        f_row = ttk.Frame(grp_param)
        f_row.pack(fill="x", pady=2)
        ttk.Label(f_row, text="格式:").pack(side="left")
        ttk.Combobox(
            f_row,
            textvariable=self.format_var,
            values=OUTPUT_FORMATS,
            width=10,
            state="readonly",
        ).pack(side="left", padx=5)

        q_row = ttk.Frame(grp_param)
        q_row.pack(fill="x", pady=5)
        ttk.Label(q_row, text="质量:").pack(side="left")
        self.scale = ttk.Scale(
            q_row, from_=1, to=100, variable=self.quality_var, orient="horizontal"
        )
        self.scale.pack(side="left", fill="x", expand=True, padx=5)
        self.lbl_q = ttk.Label(q_row, textvariable=self.quality_var, width=3)
        self.lbl_q.pack(side="left")

        self.chk_lossless = ttk.Checkbutton(
            grp_param,
            text="无损模式 (Lossless)",
            variable=self.lossless_var,
            command=self._toggle_quality,
        )
        self.chk_lossless.pack(anchor="w", pady=2)

        self.btn_run = ttk.Button(self, text="🔁 开始转换", command=self._start)
        self.btn_run.pack(fill="x", padx=20, pady=20, ipady=5)

        self._toggle_quality()

    def _on_input_change(self, *args):
        val = self.input_var.get()
        if not val:
            return

        try:
            p = Path(val)
            if p.exists():
                suggested = p.parent / f"{p.name}_output"
                self.output_var.set(str(suggested))
        except Exception:
            pass

    def _toggle_quality(self):
        state = "disabled" if self.lossless_var.get() else "normal"
        self.scale.config(state=state)
        self.lbl_q.config(state=state)

    def _start(self):
        inp, out = self.input_var.get(), self.output_var.get()
        if not inp or not out:
            return messagebox.showerror("错误", "请设置路径")

        # 临时更新配置对象
        self.config.converter.format = self.format_var.get()
        self.config.converter.quality = self.quality_var.get()
        self.config.converter.lossless = self.lossless_var.get()

        self.btn_run.config(state="disabled")
        threading.Thread(target=self._run_thread, args=(inp, out), daemon=True).start()

    def _run_thread(self, inp, out):
        try:
            self.update_status("正在扫描...", indeterminate=True)

            converter = Converter(
                Path(inp), Path(out), self.config.converter, self.image_processor
            )

            def gen():
                self.config.scanner.enable_ad_scan = self.skip_ad_var.get()
                scanner = Scanner(
                    Path(inp), self.config.extensions, self.image_processor
                )
                for root, res in scanner.run():
                    # 如果不跳过广告，则把广告当作普通图片处理
                    if not self.skip_ad_var.get() and res.ads:
                        res.to_convert.extend(res.ads)
                        res.ads.clear()
                    yield root, res

            def cb(curr, total, msg):
                pct = (curr / total * 100) if total else 0
                self.after(0, lambda: self.update_status(msg, pct, False))

            converter.run(gen(), progress_callback=cb)

            self.after(0, lambda: self.update_status("转换完成", 100, False))
            messagebox.showinfo("完成", f"转换完成！\n输出目录: {out}")
        except Exception as e:
            logger.error(f"转换失败: {e}", exc_info=True)
            self.after(0, lambda: self.update_status("转换失败", 0, False))
            messagebox.showerror("错误", str(e))
        finally:
            self.after(0, lambda: self.btn_run.config(state="normal"))
