from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
import subprocess


QUALITY_PRESETS = {
    "ultra": ("18", "slow"),
    "high": ("23", "medium"),
    "medium": ("28", "medium"),
    "low": ("32", "fast"),
}

COMMON_FFMPEG_PATHS = [
    Path("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"),
    Path("/usr/local/opt/ffmpeg-full/bin/ffmpeg"),
]

COMMON_FFPROBE_PATHS = [
    Path("/opt/homebrew/opt/ffmpeg-full/bin/ffprobe"),
    Path("/usr/local/opt/ffmpeg-full/bin/ffprobe"),
]


def _existing(paths: list[str | Path | None]) -> list[str]:
    result = []
    for path in paths:
        if not path:
            continue
        text = str(path)
        if Path(text).exists() or shutil.which(text):
            result.append(text)
    return result


def ffprobe_path() -> str:
    candidates = _existing(
        [
            os.environ.get("CAPTIONFORGE_FFPROBE"),
            shutil.which("ffprobe"),
            *COMMON_FFPROBE_PATHS,
        ]
    )
    if not candidates:
        raise RuntimeError("Missing required executable: ffprobe")
    return candidates[0]


def ffmpeg_path(require_subtitles: bool = False) -> str:
    candidates = _existing(
        [
            os.environ.get("CAPTIONFORGE_FFMPEG"),
            shutil.which("ffmpeg"),
            *COMMON_FFMPEG_PATHS,
        ]
    )
    if not candidates:
        raise RuntimeError("Missing required executable: ffmpeg")
    if not require_subtitles:
        return candidates[0]
    for candidate in candidates:
        filters = available_filters(candidate)
        if "subtitles" in filters or "ass" in filters:
            return candidate
    raise RuntimeError(
        "No available ffmpeg build includes the subtitles/ass filter. "
        "Install ffmpeg-full or another libass-enabled ffmpeg build, then retry."
    )


def require_ffmpeg(require_subtitles: bool = False) -> str:
    ffprobe_path()
    return ffmpeg_path(require_subtitles)


def available_filters(ffmpeg: str | None = None) -> set[str]:
    binary = ffmpeg or ffmpeg_path()
    result = subprocess.run([binary, "-hide_banner", "-filters"], check=True, capture_output=True, text=True)
    names = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and not parts[0].startswith("-"):
            names.add(parts[1])
    return names


def available_encoders(ffmpeg: str | None = None) -> set[str]:
    binary = ffmpeg or ffmpeg_path()
    result = subprocess.run([binary, "-hide_banner", "-encoders"], check=True, capture_output=True, text=True)
    names = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and not parts[0].startswith("-"):
            names.add(parts[1])
    return names


_ENCODER_MAP = {
    "cpu": "cpu",
    "nvenc": "nvenc",
    "qsv": "qsv",
    "amf": "amf",
    "videotoolbox": "videotoolbox",
}

ENCODER_CHOICES = [
    "auto",
    "cpu",
    "nvenc",
    "qsv",
    "amf",
    "videotoolbox",
    "libx264",
    "libx265",
    "libsvtav1",
    "libaom-av1",
    "libvvenc",
    "h264_nvenc",
    "hevc_nvenc",
    "av1_nvenc",
    "h264_qsv",
    "hevc_qsv",
    "av1_qsv",
    "h264_amf",
    "hevc_amf",
    "av1_amf",
    "h264_videotoolbox",
    "hevc_videotoolbox",
]

_CODEC_SOFTWARE = {
    "h264": "libx264",
    "hevc": "libx265",
    "av1": "libsvtav1",
    "vvc": "libvvenc",
}


def _software_encoder(codec: str, ffmpeg: str | None = None) -> str:
    encoders = available_encoders(ffmpeg)
    sw = _CODEC_SOFTWARE.get(codec, "libx264")
    if sw in encoders:
        return sw
    if codec == "av1" and "libaom-av1" in encoders:
        return "libaom-av1"
    if ffmpeg:
        raise RuntimeError(f"No software encoder for codec {codec!r} is available in {ffmpeg}")
    return sw


def select_encoder(preferred: str | None = None, codec: str = "h264", ffmpeg: str | None = None) -> str:
    if preferred == "cpu":
        return _software_encoder(codec, ffmpeg)
    if preferred and preferred != "auto":
        mapped = _ENCODER_MAP.get(preferred)
        if mapped:
            candidate = f"{codec}_{mapped}"
            if candidate in available_encoders(ffmpeg):
                return candidate
            return _software_encoder(codec, ffmpeg)
        return preferred
    encoders = available_encoders(ffmpeg)
    platforms = ["nvenc", "qsv", "amf"]
    if platform.system() == "Darwin":
        platforms.insert(0, "videotoolbox")
    for encoder_platform in platforms:
        candidate = f"{codec}_{encoder_platform}"
        if candidate in encoders:
            return candidate
    return _software_encoder(codec, ffmpeg)


