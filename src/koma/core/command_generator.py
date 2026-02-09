import shlex
import shutil
import sys
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=32)
def _opts_avif(
    quality: int, lossless: bool, raw_fmt: str, is_anim: bool, is_gray: bool
) -> tuple[str, ...]:
    cmd = []
    pix_fmt = "gray10le" if is_gray else "yuv420p10le"

    is_lossless_mode = lossless or quality >= 100

    # AOM 画质大小更优，但是速度很慢
    if "aom" in raw_fmt:
        if is_lossless_mode:
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
    else:
        # SVT-AV1 速度快
        svt_params = ["tune=0", "lp=2"]
        if is_lossless_mode:
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

    return tuple(cmd)


@lru_cache(maxsize=32)
def _opts_webp(
    quality: int, lossless: bool, raw_fmt: str, is_anim: bool, is_gray: bool
) -> tuple[str, ...]:
    cmd = []
    encoder = "libwebp_anim" if is_anim else "libwebp"
    cmd.extend(["-c:v", encoder])

    if lossless or quality >= 100:
        cmd.extend(["-lossless", "1"])
    else:
        cmd.extend(["-q:v", str(quality)])
        cmd.extend(["-preset", "default"])
    return tuple(cmd)


@lru_cache(maxsize=32)
def _opts_jxl(
    quality: int, lossless: bool, raw_fmt: str, is_anim: bool, is_gray: bool
) -> tuple[str, ...]:
    cmd = ["-c:v", "libjxl", "-effort", "7"]

    distance = 0.0 if lossless else max(0.0, (100 - quality) / 10.0)
    cmd.extend(["-distance", f"{distance:.1f}"])

    if is_gray:
        cmd.extend(["-pix_fmt", "gray10le"])

    return tuple(cmd)


class CommandGenerator:
    def __init__(
        self,
        format_name: str,
        quality: int,
        lossless: bool,
        custom_params: str = "",
        custom_ext: str = "",
    ):
        self.raw_format = format_name.lower()
        self.base_fmt = self.raw_format.split(" ")[0]
        self.quality = quality
        self.lossless = lossless
        self.custom_params = custom_params
        self.custom_ext = custom_ext
        self.ffmpeg_bin = self._find_ffmpeg()
        if not self.ffmpeg_bin:
            raise FileNotFoundError("未找到 FFmpeg，请确保已正确安装并配置环境变量。")

        strategies = {
            "avif": _opts_avif,
            "webp": _opts_webp,
            "jxl": _opts_jxl,
        }
        self._strategy_func = strategies.get(self.base_fmt, _opts_avif)

        ext_map = {"avif": ".avif", "webp": ".webp", "jxl": ".jxl", "heic": ".heic"}
        self._default_ext = ext_map.get(self.base_fmt, ".avif")

        self._common_head = [
            self.ffmpeg_bin,
            "-hide_banner",
            "-y",
            "-an",
            "-sn",
        ]

    def get_ext(self) -> str:
        return self.custom_ext if self.custom_ext else self._default_ext

    def generate(self, src: Path, dst: Path, is_anim: bool, is_gray: bool) -> list[str]:
        if self.custom_ext:
            encoding_opts = shlex.split(self.custom_params)
        else:
            encoding_opts = list(
                self._strategy_func(
                    self.quality, self.lossless, self.raw_format, is_anim, is_gray
                )
            )

        if not is_anim:
            encoding_opts.extend(["-frames:v", "1"])

        return [*self._common_head, "-i", str(src), *encoding_opts, str(dst)]

    def _find_ffmpeg(self) -> str | None:
        if path_in_env := shutil.which("ffmpeg"):
            return path_in_env

        if getattr(sys, "frozen", False):
            base_path = Path(sys._MEIPASS) / "koma"  # type: ignore
        else:
            base_path = Path(__file__).parent.parent

        local_ffmpeg = base_path / "resources" / "ffmpeg" / "ffmpeg.exe"
        if local_ffmpeg.exists():
            return str(local_ffmpeg)

        return None
