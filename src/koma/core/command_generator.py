import shutil
from pathlib import Path


class CommandGenerator:
    def __init__(self, format_name: str, quality: int, lossless: bool):
        self.raw_format = format_name.lower()
        self.base_fmt = self.raw_format.split(" ")[0]

        self.quality = quality
        self.lossless = lossless

        self.ffmpeg_bin = shutil.which("ffmpeg")
        if not self.ffmpeg_bin:
            raise FileNotFoundError("未找到 FFmpeg，请确保已正确安装并配置环境变量。")

    def get_ext(self) -> str:
        ext_map = {"avif": ".avif", "webp": ".webp", "jxl": ".jxl", "heic": ".heic"}
        return ext_map.get(self.base_fmt, ".avif")

    def generate(self, src: Path, dst: Path, is_anim: bool, is_gray: bool) -> list[str]:
        """生成 FFmpeg 命令行参数"""

        cmd = [self.ffmpeg_bin, "-hide_banner", "-y", "-i", str(src)]

        # 禁用不需要的音频/字幕轨道
        cmd.extend(["-an", "-sn"])

        # 获取编码参数
        opts = self._build_opts(
            self.raw_format, self.quality, self.lossless, is_anim, is_gray
        )
        cmd.extend(opts)

        # 输出路径
        cmd.append(str(dst))

        return cmd

    def _build_opts(
        self, fmt_full: str, quality: int, lossless: bool, is_anim: bool, is_gray: bool
    ) -> list[str]:
        cmd = []
        fmt = fmt_full.split(" ")[0]

        if fmt == "avif":
            pix_fmt = "yuv420p10le"

            # SVT-AV1 速度快
            if "svt" in fmt_full or "avif" == fmt_full:  # 默认 SVT
                svt_params = ["tune=0", "lp=2"]  # Visual tuning, Lookahead

                if lossless or quality >= 100:
                    crf = 0
                    svt_params.append("lossless=1")
                    preset = "8"
                else:
                    # SVT-AV1 的 CRF 范围是 0-63, quality(75) -> crf(35)
                    crf = max(0, min(63, int((100 - quality) * 0.76 + 16)))
                    preset = "6"

                svt_params_str = ":".join(svt_params)
                cmd.extend(
                    [
                        "-c:v",
                        "libsvtav1",
                        "-preset",
                        preset,
                        "-crf",
                        str(crf),
                        "-pix_fmt",
                        pix_fmt,
                        "-svtav1-params",
                        svt_params_str,
                    ]
                )

            # AOM 画质大小更优，但是速度很慢
            elif "aom" in fmt_full:
                if lossless or quality >= 100:
                    crf = 0
                    cpu_used = "6"
                else:
                    # AOM 的 CRF 范围也是 0-63, quality(75) -> crf(23)
                    crf = max(0, min(63, int((100 - quality) * 0.6 + 8)))
                    cpu_used = "6"

                cmd.extend(
                    [
                        "-c:v",
                        "libaom-av1",
                        "-cpu-used",
                        cpu_used,
                        "-crf",
                        str(crf),
                        "-pix_fmt",
                        pix_fmt,
                        "-b:v",
                        "0",
                    ]
                )

        elif fmt == "webp":
            encoder = "libwebp_anim" if is_anim else "libwebp"
            cmd.extend(["-c:v", encoder])

            if lossless:
                cmd.extend(["-lossless", "1"])
            else:
                cmd.extend(["-q:v", str(quality)])
                cmd.extend(["-preset", "default"])

        elif fmt == "jxl":
            cmd.extend(["-c:v", "libjxl"])

            # Effort 7: 生成速度和体积的甜点位
            cmd.extend(["-effort", "7"])

            if lossless or quality >= 100:
                # 纯无损 (Modular Mode)
                cmd.extend(["-distance", "0.0"])
            else:
                distance = max(0.1, (100 - quality) / 15.0)
                cmd.extend(["-distance", f"{distance:.1f}"])

        if not is_anim:
            cmd.extend(["-frames:v", "1"])

        return cmd