def require_subtitle_filter() -> str:
    return require_ffmpeg(require_subtitles=True)


def escape_filter_path(path: Path) -> str:
    text = str(path.resolve())
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", r"\'")
        .replace(",", r"\,")
        .replace("[", r"\[")
        .replace("]", r"\]")
        .replace(";", r"\;")
    )


def encode_args(output: Path, quality: str, encoder: str | None = None) -> list[str]:
    if quality not in QUALITY_PRESETS:
        raise ValueError(f"Unknown quality {quality!r}; expected one of {', '.join(QUALITY_PRESETS)}")
    crf, preset = QUALITY_PRESETS[quality]
    if output.suffix.lower() == ".webm":
        return ["-c:v", "libvpx-vp9", "-crf", crf, "-b:v", "0"]

    enc = encoder or "libx264"

    # Software encoders share CRF-style quality control.
    if enc in ("libx264", "libx265"):
        return ["-c:v", enc, "-crf", crf, "-preset", preset]

    if enc == "libsvtav1":
        svt_preset = {"slow": "4", "medium": "6", "fast": "8"}.get(preset, "6")
        return ["-c:v", "libsvtav1", "-crf", str(crf), "-preset", svt_preset]

    if enc == "libaom-av1":
        aom_speed = {"slow": "2", "medium": "4", "fast": "6"}.get(preset, "4")
        return ["-c:v", "libaom-av1", "-crf", str(crf), "-cpu-used", aom_speed]

    if enc == "libvvenc":
        return ["-c:v", "libvvenc", "-qp", str(crf), "-preset", preset, "-pix_fmt", "yuv420p10le"]

    # NVENC uses constant-quality VBR across h264, hevc, and av1.
    if enc.endswith("_nvenc"):
        return [
            "-c:v", enc,
            "-rc", "vbr",
            "-cq", str(crf),
            "-preset", preset,
        ]

    # QSV exposes quality through global_quality for h264, hevc, and av1.
    if enc.endswith("_qsv"):
        return [
            "-c:v", enc,
            "-global_quality", str(crf),
            "-preset", preset,
        ]

    # AMF uses CQP values and maps presets to quality/balanced/speed.
    if enc.endswith("_amf"):
        amf_preset = "quality" if preset == "slow" else "balanced" if preset == "medium" else "speed"
        return [
            "-c:v", enc,
            "-rc", "cqp",
            "-qp_p", str(crf),
            "-qp_i", str(crf),
            "-preset", amf_preset,
        ]

    if enc.endswith("_videotoolbox"):
        return ["-c:v", enc, "-q:v", str(crf)]

    return ["-c:v", enc]


