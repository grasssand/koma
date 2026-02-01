import datetime
import os
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from send2trash import send2trash

from koma.config import FONT_SIZE
from koma.core import Deduplicator
from koma.ui.utils import get_sans_font
from koma.utils import logger


class DedupeWindow(tk.Toplevel):
    def __init__(self, parent, input_paths: list[Path]):
        super().__init__(parent)
        self.title("📚 归档查重结果")
        self.geometry("900x600")

        self.input_paths = input_paths
        self.deduplicator = Deduplicator()
        self.results = {}

        self._setup_ui()
        self._start_scan()

    def _setup_ui(self):
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=5, pady=5)

        ttk.Button(toolbar, text="选择旧文件", command=self.select_older).pack(
            side="left", padx=5
        )
        ttk.Button(toolbar, text="反向选择", command=self.invert_selection).pack(
            side="left", padx=5
        )

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=5)

        self.btn_delete = ttk.Button(
            toolbar, text="删除选中到回收站", command=self.delete_selected
        )
        self.btn_delete.pack(side="left", padx=5)

        ttk.Label(toolbar, text="💡 双击打开文件位置", foreground="gray").pack(
            side="right", padx=10
        )

        # style = ttk.Style(self)
        # style.configure("Treeview", font=(get_sans_font(), FONT_SIZE))

        columns = ("check", "name", "mtime", "size", "path")
        self.tree = ttk.Treeview(
            self, columns=columns, show="headings", selectmode="browse"
        )

        self.tree.heading("check", text="选择")
        self.tree.heading("name", text="文件名")
        self.tree.heading("mtime", text="修改时间")
        self.tree.heading("size", text="大小")
        self.tree.heading("path", text="位置")

        self.tree.column("check", width=40, anchor="center", stretch=False)
        self.tree.column("name", width=400, anchor="w")
        self.tree.column("mtime", width=80, anchor="center")
        self.tree.column("size", width=40, anchor="e")
        self.tree.column("path", width=200, anchor="w")  # 隐藏列

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 单击：处理勾选逻辑
        self.tree.bind("<Button-1>", self.on_click)
        # 双击：打开文件所在文件夹
        self.tree.bind("<Double-1>", self.on_double_click)

        self.tree.tag_configure(
            "summary", background="#e8f4ff", font=(get_sans_font(), FONT_SIZE, "bold")
        )
        self.tree.tag_configure("file", font=(get_sans_font(), FONT_SIZE))

    def _start_scan(self):
        """执行扫描逻辑"""
        self.config(cursor="watch")
        self.update()

        try:
            self.results = self.deduplicator.scan(self.input_paths)
            self._populate_tree()

            count = len(self.results)
            if count == 0:
                messagebox.showinfo("扫描完成", "🎉 没有发现重复项！")
                self.destroy()
                return  # 退出函数
            else:
                self.title(f"📚 归档查重结果 - 发现 {count} 组重复")

        except Exception as e:
            messagebox.showerror("错误", f"扫描失败: {e}")
            self.destroy()
            return

        finally:
            try:
                if self.winfo_exists():
                    self.config(cursor="")
            except tk.TclError:
                pass

    def _populate_tree(self):
        """填充 Treeview"""
        for item in self.tree.get_children():
            self.tree.delete(item)

        for key, items in self.results.items():
            group_text = f"📂 {key} ({len(items)} 个文件)"
            parent_id = self.tree.insert(
                "",
                "end",
                values=("", group_text, "", "", ""),
                open=True,
                tags=("summary",),
            )

            for item in items:
                path = item.path
                try:
                    mtime = datetime.datetime.fromtimestamp(
                        path.stat().st_mtime
                    ).strftime("%Y-%m-%d %H:%M")
                    total_bytes = self.get_total_size(path)
                    size_mb = f"{total_bytes / 1024 / 1024:.2f} MB"
                except FileNotFoundError:
                    mtime = "Unknown"
                    size_mb = "Unknown"

                self.tree.insert(
                    parent_id,
                    "end",
                    values=(
                        "☐",
                        f" └─ {'💼' if item.is_archive else '📁'} {path.name}",
                        mtime,
                        size_mb,
                        str(path),
                    ),
                    tags=("file",),
                )

    def get_total_size(self, path: Path) -> int:
        """如果是文件直接返回大小，如果是文件夹则递归计算总大小"""
        try:
            if path.is_file():
                return path.stat().st_size

            total = 0
            for p in path.rglob("*"):
                if p.is_file():
                    total += p.stat().st_size
            return total
        except Exception:
            return 0

    def on_click(self, event):
        """处理复选框点击逻辑"""
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return

        column = self.tree.identify_column(event.x)
        if column == "#1":
            item_id = self.tree.identify_row(event.y)
            if not item_id:
                return

            parent_id = self.tree.parent(item_id)
            if parent_id:
                current_values = list(self.tree.item(item_id, "values"))
                current_mark = current_values[0]
                new_mark = "☑" if current_mark == "☐" else "☐"
                current_values[0] = new_mark
                self.tree.item(item_id, values=current_values)

    def on_double_click(self, event):
        """双击打开文件夹并选中文件"""
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return

        values = self.tree.item(item_id, "values")
        if values and values[4]:
            file_path = Path(values[4])
            if file_path.exists():
                # Windows Explorer 选中文件命令
                if os.name == "nt":
                    subprocess.run(["explorer", "/select,", str(file_path)])
                else:
                    # Linux/Mac 简单打开父目录
                    subprocess.run(["xdg-open", str(file_path.parent)])

    def select_older(self):
        """逻辑：每组保留修改时间最新的，勾选其他的"""
        for parent_id in self.tree.get_children():
            children = self.tree.get_children(parent_id)
            if not children:
                continue

            file_list = []
            for child_id in children:
                path_str = self.tree.item(child_id, "values")[4]
                try:
                    mtime = os.path.getmtime(path_str)
                    file_list.append((child_id, mtime))
                except OSError:
                    file_list.append((child_id, 0))  # 读不到时间就当最旧

            # 按时间倒序排列
            file_list.sort(key=lambda x: x[1], reverse=True)

            # 第一个是最新的，其他的全部勾选
            for i, (child_id, _) in enumerate(file_list):
                values = list(self.tree.item(child_id, "values"))
                if i == 0:
                    values[0] = "☐"
                else:
                    values[0] = "☑"
                self.tree.item(child_id, values=values)

    def invert_selection(self):
        """反选"""
        for parent_id in self.tree.get_children():
            for child_id in self.tree.get_children(parent_id):
                values = list(self.tree.item(child_id, "values"))
                values[0] = "☑" if values[0] == "☐" else "☐"
                self.tree.item(child_id, values=values)

    def delete_selected(self):
        """删除打钩的文件"""
        to_delete = []
        ui_items_to_remove = []

        for parent_id in self.tree.get_children():
            for child_id in self.tree.get_children(parent_id):
                values = self.tree.item(child_id, "values")
                if values[0] == "☑":
                    path = values[4]
                    to_delete.append(path)
                    ui_items_to_remove.append(child_id)

        if not to_delete:
            messagebox.showinfo("提示", "没有勾选任何文件。")
            return

        confirm = messagebox.askyesno(
            "确认删除",
            f"确定要将这 {len(to_delete)} 个文件移入回收站吗？\n此操作可以撤销。",
            icon="warning",
        )
        if not confirm:
            return

        success_count = 0
        fail_count = 0

        for path_str in to_delete:
            try:
                send2trash(path_str)
                success_count += 1
            except Exception as e:
                logger.error(f"删除失败: {path_str} | {e}")
                fail_count += 1
                if path_str in [
                    self.tree.item(i, "values")[4] for i in ui_items_to_remove
                ]:
                    pass

        for child_id in ui_items_to_remove:
            self.tree.delete(child_id)

        for parent_id in self.tree.get_children():
            if not self.tree.get_children(parent_id):
                self.tree.delete(parent_id)

        messagebox.showinfo(
            "完成", f"删除成功: {success_count} 个\n失败: {fail_count} 个"
        )
