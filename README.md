# KOMA - 漫画工具箱
---

KOMA 是一个专为本地漫画/同人本收藏者设计的整理工具。集成了去广告、格式转换、重命名整理以及归档查重功能。

## ✨ 功能

#### 1. 🧹 扫描清理
- **去广告**：集成 WeChatQRCode，能精准识别并剔除漫画尾部的广告二维码。
- **杂项清理**: 自动识别并清理 .url, .txt, Thumbs.db 等非图片文件。

#### 2. 🛠️ 重命名
- 将文件夹内图片按自然顺序重命名为 `000, 001, 002, ...`

#### 3. 🎨 格式转换
基于 [FFmpeg](https://ffmpeg.org) 的多线程转换

- **AVIF**
    - SVT-AV1: 编码速度快，适合批量处理
    - AOM-AV1: 参考级编码器，质量体积略好于 SVT-AV1
- **WebP**: 兼容性最好
- **JPEG XL**: 无损最优选择，可无损转回原格式
- **可视化报告**: 任务结束后生成 CSV 统计报表，详细列出压缩率和体积变化。

#### 4. 📚 归档查重
- 支持扫描多个文件夹及归档包
- 识别提取 `(展会) [社团 (作者)] 作品 (系列) [语言]...`等信息，找出重复文件。

#### 5. 📖 合集装订
- 将多个图片、存档、文件夹排序并重命名到单个新文件夹

## 💻 环境要求
- **FFmpeg**: 安装并添加到系统环境变量 PATH 中，或放在 `Koma.exe` 旁。
    - **注意**: 必须使用较新的 FFmpeg 版本，且编译时需开启 `--enable-libsvtav1`，`--enable-libaom`，`--enable-libjxl`，`--enable-libwebp`（通常默认已启用）。
- **OpenCV 运行库**: Windows 用户通常无需额外操作，程序已内置。

## ⚙️ 配置
程序启动时会按照以下优先级读取配置文件 `config.toml`：
- 用户配置目录 (`~/.config/koma/`)
- 程序所在目录
- 当前工作目录

如果未找到，程序会自动在**用户配置目录**下生成一份带有默认值的 `config.toml`。

## 🚀 安装与运行

#### 方式一：下载可执行文件（推荐普通用户）
前往 [Releases](https://github.com/grasssand/koma/releases) 页面下载最新的 `Koma.exe` (Windows)，点击即用。请确保 `ffmpeg.exe` 在同级目录或系统路径中。

#### 方式二：源码运行（开发人员）
本项目使用 uv 进行依赖管理。
1. 克隆本仓库
```bash
git clone https://github.com/grasssand/koma.git
cd koma
```
2. 安装依赖并运行
```bash
uv sync
uv run koma
```
3. 开发、测试与构建
```bash
# 安装开发依赖
uv sync --all-groups

# 运行所有测试
uv run pytest

# 打包为 wheel
uv build

# 使用 PyInstaller 打包为单文件 exe
uv run pyinstaller build.spec
```

## 📄 开源协议
本项目采用 [MIT License](./LICENSE) 开源。

二维码识别模型来自 [WeChatCV/opencv_3rdparty](https://github.com/WeChatCV/opencv_3rdparty)，7-Zip (7z.exe, 7z.dll) 来自 [www.7-zip.org](https://www.7-zip.org/) ，FFmpeg (ffmpeg.exe) 来自 [www.ffmpeg.org](https://www.ffmpeg.org/)。遵循其各自协议。