def probe_video_size(video: Path) -> tuple[int, int]:
    cmd = [
        ffprobe_path(),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=s=x:p=0",
        str(video),
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    text = result.stdout.strip().splitlines()[0]
    try:
        width, height = text.split("x", 1)
        return int(width), int(height)
    except (IndexError, ValueError) as exc:
        raise RuntimeError(f"Could not read video resolution for {video}") from exc


def probe_video_codec(video: Path) -> str:
    cmd = [
        ffprobe_path(),
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video),
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    lines = result.stdout.strip().splitlines()
    codec = lines[0].lower() if lines else ""
    if codec in {"h264", "avc1"}:
        return "h264"
    if codec in {"hevc", "h265"}:
        return "hevc"
    if codec in {"av1"}:
        return "av1"
    if codec in {"vvc", "h266"}:
        return "vvc"
    return "h264"


def probe_pix_fmt(video: Path) -> str:
    cmd = [
        ffprobe_path(),
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=pix_fmt",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video),
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return result.stdout.strip().splitlines()[0]


def _parse_rate(rate_str: str) -> float:
    try:
        if "/" in rate_str:
            num, den = rate_str.split("/")
            denominator = float(den)
            if denominator == 0:
                return 0.0
            return float(num) / denominator
        return float(rate_str)
    except (TypeError, ValueError):
        return 0.0


def probe_fps(video: Path) -> float:
    cmd = [
        ffprobe_path(),
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate,avg_frame_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video),
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
    r_rate = _parse_rate(lines[0]) if lines else 24.0
    avg_rate = _parse_rate(lines[1]) if len(lines) > 1 else r_rate
    if r_rate <= 0 and avg_rate <= 0:
        return 24.0
    if r_rate <= 0:
        return avg_rate
    # For VFR inputs, prefer avg_frame_rate when it meaningfully differs from r_frame_rate.
    if avg_rate > 0 and abs(r_rate - avg_rate) / max(r_rate, 1.0) > 0.05:
        return avg_rate
    return r_rate


def probe_color_info(video: Path) -> dict[str, str | None]:
    """Return color primaries, transfer, and space info."""
    cmd = [
        ffprobe_path(),
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=color_primaries,color_transfer,color_space",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video),
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    keys = ["color_primaries", "color_transfer", "color_space"]
    info: dict[str, str | None] = {}
    for i, key in enumerate(keys):
        info[key] = lines[i] if i < len(lines) and lines[i] != "unknown" else None
    return info


def probe_duration(video: Path) -> float:
    cmd = [
        ffprobe_path(),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=nw=1:nk=1",
        str(video),
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(f"Could not read video duration for {video}") from exc


def ass_filter(ass_path: Path, font_dirs: list[Path] | None = None, filters: set[str] | None = None) -> str:
    filter_names = filters or available_filters()
    filter_name = "ass" if "ass" in filter_names else "subtitles"
    value = f"{filter_name}=filename='{escape_filter_path(ass_path)}'"
    if font_dirs:
        value += f":fontsdir='{escape_filter_path(font_dirs[0])}'"
    return value


def burn_subtitles(
    video: Path,
    ass_path: Path,
    output: Path,
    extra_args: list[str] | None = None,
    quality: str = "medium",
    font_dirs: list[Path] | None = None,
    verbose: bool = False,
    encoder: str | None = None,
    ffmpeg: str | None = None,
    output_res: tuple[int, int] | None = None,
    fallback_encoder: str | None = None,
) -> None:
    ffmpeg = ffmpeg or require_subtitle_filter()
    filters = available_filters(ffmpeg)
    output.parent.mkdir(parents=True, exist_ok=True)
    vf_parts = []
    if output_res:
        vf_parts.append(f"scale={output_res[0]}:{output_res[1]}:flags=lanczos")
    vf_parts.append(ass_filter(ass_path, font_dirs, filters))
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "info" if verbose else "error",
        "-i",
        str(video),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        ",".join(vf_parts),
        "-c:a",
        "copy",
        *encode_args(output, quality, encoder),
    ]
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(str(output))
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        if not fallback_encoder or fallback_encoder == encoder:
            raise
        fallback_cmd = [
            *cmd[: cmd.index("-c:a") + 2],
            *encode_args(output, quality, fallback_encoder),
        ]
        if extra_args:
            fallback_cmd.extend(extra_args)
        fallback_cmd.append(str(output))
        print(f"[CaptionForge] Encoder {encoder} failed; retrying with {fallback_encoder}.", flush=True)
        subprocess.run(fallback_cmd, check=True)


def transcode_video(
    video: Path,
    output: Path,
    quality: str = "medium",
    verbose: bool = False,
    encoder: str | None = None,
    ffmpeg: str | None = None,
    output_res: tuple[int, int] | None = None,
    extra_args: list[str] | None = None,
    fallback_encoder: str | None = None,
) -> None:
    ffmpeg = ffmpeg or require_ffmpeg()
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "info" if verbose else "error",
        "-i",
        str(video),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
    ]
    if output_res:
        cmd.extend(["-vf", f"scale={output_res[0]}:{output_res[1]}:flags=lanczos"])
    cmd.extend(["-c:a", "copy", *encode_args(output, quality, encoder)])
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(str(output))
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        if not fallback_encoder or fallback_encoder == encoder:
            raise
        fallback_cmd = [
            *cmd[: cmd.index("-c:a") + 2],
            *encode_args(output, quality, fallback_encoder),
        ]
        if extra_args:
            fallback_cmd.extend(extra_args)
        fallback_cmd.append(str(output))
        print(f"[CaptionForge] Encoder {encoder} failed; retrying with {fallback_encoder}.", flush=True)
        subprocess.run(fallback_cmd, check=True)


def soft_subtitles(video: Path, subtitle: Path, output: Path, verbose: bool = False) -> None:
    ffmpeg = require_ffmpeg()
    if output.suffix.lower() == ".webm":
        raise ValueError("WebM does not support this soft-subtitle path; use --mode hard.")
    output.parent.mkdir(parents=True, exist_ok=True)
    subtitle_codec = "mov_text" if output.suffix.lower() in {".mp4", ".m4v", ".mov"} else "copy"
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "info" if verbose else "error",
        "-i",
        str(video),
        "-i",
        str(subtitle),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-map",
        "1:0",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-c:s",
        subtitle_codec,
        str(output),
    ]
    subprocess.run(cmd, check=True)
