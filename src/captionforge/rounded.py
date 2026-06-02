from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
import math
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw, ImageFont

from .ffmpeg import available_encoders, encode_args, ffmpeg_path, probe_duration, probe_fps, probe_pix_fmt, probe_color_info, probe_video_size, select_encoder
from .fontsplit import FontRule, split_mixed_font_runs
from .styles import CaptionStyle, font_collection_index, rgb_alpha, scaled_style
from .subtitles import load_subtitles


def _adjust_hdr_color(hex_color: str, factor: float) -> str:
    r, g, b, _ = rgb_alpha(hex_color)
    r = max(0, min(255, round(r * factor)))
    g = max(0, min(255, round(g * factor)))
    b = max(0, min(255, round(b * factor)))
    return f"#{r:02x}{g:02x}{b:02x}"


ASS_TAG_RE = re.compile(r"\{[^{}]*\}")
HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}
PREVIEW_FORMATS = {"auto", "png", "jpg", "jpeg", "avif", "jxl"}


@dataclass(frozen=True)
class FontSources:
    cjk_font_file: Path | None = None
    latin_font_file: Path | None = None


def plain_text(text: str) -> str:
    text = ASS_TAG_RE.sub("", text)
    return text.replace(r"\N", "\n").replace(r"\n", "\n").strip()


def rgba(hex_color: str, alpha: int) -> tuple[int, int, int, int]:
    r, g, b, _ = rgb_alpha(hex_color, alpha)
    return r, g, b, 255 - alpha


def resolve_font_file(font_name: str) -> str | None:
    fc_match = shutil.which("fc-match")
    if not fc_match:
        return None
    result = subprocess.run(
        [fc_match, "-f", "%{file}", font_name],
        check=False,
        capture_output=True,
        text=True,
    )
    path = result.stdout.strip()
    return path if path and Path(path).exists() else None


def load_font(font_name: str, size: int, font_file: Path | None = None) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    if font_file:
        candidates.append(str(font_file))
    matched = resolve_font_file(font_name)
    if matched:
        candidates.append(matched)
    # If fontconfig cannot resolve the face, fall back to CaptionForge's scanner.
    if not matched:
        from .fonts import match_font
        record = match_font(font_name)
        if record:
            candidates.append(str(record.path))
    candidates.append(font_name)

    errors = []
    for candidate in candidates:
        try:
            index = font_collection_index(Path(candidate), font_name)
            return ImageFont.truetype(candidate, size, index=index)
        except OSError as exc:
            errors.append(f"{candidate}: {exc}")
            continue
    if font_file:
        raise ValueError(f"Could not load font file {font_file}: {'; '.join(errors)}")
    warnings.warn(f"Could not resolve font {font_name!r}; using Pillow default font", RuntimeWarning, stacklevel=2)
    return ImageFont.load_default()


def text_width(draw: ImageDraw.ImageDraw, runs: list[tuple[str | None, str]], fonts: dict[str, ImageFont.ImageFont]) -> int:
    width = 0
    for font_name, value in runs:
        font = fonts.get(font_name or "", fonts["latin"])
        bbox = draw.textbbox((0, 0), value, font=font, stroke_width=0)
        width += bbox[2] - bbox[0]
    return width


def wrap_text(
    text: str,
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    max_width: int,
    style: CaptionStyle,
    font_rules: list[FontRule] | None = None,
) -> list[str]:
    lines = []
    for source_line in text.splitlines() or [""]:
        current = ""
        for char in source_line:
            candidate = current + char
            runs = list(split_mixed_font_runs(candidate, style.cjk_font, style.latin_font, font_rules))
            if current and text_width(draw, runs, fonts) > max_width:
                lines.append(current.rstrip())
                current = char
            else:
                current = candidate
        if current:
            lines.append(current.rstrip())
    return lines or [""]


