# Koma 项目指南

## 项目简介

KOMA 是一个**本地漫画/同人本整理工具**（GUI 桌面应用）。核心能力：

- **扫描清理**：识别并剔除尾部广告二维码（WeChatQRCode）、清理 `.url`/`.txt`/`Thumbs.db` 等杂项
- **重命名**：文件夹内图片按自然顺序重命名为 `000, 001, ...`
- **格式转换**：基于 FFmpeg 多线程转 AVIF (SVT/AOM) / WebP / JPEG XL，生成 CSV 压缩率报告
- **归档查重**：递归扫描文件夹与压缩包，按文件名正则 + 封面相似度查重
- **合集装订**：把散图/单话文件夹/压缩包"装订"成合集，支持拖拽排序

> ⚠️ **最高优先级规则**：本工具会**删除、重命名、移动、覆盖用户文件**。
> 任何涉及文件变更的改动，必须先读下面的《文件操作的失败路径》一节。
> 中途失败会残留部分状态并导致用户数据丢失的改动，一律视为**阻断问题**。

## 技术栈

- **语言**：Python `>=3.12`（`.python-version` 为 3.14）
- **依赖管理**：`uv`（src 布局，`pythonpath = "src"`）
- **GUI**：Tkinter + `tkinterdnd2`（拖拽）
- **图像处理**：OpenCV、Pillow、`onnxruntime`（仅封面相似度查重需要）、`natsort`（自然排序）
- **外部二进制**：FFmpeg（转换）、7-Zip（归档，缺失时回退 Python 原生 zip）
- **安全删除**：`send2trash`（进回收站，非 `os.remove`）
- **Lint/Format**：`ruff`（pre-commit hook，`line-length = 88`）
- **测试**：`pytest` + `pytest-cov`（addopts 自带 `--cov=koma`）
- **构建**：`uv build`（wheel）、`pyinstaller build.spec`（单文件 exe）

## 常用命令

```bash
uv sync                 # 安装运行时依赖
uv sync --all-groups    # 安装含 dev 依赖（ruff/pytest/pyinstaller/commitizen）
uv run koma             # 运行 GUI
uv run pytest           # 运行全部测试（含覆盖率）
uv run pytest tests/test_renamer.py -v   # 运行单个测试文件（加 --no-cov 可跳过覆盖率统计）
uv run ruff check .     # lint
uv run ruff format .    # 格式化
uv run cz bump          # commitizen 版本号 + changelog
uv build                # 打 wheel
uv run pyinstaller build.spec   # 打单文件 exe
```

### 排障

- **`uv sync` 会改写 `pyproject.toml` 与 `uv.lock`**：本机 uv 版本若与
  `[build-system] requires` 里的 `uv_build` 区间不匹配，uv 会自动上调该区间并重解析整个
  lock（可能产生上千行无关 diff）。提交前 `git diff` 确认；不想要就
  `git checkout -- pyproject.toml uv.lock`。
- **运行日志**：默认写到 `<配置目录>/logs/koma.log`（`RotatingFileHandler`，2MB × 3 备份），
  由 `[app].enable_file_log` 控制，可在 设置 → 常规 里关闭且**立即生效**
  （见 `utils.setup_file_logging` / `remove_file_logging`）。打包版是 `console=False`，
  stdout 无效，排查问题应看这个文件。

## 项目模块地图

