import datetime
import os
import subprocess
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, ttk

from send2trash import send2trash

from koma.config import GlobalConfig
from koma.core import Deduplicator
from koma.utils import logger


class DedupeWindow(tk.Toplevel):
    def __init__(
        self,
        parent,
        input_paths: list[Path],
        config: GlobalConfig,
        mode: str = "filename",
        threshold: int = 85,
        *,
        task_launcher: Callable,
        ui_dispatch: Callable,
    ):
        super().__init__(parent)
        self.title("📚 归档查重结果 - 扫描初始化...")

        window_width = 900
        window_height = 600
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        self.geometry(f"{window_width}x{window_height}+{x}+{y}")

        self.config = config
        self.input_paths = input_paths
        self.mode = mode
        self.threshold = threshold

        self.deduplicator = Deduplicator(config.extensions, config.deduplicator)
        self._task_launcher = task_launcher
        self._ui_dispatch = ui_dispatch
        self.results = {}
        # 体积在后台线程预先算好，避免主线程递归 stat 卡死 UI
        self.sizes: dict[str, int] = {}

        self._setup_ui()

        self._start_scan_thread()

    def _setup_ui(self):
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=5, pady=5)

        ttk.Button(toolbar, text="选择旧文件", command=self.select_older).pack(
            side="left", padx=5
        )
        ttk.Button(toolbar, text="反向选择", command=self.invert_selection).pack(
            side="left", padx=5
        )
        ttk.Button(toolbar, text="取消选择", command=self.deselect_all).pack(
            side="left", padx=5
        )

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=5)

        self.btn_delete = ttk.Button(
            toolbar, text="删除选中到回收站", command=self.delete_selected
        )
        self.btn_delete.pack(side="left", padx=5)

        ttk.Label(
            toolbar, text="💡 双击打开文件，中键打开位置", foreground="gray"
        ).pack(side="right", padx=10)

        columns = ("check", "name", "mtime", "size", "path")
        self.tree = ttk.Treeview(
            self,
            columns=columns,
            show="headings",
            selectmode="browse",
            style="Dedupe.Treeview",
        )

        self.tree.heading("check", text="选择")
        self.tree.heading("name", text="文件名")
        self.tree.heading("mtime", text="修改时间")
        self.tree.heading("size", text="大小")
        self.tree.heading("path", text="位置")

        self.tree.column("check", width=50, anchor="center", stretch=False)
        self.tree.column("name", width=400, anchor="w")
        self.tree.column("mtime", width=120, anchor="center", stretch=False)
        self.tree.column("size", width=80, anchor="e", stretch=False)
        self.tree.column("path", width=200, anchor="w")

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 绑定事件
        self.tree.bind("<Button-1>", self.on_click)
        self.tree.bind("<Double-1>", self.on_double_click)
        self.tree.bind("<Button-2>", self.on_middle_click)

        # 定义样式标签
        self.tree.tag_configure(
            "summary",
            background="#e8f4ff",
            font=(self.config.app.font, self.config.app.list_font_size, "bold"),
        )

    def _toggle_ui(self, enable: bool):
        state = "normal" if enable else "disabled"
        self.btn_delete.config(state=state)
        # 扫描期间鼠标转圈
        cursor = "" if enable else "watch"
        self.config_cursor(cursor)

    def config_cursor(self, cursor):
        try:
            self.configure(cursor=cursor)
        except tk.TclError:
            pass

    def _start_scan_thread(self):
        self._toggle_ui(False)
        self._task_launcher(self._run_scan)

    def _post_to_ui(self, callback: Callable) -> None:
        """在主线程执行回调，并忽略已关闭的结果窗口。"""

        def guarded_callback():
            try:
                if self.winfo_exists():
                    callback()
            except tk.TclError:
                return

        self._ui_dispatch(guarded_callback)

    def _run_scan(self):
        try:

            def cb(curr, total, msg):
                self._post_to_ui(lambda: self.title(f"📚 查重中... {msg}"))

            self.results = self.deduplicator.run(
                self.input_paths, self.mode, self.threshold, progress_callback=cb
            )

            # 体积必须在后台算完：一个候选文件夹要递归 stat 全部文件，
            # 放到 _populate_tree（主线程）里会让大库直接冻住界面。
            self._post_to_ui(lambda: self.title("📚 正在统计体积..."))
            self.sizes = self._collect_sizes(self.results)
            self._post_to_ui(self._on_scan_complete)

        except Exception as e:
            msg = str(e)
            logger.error(f"查重扫描出错: {msg}", exc_info=True)

            def on_failure():
                messagebox.showerror("错误", f"扫描失败: {msg}", parent=self)
                self.destroy()

            self._post_to_ui(on_failure)

    def _on_scan_complete(self):
        self._toggle_ui(True)
        self._populate_tree()

        count = len(self.results)
        if count == 0:
            messagebox.showinfo("扫描完成", "🎉 没有发现重复项！", parent=self)
            self.destroy()
        else:
            self.title(f"📚 归档查重结果 - 发现 {count} 组重复")
            messagebox.showinfo(
                "扫描完成", f"共发现 {count} 组疑似重复内容。", parent=self
            )

            # 弹窗关闭后，强制将本窗口提到最前并获取焦点
            self.lift()
            self.focus_force()

    def _populate_tree(self):
        """将扫描结果填入表格"""
        # 清空旧数据
        for item in self.tree.get_children():
            self.tree.delete(item)

        for key, items in self.results.items():
            group_text = f"📂 {key} (包含 {len(items)} 个文件)"
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
                    stat = path.stat()
                    mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime(
                        "%Y-%m-%d %H:%M"
                    )
                    missing = False
                except FileNotFoundError:
                    mtime = "已丢失"
                    missing = True

                # 体积取自后台预计算结果
                size_val = self.sizes.get(str(path))
                if missing or size_val is None:
                    size_mb = "未知"
                else:
                    size_mb = f"{size_val / 1024 / 1024:.2f} MB"

                icon = "💼" if item.is_archive else "📁"

                self.tree.insert(
                    parent_id,
                    "end",
                    values=(
                        "☐",
                        f" └─ {icon} {path.name}",
                        mtime,
                        size_mb,
                        str(path),
                    ),
                )

    def _collect_sizes(self, results) -> dict[str, int]:
        """
        预算每个候选的体积（归档取文件大小，文件夹递归求和）。

        在扫描线程里调用。取不到的条目不写入，界面按「未知」显示。
        """
        sizes: dict[str, int] = {}
        for items in results.values():
            for item in items:
                key = str(item.path)
                try:
                    if item.is_archive:
                        sizes[key] = item.path.stat().st_size
                    else:
                        sizes[key] = self.get_folder_size(item.path)
                except OSError:
                    continue
        return sizes

    def get_folder_size(self, path: Path) -> int:
        """递归计算文件夹大小"""
        total = 0
        try:
            for p in path.rglob("*"):
                if p.is_file():
                    total += p.stat().st_size
        except Exception:
            pass
        return total

    def on_click(self, event):
        """自定义 Checkbox 逻辑：点击第一列切换 ☐/☑"""
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return

        column = self.tree.identify_column(event.x)
        if column == "#1":
            item_id = self.tree.identify_row(event.y)
            if not item_id:
                return

            tags = self.tree.item(item_id, "tags")
            if "summary" in tags:
                return

            current_values = list(self.tree.item(item_id, "values"))
            current_mark = current_values[0]
            new_mark = "☑" if current_mark == "☐" else "☐"
            current_values[0] = new_mark
            self.tree.item(item_id, values=current_values)

    def on_double_click(self, event):
        """双击打开文件/压缩包"""
        file_path = self._get_path_from_event(event.y)
        if not file_path or not file_path.exists():
            return

        try:
            if os.name == "nt":
                os.startfile(file_path)
            else:
                subprocess.Popen(["xdg-open", str(file_path)], close_fds=True)
        except Exception as e:
            logger.error(f"无法打开文件: {e}")
            messagebox.showerror("错误", f"无法打开文件: {e}", parent=self)

    def on_middle_click(self, event):
        """鼠标中键打开所在文件夹"""
        file_path = self._get_path_from_event(event.y)
        if not file_path or not file_path.exists():
            return

        try:
            if os.name == "nt":
                subprocess.Popen(
                    ["explorer", "/select,", str(file_path)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    creationflags=subprocess.DETACHED_PROCESS
                    | subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            else:
                subprocess.Popen(["xdg-open", str(file_path.parent)], close_fds=True)
        except Exception as e:
            logger.error(f"无法打开文件夹: {e}")
            messagebox.showerror("错误", f"无法打开文件夹: {e}", parent=self)

    def _get_path_from_event(self, event_y) -> Path | None:
        """从鼠标点击事件中提取文件路径"""
        item_id = self.tree.identify_row(event_y)
        if not item_id:
            return None

        values = self.tree.item(item_id, "values")
        if values and len(values) > 4 and values[4]:
            return Path(values[4])
        return None

    def select_older(self):
        """智能选择：保留每组中修改时间【最新】的，选中其他的"""
        for parent_id in self.tree.get_children():
            children = self.tree.get_children(parent_id)
            if not children:
                continue

            latest_id = children[0]
            values_latest = list(self.tree.item(latest_id, "values"))
            values_latest[0] = "☐"
            self.tree.item(latest_id, values=values_latest)

            for child_id in children[1:]:
                values = list(self.tree.item(child_id, "values"))
                values[0] = "☑"
                self.tree.item(child_id, values=values)

    def invert_selection(self):
        """反选"""
        for parent_id in self.tree.get_children():
            for child_id in self.tree.get_children(parent_id):
                values = list(self.tree.item(child_id, "values"))
                values[0] = "☑" if values[0] == "☐" else "☐"
                self.tree.item(child_id, values=values)

    def deselect_all(self):
        """取消选择"""
        for parent_id in self.tree.get_children():
            for child_id in self.tree.get_children(parent_id):
                values = list(self.tree.item(child_id, "values"))
                values[0] = "☐"
                self.tree.item(child_id, values=values)

    @staticmethod
    def _resolved_path(path: Path) -> Path:
        """获取用于比较的实际路径。"""
        try:
            return path.resolve(strict=False)
        except (OSError, RuntimeError):
            return Path(os.path.abspath(path))

    @classmethod
    def _entity_key(cls, path: Path) -> tuple:
        """按路径及文件系统实体识别重复行。"""
        resolved = cls._resolved_path(path)
        try:
            stat = resolved.stat()
        except OSError:
            return ("path", os.path.normcase(str(resolved)))
        if stat.st_ino:
            return ("stat", stat.st_dev, stat.st_ino)
        return ("path", os.path.normcase(str(resolved)))

    @classmethod
    def _is_ancestor(cls, parent: Path, child: Path) -> bool:
        """判断 parent 是否严格包含 child。"""
        parent = cls._resolved_path(parent)
        child = cls._resolved_path(child)
        return parent != child and child.is_relative_to(parent)

    def delete_selected(self):
        """执行删除，并保留失败行及被保护的祖先行。"""
        selected_rows = []
        retained_paths = []

        for parent_id in self.tree.get_children():
            for child_id in self.tree.get_children(parent_id):
                values = self.tree.item(child_id, "values")
                if len(values) <= 4 or not values[4]:
                    continue
                path = Path(values[4])
                row = (child_id, path, self._entity_key(path))
                if values[0] == "☑":
                    selected_rows.append(row)
                else:
                    retained_paths.append(path)

        if not selected_rows:
            messagebox.showinfo("提示", "没有勾选任何文件。", parent=self)
            return

        # 同一实体可能因重叠输入根或符号链接出现在多行，只保留一次删除操作。
        candidates = {}
        for child_id, path, entity_key in selected_rows:
            candidate = candidates.setdefault(entity_key, {"path": path, "rows": []})
            candidate["rows"].append(child_id)

        operations = []
        blocked_count = 0
        retained_keys = {self._entity_key(path) for path in retained_paths}
        for entity_key, candidate in candidates.items():
            if entity_key in retained_keys or any(
                self._is_ancestor(candidate["path"], path) for path in retained_paths
            ):
                blocked_count += 1
                logger.warning(
                    "跳过删除祖先路径（其中包含保留结果）: %s", candidate["path"]
                )
                continue
            candidate["entity_key"] = entity_key
            operations.append(candidate)

        # 选中祖先和子项时只操作祖先，避免重复移入回收站。
        operations = [
            candidate
            for candidate in operations
            if not any(
                other is not candidate
                and self._is_ancestor(other["path"], candidate["path"])
                for other in operations
            )
        ]

        if not operations:
            messagebox.showwarning(
                "无法删除",
                "选中的路径均包含保留结果，已跳过删除。",
                parent=self,
            )
            return

        # 祖先操作成功后，其下被选中的结果行也随之消失；失败则全部保留。
        for operation in operations:
            operation["rows"] = [
                child_id
                for child_id, path, entity_key in selected_rows
                if entity_key == operation["entity_key"]
                or self._is_ancestor(operation["path"], path)
            ]

        confirm = messagebox.askyesno(
            "确认删除",
            f"确定要将这 {len(operations)} 个文件移入回收站吗？\n此操作可以撤销。",
            icon="warning",
            parent=self,
        )
        if not confirm:
            return

        self.btn_delete.config(state="disabled")
        self._task_launcher(self._delete_paths, operations, blocked_count)

    def _delete_paths(self, operations: list[dict], blocked_count: int) -> None:
        success_count = 0
        fail_count = 0
        removed_rows = set()
        for operation in operations:
            path = operation["path"]
            try:
                send2trash(str(path))
                success_count += 1
                removed_rows.update(operation["rows"])
            except Exception as e:
                logger.error(f"删除失败: {path} | {e}", exc_info=True)
                fail_count += 1

        self._post_to_ui(
            lambda: self._apply_delete_result(
                removed_rows, success_count, fail_count, blocked_count
            )
        )

    def _apply_delete_result(
        self,
        removed_rows: set[str],
        success_count: int,
        fail_count: int,
        blocked_count: int,
    ) -> None:
        for child_id in removed_rows:
            self.tree.delete(child_id)

        for parent_id in self.tree.get_children():
            if not self.tree.get_children(parent_id):
                self.tree.delete(parent_id)

        msg = f"删除成功: {success_count} 个"
        if fail_count > 0:
            msg += f"\n失败: {fail_count} 个 (详情见日志)"
        if blocked_count > 0:
            msg += f"\n跳过: {blocked_count} 个包含保留结果的路径"

        self.btn_delete.config(state="normal")
        messagebox.showinfo("操作完成", msg, parent=self)
        self.lift()
        self.focus_force()