def draw_mixed_text(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    text: str,
    fonts: dict[str, ImageFont.ImageFont],
    fill: tuple[int, int, int, int],
    stroke_fill: tuple[int, int, int, int],
    stroke_width: int,
    style: CaptionStyle,
    font_rules: list[FontRule] | None = None,
) -> None:
    x, y = position
    for font_name, value in split_mixed_font_runs(text, style.cjk_font, style.latin_font, font_rules):
        font = fonts.get(font_name or "", fonts["latin"])
        draw.text((x, y), value, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
        bbox = draw.textbbox((0, 0), value, font=font, stroke_width=stroke_width)
        x += bbox[2] - bbox[0]


def aligned_box_position(size: tuple[int, int], box_size: tuple[int, int], style: CaptionStyle) -> tuple[int, int]:
    width, height = size
    box_width, box_height = box_size
    column = (style.alignment - 1) % 3
    row = (style.alignment - 1) // 3

    if column == 0:
        box_left = style.margin_l
    elif column == 2:
        box_left = width - style.margin_r - box_width
    else:
        box_left = (width - box_width) // 2

    if row == 0:
        box_top = height - style.margin_v - box_height
    elif row == 2:
        box_top = style.margin_v
    else:
        box_top = (height - box_height) // 2

    max_left = max(0, width - box_width)
    max_top = max(0, height - box_height)
    return max(0, min(box_left, max_left)), max(0, min(box_top, max_top))


def render_frame(
    size: tuple[int, int],
    texts: list[str],
    style: CaptionStyle,
    fonts: dict[str, ImageFont.ImageFont],
    font_rules: list[FontRule] | None = None,
) -> Image.Image:
    width, height = size
    frame = Image.new("RGBA", size, (0, 0, 0, 0))
    if not texts:
        return frame

    draw = ImageDraw.Draw(frame)
    max_text_width = max(1, width - style.margin_l - style.margin_r - style.padding_h * 2)
    lines = []
    for text in texts:
        lines.extend(wrap_text(text, draw, fonts, max_text_width, style, font_rules))

    line_metrics = []
    content_width = 0
    content_height = 0
    for line in lines:
        runs = list(split_mixed_font_runs(line, style.cjk_font, style.latin_font, font_rules))
        line_width = text_width(draw, runs, fonts)
        line_height = max(
            draw.textbbox((0, 0), line or " ", font=fonts["latin"], stroke_width=math.ceil(style.outline))[3],
            style.font_size,
        )
        line_metrics.append((line, line_width, line_height))
        content_width = max(content_width, line_width)
        content_height += line_height
    content_height += style.line_spacing * max(0, len(line_metrics) - 1)

    box_width = content_width + style.padding_h * 2
    box_height = content_height + style.padding_v * 2
    box_left, box_top = aligned_box_position(size, (box_width, box_height), style)

    bg = rgba(style.background_color, style.background_alpha)
    if style.background_alpha < 255:
        draw.rounded_rectangle(
            (box_left, box_top, box_left + box_width, box_top + box_height),
            radius=style.corner_radius,
            fill=bg,
        )

    text_fill = rgba(style.primary_color, style.primary_alpha)
    stroke_fill = rgba(style.outline_color, style.outline_alpha)
    y = box_top + style.padding_v
    for line, line_width, line_height in line_metrics:
        x = box_left + (box_width - line_width) // 2
        draw_mixed_text(draw, (x, y), line, fonts, text_fill, stroke_fill, max(0, round(style.outline)), style, font_rules)
        y += line_height + style.line_spacing

    return frame


def render_fonts(
    style: CaptionStyle,
    font_sources: FontSources,
    font_rules: list[FontRule] | None = None,
) -> dict[str, ImageFont.ImageFont]:
    fonts = {
        style.cjk_font: load_font(style.cjk_font, style.font_size, font_sources.cjk_font_file),
        style.latin_font: load_font(style.latin_font, style.font_size, font_sources.latin_font_file),
    }
    for rule in font_rules or []:
        if rule.font not in fonts:
            fonts[rule.font] = load_font(rule.font, style.font_size)
    fonts["cjk"] = fonts[style.cjk_font]
    fonts["latin"] = fonts[style.latin_font]
    return fonts


def save_preview_frame(frame: Image.Image, output: Path) -> None:
    if output.suffix.lower() in {".jpg", ".jpeg"} and frame.mode == "RGBA":
        background = Image.new("RGB", frame.size, (24, 24, 24))
        background.paste(frame, mask=frame.getchannel("A"))
        background.save(output)
        return
    frame.save(output)


def is_hdr_color_info(color_info: dict[str, str | None]) -> bool:
    return color_info.get("color_transfer") in HDR_TRANSFERS


def resolve_preview_format(preview_format: str, color_info: dict[str, str | None]) -> str:
    normalized = preview_format.lower()
    if normalized not in PREVIEW_FORMATS:
        raise ValueError(f"--preview-format must be one of {', '.join(sorted(PREVIEW_FORMATS))}")
    if normalized == "auto":
        return "avif" if is_hdr_color_info(color_info) else "png"
    return "jpg" if normalized == "jpeg" else normalized


def preview_output_path(output: Path, preview_format: str) -> Path:
    suffix = ".jpg" if preview_format == "jpg" else f".{preview_format}"
    return output.with_suffix(suffix)


def fallback_preview_path(output: Path) -> Path:
    if output.suffix.lower() == ".png":
        return output
    return output.with_suffix(".png")


def preview_codec_args(preview_format: str, ffmpeg: str | None = None) -> list[str]:
    encoders = available_encoders(ffmpeg)
    if preview_format == "jxl":
        if "libjxl" not in encoders:
            raise RuntimeError("JXL preview requires an ffmpeg build with the libjxl encoder")
        return ["-c:v", "libjxl"]

    if preview_format == "avif":
        for encoder in ("libaom-av1", "libsvtav1", "librav1e"):
            if encoder in encoders:
                args = ["-c:v", encoder]
                if encoder == "libaom-av1":
                    args.extend(["-crf", "18", "-b:v", "0"])
                elif encoder == "libsvtav1":
                    args.extend(["-crf", "18"])
                return args
        raise RuntimeError("AVIF preview requires an ffmpeg build with an AV1 encoder such as libaom-av1 or libsvtav1")

    raise ValueError(f"Unsupported HDR preview format: {preview_format}")


def extract_video_frame(video: Path, timestamp: float, size: tuple[int, int], ffmpeg: str | None = None) -> Image.Image:
    with tempfile.TemporaryDirectory(prefix="captionforge-preview-") as tmp_dir:
        frame_path = Path(tmp_dir) / "frame.png"
        cmd = [
            ffmpeg or ffmpeg_path(),
            "-y",
            "-hide_banner",
            "-loglevel", "error",
            "-ss", f"{max(0.0, timestamp):.3f}",
            "-i", str(video),
            "-frames:v", "1",
            "-vf", f"scale={size[0]}:{size[1]}:flags=lanczos",
            str(frame_path),
        ]
        subprocess.run(cmd, check=True)
        return Image.open(frame_path).convert("RGBA")


def save_hdr_composited_preview(
    video: Path,
    timestamp: float,
    overlay: Image.Image,
    output: Path,
    preview_format: str,
    color_info: dict[str, str | None],
    ffmpeg: str | None = None,
) -> None:
    with tempfile.TemporaryDirectory(prefix="captionforge-preview-") as tmp_dir:
        overlay_path = Path(tmp_dir) / "overlay.png"
        overlay.save(overlay_path, "PNG")
        width, height = overlay.size
        pix_fmt = "rgb48le" if preview_format == "jxl" else "yuv420p10le"
        filter_complex = (
            f"[0:v]scale={width}:{height}:flags=lanczos[base];"
            f"[base][1:v]overlay=0:0:format=auto,format=pix_fmts={pix_fmt}[v]"
        )
        color_option_map = {
            "color_primaries": "-color_primaries",
            "color_transfer": "-color_trc",
            "color_space": "-colorspace",
        }
        binary = ffmpeg or ffmpeg_path()
        codec_args = preview_codec_args(preview_format, binary)
        cmd = [
            binary,
            "-y",
            "-hide_banner",
            "-loglevel", "error",
            "-ss", f"{max(0.0, timestamp):.3f}",
            "-i", str(video),
            "-i", str(overlay_path),
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-frames:v", "1",
            *codec_args,
        ]
        for key, value in color_info.items():
            if value:
                cmd.extend([color_option_map[key], value])
        cmd.append(str(output))
        subprocess.run(cmd, check=True)


def save_composited_preview(
    video: Path,
    timestamp: float,
    overlay: Image.Image,
    output: Path,
    ffmpeg: str | None = None,
    preview_format: str = "png",
    color_info: dict[str, str | None] | None = None,
) -> Path:
    color_info = color_info or {}
    if preview_format in {"avif", "jxl"}:
        try:
            save_hdr_composited_preview(video, timestamp, overlay, output, preview_format, color_info, ffmpeg)
            return output
        except (RuntimeError, subprocess.CalledProcessError) as exc:
            fallback = fallback_preview_path(output)
            print(f"[CaptionForge] {preview_format.upper()} preview failed; writing PNG fallback: {fallback} ({exc})", flush=True)
            base = extract_video_frame(video, timestamp, overlay.size, ffmpeg)
            base.alpha_composite(overlay)
            save_preview_frame(base, fallback)
            return fallback
    base = extract_video_frame(video, timestamp, overlay.size, ffmpeg)
    base.alpha_composite(overlay)
    save_preview_frame(base, output)
    return output


def _build_segments(events: list[tuple[float, float, int, str]], duration: float) -> list[tuple[float, float, list[str]]]:
    """Build non-overlapping segments with deduplicated texts."""
    # Keep overlapping tracks deterministic before building segment boundaries.
    sorted_events = sorted(events, key=lambda x: (x[0], x[2]))
    # Segment boundaries are every subtitle start/end plus the video bounds.
    points: set[float] = {0.0, duration}
    for start, end, _, _ in sorted_events:
        points.add(start)
        points.add(end)
    points = {p for p in points if 0 <= p <= duration}
    sorted_points = sorted(points)

    segments: list[tuple[float, float, list[str]]] = []
    for i in range(len(sorted_points) - 1):
        seg_start = sorted_points[i]
        seg_end = sorted_points[i + 1]
        if seg_start >= seg_end:
            continue
        mid = (seg_start + seg_end) / 2
        active_texts = [text for s, e, _, text in sorted_events if s <= mid < e and text]
        segments.append((seg_start, seg_end, active_texts))
    return segments


def rounded_subtitles(
    video: Path,
    subtitle: Path | list[Path],
    output: Path,
    style: CaptionStyle,
    quality: str,
    font_sources: FontSources | None = None,
    fps: int | None = None,
    reference_height: int = 1080,
    verbose: bool = False,
    extra_args: list[str] | None = None,
    encoder: str | None = None,
    codec: str = "h264",
    output_res: tuple[int, int] | None = None,
    preview_image: Path | None = None,
    preview_only: bool = False,
    preview_format: str = "auto",
    font_rules: list[FontRule] | None = None,
) -> None:
    source_width, source_height = probe_video_size(video)
    width, height = output_res or (source_width, source_height)
    duration = probe_duration(video)
    overlay_fps = fps if fps is not None else probe_fps(video)
    if overlay_fps <= 0:
        raise ValueError("--rounded-fps must be positive")
    scaled = scaled_style(style, height / reference_height)
    font_sources = font_sources or FontSources()
    fonts = render_fonts(scaled, font_sources, font_rules)
    subtitle_paths = subtitle if isinstance(subtitle, list) else [subtitle]
    events = []
    for track_index, subtitle_path in enumerate(subtitle_paths):
        subs = load_subtitles(subtitle_path)
        events.extend((event.start / 1000, event.end / 1000, track_index, plain_text(event.text)) for event in subs.events)
    segments = _build_segments(events, duration)

    ffmpeg = ffmpeg_path()
    color_info = probe_color_info(video)

    # HDR subtitles need lower SDR RGB values to avoid excessive brightness.
    transfer = color_info.get("color_transfer")
    if transfer == "smpte2084":  # PQ
        scaled = replace(
            scaled,
            primary_color=_adjust_hdr_color(scaled.primary_color, 0.50),
            outline_color=_adjust_hdr_color(scaled.outline_color, 0.50),
        )
    elif transfer == "arib-std-b67":  # HLG
        scaled = replace(
            scaled,
            primary_color=_adjust_hdr_color(scaled.primary_color, 0.75),
            outline_color=_adjust_hdr_color(scaled.outline_color, 0.75),
        )

    if preview_image:
        selected_preview_format = resolve_preview_format(preview_format, color_info)
        preview_image = preview_output_path(preview_image, selected_preview_format)
        preview_segment = next((segment for segment in segments if segment[2]), segments[0] if segments else (0.0, 0.0, []))
        preview_image.parent.mkdir(parents=True, exist_ok=True)
        preview_time = preview_segment[0] + max(0.0, preview_segment[1] - preview_segment[0]) / 2
        overlay = render_frame((width, height), preview_segment[2], scaled, fonts, font_rules)
        written_preview = save_composited_preview(video, preview_time, overlay, preview_image, ffmpeg, selected_preview_format, color_info)
        print(f"[CaptionForge] Preview image: {written_preview}", flush=True)
        if preview_only:
            return

    output.parent.mkdir(parents=True, exist_ok=True)

    pix_fmt = probe_pix_fmt(video)

    with tempfile.TemporaryDirectory(prefix="captionforge-rounded-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        concat_txt = tmp_path / "concat.txt"
        overlay_mkv = tmp_path / "overlay.mkv"

        def _render_task(idx: int, seg_start: float, seg_end: float, texts: list[str]) -> tuple[int, tuple[str, ...], Path]:
            text_key = tuple(texts)
            with seen_lock:
                frame_path = seen_frames.get(text_key)
            if frame_path is None:
                candidate_path = tmp_path / f"frame_{idx:05d}.png"
                frame = render_frame((width, height), texts, scaled, fonts, font_rules)
                frame.save(candidate_path, "PNG")
                with seen_lock:
                    frame_path = seen_frames.setdefault(text_key, candidate_path)
            return idx, text_key, frame_path

        seen_frames: dict[tuple[str, ...], Path] = {}
        seen_lock = threading.Lock()
        total = len(segments)
        t0 = time.time()

        with ThreadPoolExecutor(max_workers=min(os.cpu_count() or 4, 8)) as executor:
            futures = [
                executor.submit(_render_task, idx, seg_start, seg_end, texts)
                for idx, (seg_start, seg_end, texts) in enumerate(segments)
            ]
            for future_idx, future in enumerate(futures):
                idx, text_key, frame_path = future.result()
                seg_start, seg_end, _ = segments[idx]
                seg_dur = seg_end - seg_start
                # Preserve segment order because the concat demuxer is order-sensitive.
                if not verbose and total > 1 and (future_idx + 1) % max(1, total // 100) == 0 or future_idx == total - 1:
                    pct = (future_idx + 1) / total * 100
                    elapsed = time.time() - t0
                    eta = elapsed / max(future_idx + 1, 1) * (total - future_idx - 1)
                    print(
                        f"\r[CaptionForge] Rendering subtitle frames: {future_idx + 1}/{total} ({pct:.1f}%) | ETA {int(eta // 60)}m {int(eta % 60)}s",
                        end="",
                        flush=True,
                    )

        if not verbose and total > 1:
            print()

        with concat_txt.open("w", encoding="utf-8") as cf:
            for idx, (seg_start, seg_end, texts) in enumerate(segments):
                frame_path = seen_frames[tuple(texts)]
                cf.write(f"file '{frame_path.as_posix()}'\n")
                cf.write(f"duration {seg_end - seg_start:.6f}\n")
            if segments:
                last_frame = seen_frames[tuple(segments[-1][2])]
                cf.write(f"file '{last_frame.as_posix()}'\n")

        # Build a VFR overlay so static subtitle states are encoded only once.
        overlay_cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel", "info" if verbose else "error",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_txt),
            "-vsync", "vfr",
            "-c:v", "ffv1",
            "-pix_fmt", "bgra",
            str(overlay_mkv),
        ]
        if not verbose:
            print("[CaptionForge] ffmpeg: building VFR overlay video...")
        subprocess.run(overlay_cmd, check=True)

        # Composite the overlay video onto the source frames.
        if output_res:
            filter_complex = f"[0:v]scale={width}:{height}:flags=lanczos[base];[base][1:v]overlay=0:0:format=auto"
        else:
            filter_complex = "[0:v][1:v]overlay=0:0:format=auto"
        if pix_fmt:
            filter_complex += f",format=pix_fmts={pix_fmt}"
        filter_complex += "[v]"

        color_option_map = {
            "color_primaries": "-color_primaries",
            "color_transfer": "-color_trc",
            "color_space": "-colorspace",
        }

        selected_encoder = select_encoder(encoder, codec, ffmpeg)
        fallback_encoder = select_encoder("cpu", codec, ffmpeg) if encoder in {None, "auto"} and selected_encoder.endswith("_videotoolbox") else None

        def build_burn_cmd(active_encoder: str) -> list[str]:
            cmd = [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel", "info" if verbose else "error",
                "-progress", "pipe:1",
                "-i", str(video),
                "-i", str(overlay_mkv),
                "-filter_complex", filter_complex,
                "-map", "[v]",
                "-map", "0:a?",
                "-c:a", "copy",
                *encode_args(output, quality, active_encoder),
                "-shortest",
            ]
            for key, value in color_info.items():
                if value:
                    cmd.extend([color_option_map[key], value])
            if extra_args:
                cmd.extend(extra_args)
            cmd.append(str(output))
            return cmd

        def run_burn_cmd(active_encoder: str) -> None:
            burn_cmd = build_burn_cmd(active_encoder)
            if verbose:
                subprocess.run(burn_cmd, check=True)
                return
            print("[CaptionForge] ffmpeg: burning final video...")
            process = subprocess.Popen(
                burn_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            assert process.stdout is not None
            start_enc = time.time()
            last_pct = -1.0
            while True:
                line = process.stdout.readline()
                if not line:
                    if process.poll() is not None:
                        break
                    continue
                line = line.strip()
                if line.startswith("out_time_ms="):
                    try:
                        # ffmpeg reports out_time_ms in microseconds despite the field name.
                        us = int(line.split("=", 1)[1])
                        elapsed_vid = us / 1_000_000
                        pct = min(100.0, elapsed_vid / max(duration, 0.001) * 100)
                        if pct <= last_pct:
                            continue
                        last_pct = pct
                        elapsed = time.time() - start_enc
                        eta = elapsed / max(pct, 0.1) * (100 - pct) if pct > 0 else 0
                        print(
                            f"\r[CaptionForge] Encoding: {pct:.1f}% | time={elapsed_vid:.1f}s / {duration:.1f}s | ETA {int(eta // 60)}m {int(eta % 60)}s",
                            end="",
                            flush=True,
                        )
                    except Exception:
                        pass
            print()
            if process.wait() != 0:
                raise subprocess.CalledProcessError(process.returncode, burn_cmd)

        try:
            run_burn_cmd(selected_encoder)
        except subprocess.CalledProcessError:
            if not fallback_encoder or fallback_encoder == selected_encoder:
                raise
            print(f"[CaptionForge] Encoder {selected_encoder} failed; retrying with {fallback_encoder}.", flush=True)
            run_burn_cmd(fallback_encoder)