```
src/koma/
├── main.py              # 入口：启动 TkinterDnD + KomaGUI
├── config.py            # 配置模型：GlobalConfig / ConfigManager / 各 *Config dataclass / TOML 模版
├── utils.py             # 全局 logger（logging.getLogger("koma")）
├── core/                # 业务逻辑（无 GUI 依赖，可独立测试）
│   ├── scanner.py           # Scanner / ScanResult：扫描目录，分类 to_convert/to_copy/ads/junk/archives
│   ├── image_processor.py   # ImageProcessor / ImageInfo：判断动图/灰度图、二维码广告检测（cv2 + onnx）
│   ├── renamer.py           # Renamer：按自然顺序重命名图片（含两阶段重命名与回滚）
│   ├── converter.py         # Converter / Status / ConversionResult：FFmpeg 多线程转换 + CSV 报告
│   ├── command_generator.py # CommandGenerator：生成 FFmpeg 命令行参数（_opts_avif 等）
│   ├── deduplicator.py      # Deduplicator / DuplicateItem：文件名正则 + 封面相似度查重
│   ├── binder.py            # Binder：合集装订（合并/重命名/归档）
│   └── archive.py           # ArchiveHandler：7-Zip / 原生 zip 归档与解压
├── ui/                  # Tkinter GUI（Tab 结构）
│   ├── app.py               # KomaGUI 主窗口
│   ├── base_tab.py          # Tab 基类（含 safe_update_status 跨线程封装）
│   ├── scan_tab.py          # 扫描清理 Tab
│   ├── convert_tab.py       # 格式转换 Tab
│   ├── rename_tab.py        # 重命名 Tab
│   ├── dedupe_tab.py        # 查重 Tab
│   ├── dedupe_window.py     # 查重结果窗口
│   ├── binder_tab.py        # 合集装订 Tab
│   ├── settings.py          # 设置对话框
│   └── utils.py             # UI 字体/文本辅助
└── resources/           # 内置资源：7z/、onnx/（模型）、wechat_qrcode/、koma.ico
```

`tests/` 与 `core/` 模块基本一一对应：`conftest.py`、`test_scanner.py`、`test_converter.py`、
`test_renamer.py`、`test_deduplicator.py`、`test_binder.py`、`test_archive.py`、
`test_cmd_gen.py`、`test_image_processor.py`、`test_regex.py`、`test_config.py`。

## 架构约定

- **core 与 ui 分离**：`core/*` 不依赖 Tkinter，只做纯逻辑，因此可被 `tests/` 直接单测。改业务逻辑时优先在 `core/` 改，UI 只负责调用与展示。
- **配置经 `GlobalConfig` 传递**：各 core 类在 `__init__` 接收对应 `*Config`（如 `ExtensionsConfig`、`ConverterConfig`、`ScannerConfig`、`DeduplicatorConfig`），不要直接读全局单例。
- **顺序一律用 `natsorted`**：图片/文件排序用 `natsort.natsorted`（自然序，`2 < 10`），不要用裸 `sorted`。
- **删除用 `send2trash`**：不要直接 `os.remove` / `shutil.rmtree` 用户文件。
- **外部二进制惰性/容错**：FFmpeg、7-Zip 可能缺失，代码需有回退与 `logger.warning`（见 `ArchiveHandler._find_7z`）。
- **重型依赖惰性导入**：`onnxruntime` 只能在真正用到时导入（见 `Deduplicator._init_onnx`）。`core/__init__.py` 聚合导出了所有 core 类，而 `ui/app.py` 会经 `dedupe_tab → dedupe_window → koma.core` 间接导入，**顶层 import 会让每次启动白付约 0.22s**，即使从不使用查重。
- **日志用项目 logger**：`from koma.utils import logger` 或 `logging.getLogger(__name__)`，不要在库代码里 `print`（ruff T20 会拦）。
- **注释/文档用中文**：现有代码注释、docstring、UI 文案均为中文，保持一致。

## 过滤规则语义

- **`system_junk`**（系统垃圾文件）：显式列出的名字**优先于一切判断**，即使扩展名在支持列表里
  也判为垃圾（见 `Scanner._is_junk`）。命中的**目录**会被整体列为待清理项并跳过递归
  （如 `__MACOSX`），因此不要往里塞正常目录名。
- **`misc_whitelist`**（杂项白名单）：优先级低于 `system_junk`，用于保留 `comicinfo.xml`、
  `readme.txt` 这类非图片但需要保留的文件。
- **`qr_whitelist`**（二维码白名单）：按二维码 URL 的 **host 域名**匹配（主域或子域），
  **不是子串匹配**（见 `ImageProcessor._is_whitelisted`）。子串匹配会误放行
  `https://notpixiv.net/ad` 和 `https://evil.com/?ref=qq.com` 这类绕过，别改回去。
  该列表有**三处副本**：`config.py` 的 `ScannerConfig` 默认值、`config.example.toml`、
  用户的 `config.toml`（后者会覆盖前者，改默认值对已存在配置文件的环境不生效）。
  `tests/test_config.py` 有防漂移用例，改动务必同步。
- 两者都是**按文件名小写全等匹配**，不是 glob/正则。
- 未命中任何规则且扩展名不在支持列表里的文件，一律判为杂项 —— 新增支持格式时记得同步
  `[extensions]` 配置。

## 测试与覆盖率

- 覆盖率**故意排除** `main.py`、`utils.py`、`__init__.py`、`ui/*`（见 `pyproject.toml`
  的 `[tool.coverage.run] omit`）——不要为这些文件补测试或标记缺失。
- `conftest.py` 提供 fixture：`global_config`、`ext_config`、`scanner_config`、
  `converter_config`、`dedupe_config`、`mock_image_processor`。
  写 `core/` 测试时优先用 `mock_image_processor`（默认：非动图、非灰度、无二维码），
  避免真的去解码图片。
- 新增 `core/` 行为必须配对应 `tests/test_*.py` 用例；新分支（if/except）需覆盖。
- `pytest` 的 addopts 自带 `--cov=koma`，所以跑单个测试文件也会做全量覆盖率统计（比预期慢），
  只验证逻辑时加 `--no-cov`。
- 测试一律用 `tmp_path` 造数据，**不要依赖 `data/` 目录**：它在 `.gitignore` 里，
  是开发者本地手工验证用的语料，不随仓库分发，CI 上不存在。
- 涉及文件名/路径的改动注意 Unicode 与 Windows 长路径（真实场景含大量 CJK 文件名）。

## 代码风格

- 遵循 `ruff` 规则集（E, W, F, I, B, C4, UP, N, SIM, RUF, T20），`line-length = 88`。
- 提交信息遵循 **conventional commits**（commitizen，`cz check` 在 pre-commit 校验）。
- 类型注解：公共函数尽量补全注解，`Optional` 接收者解引用前先收窄。
- ⚠️ **`.md` 里的 Python 代码围栏会被 ruff 格式化**。ruff 只解析语言标注为 `python` 或 `py`
  的围栏；标注为 `bash`、`text`，或完全不写语言标注的围栏，都不受影响。
  一旦标注成 Python 却没按 ruff 的格式写，`uv run ruff format --check` 会报 `unformatted`，
  **CI 直接失败**。写法二选一：按 ruff 格式化，或改用非 Python 的语言标注。

## AI 协作资产

- `AGENTS.md`（本文件）是**唯一事实来源**。`.github/copilot-instructions.md` 只做指针，
  **不要在里面重复内容**，否则两处会漂移。
- `.github/skills/code-review/SKILL.md`：结构化代码评审流程。报告格式固定为
  **阻断问题 / 警告 / 小建议**，每条带 `file:line` + 修复建议，正文中文，
  末尾附「检查结果」与结论。
  该 skill 第 2 步依赖 Pylance MCP（`mcp_pylance_mcp_s_pylanceLSP`）；**未配置时跳过该步即可**，
  不要因为拿不到诊断就跳过整个流程。

## 提交前自检

1. `uv run ruff check .` 与 `uv run ruff format --check .` 均通过
2. `uv run pytest` 全绿，且 `core/` 的新行为有新测试
3. 若改动了文件删除/重命名/移动/覆盖逻辑：走查失败路径，确认不会残留导致数据丢失的状态
4. 若改动了 UI 的 `_run_thread`：确认没有从后台线程直接碰 Tkinter
5. 若新增了 `.md`：确认语言标注为 `python` / `py` 的代码围栏符合 ruff 格式
