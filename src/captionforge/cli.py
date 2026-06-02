from __future__ import annotations

from argparse import ArgumentParser, Namespace
from contextlib import contextmanager
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from .ffmpeg import (
    ENCODER_CHOICES,
    QUALITY_PRESETS,
    available_filters,
    burn_subtitles,
    ffmpeg_path,
    ffprobe_path,
    probe_video_codec,
    probe_video_size,
    select_encoder,
    soft_subtitles,
    transcode_video,
)
from .fonts import default_font, list_fonts, match_font, match_font_exact, search_fonts
from .fontsplit import FontRule, font_rule_from_dict
from .rounded import FontSources, rounded_subtitles
from .styles import CaptionStyle, apply_style_override, font_family_name, font_names
from .subtitles import write_ass, write_multi_ass
from .templates import BUILTIN_TEMPLATES, load_template, style_from_template, template_json, template_names


VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi"}
SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt", ".sub"}
FONT_EXTENSIONS = {".ttf", ".ttc", ".otf", ".otc"}
CODEC_CHOICES = ["auto", "h264", "hevc", "av1", "vvc", "h266"]
DEFAULT_SUBTITLE_TAGS = ["zh", "zh-cn", "zh-hans", "zh-hant", "cn", "chs", "cht"]
LANG_SEPARATORS = ".-_ "
FIELD_RE = re.compile(r"[._\-\s]+")


@dataclass(frozen=True)
class SubtitleCandidate:
    path: Path
    key: str
    score: tuple[int, int, str]


@dataclass(frozen=True)
class BatchMatch:
    video: Path
    subtitles: list[Path]


@dataclass(frozen=True)
class BatchOutput:
    video: Path
    subtitles: list[Path]
    output: Path


class AmbiguousSubtitleError(ValueError):
    def __init__(self, ambiguous: dict[Path, list[SubtitleCandidate]]):
        self.ambiguous = ambiguous
        lines = ["Multiple subtitle candidates found. Choose with repeated --subtitle, for example --subtitle en --subtitle zh:"]
        for video, candidates in ambiguous.items():
            lines.append(f"{video}:")
            for candidate in candidates:
                lines.append(f"  {candidate.key}\t{candidate.path}")
        super().__init__("\n".join(lines))


def style_from_args(args: Namespace) -> CaptionStyle:
    font_dirs = list(getattr(args, "font_dir", []) or [])
    style = CaptionStyle(cjk_font=default_font("cjk", font_dirs), latin_font=default_font("latin", font_dirs))
    if getattr(args, "template", None):
        style = style_from_template(args.template, style)

    overrides = {}
    for arg_name, field_name in (
        ("cjk_font", "cjk_font"),
        ("latin_font", "latin_font"),
        ("font_size", "font_size"),
        ("primary_color", "primary_color"),
        ("outline_color", "outline_color"),
        ("background_color", "background_color"),
        ("primary_alpha", "primary_alpha"),
        ("outline_alpha", "outline_alpha"),
        ("background_alpha", "background_alpha"),
        ("outline", "outline"),
        ("shadow", "shadow"),
        ("margin_v", "margin_v"),
        ("margin_l", "margin_l"),
        ("margin_r", "margin_r"),
        ("alignment", "alignment"),
        ("box", "boxed"),
        ("corner_radius", "corner_radius"),
        ("padding_h", "padding_h"),
        ("padding_v", "padding_v"),
        ("line_spacing", "line_spacing"),
    ):
        value = getattr(args, arg_name, None)
        if value is not None:
            overrides[field_name] = value

    if "cjk_font" not in overrides:
        overrides["cjk_font"] = font_name_from_file(args.cjk_font_file, getattr(args, "cjk_font_name_source", "family")) if getattr(args, "cjk_font_file", None) else style.cjk_font
    if "latin_font" not in overrides:
        overrides["latin_font"] = font_name_from_file(args.latin_font_file, getattr(args, "latin_font_name_source", "family")) if getattr(args, "latin_font_file", None) else style.latin_font

    if overrides:
        style = apply_style_override(style, overrides)
    if getattr(args, "style_override", None):
        override = json.loads(args.style_override)
        if not isinstance(override, dict):
            raise ValueError("--style-override must be a JSON object")
        style = apply_style_override(style, override)
    return style


def font_name_from_file(path: Path, source: str) -> str:
    if source == "family":
        return font_family_name(path)
    return font_names(path).selected(source)


def format_font_record(record) -> str:
    return "\t".join(
        [
            record.family,
            record.full_name or "",
            record.postscript_name or "",
            str(record.path),
            record.source,
        ]
    )


def print_selected_default_fonts(args: Namespace, style: CaptionStyle) -> None:
    if getattr(args, "cjk_font", None) or getattr(args, "cjk_font_file", None):
        cjk = None
    else:
        cjk = style.cjk_font
    if getattr(args, "latin_font", None) or getattr(args, "latin_font_file", None):
        latin = None
    else:
        latin = style.latin_font

    if cjk or latin:
        parts = []
        if latin:
            parts.append(f"Latin={latin}")
        if cjk:
            parts.append(f"CJK={cjk}")
        print(f"[CaptionForge] Selected default fonts: {', '.join(parts)}", file=sys.stderr)


def print_selected_font_faces(args: Namespace, style: CaptionStyle) -> None:
    font_dirs = font_dirs_from_args(args)
    parts = []
    for role, selected in (("Latin", style.latin_font), ("CJK", style.cjk_font)):
        record = match_font(selected, font_dirs)
        if not record:
            parts.append(f"{role}={selected} (unmatched)")
            continue
        details = [f"{role}={selected}"]
        if record.full_name:
            details.append(f"full={record.full_name}")
        if record.postscript_name:
            details.append(f"postscript={record.postscript_name}")
        details.append(f"file={record.path}")
        parts.append(f"{details[0]} ({', '.join(details[1:])})")
    print(f"[CaptionForge] Font faces: {', '.join(parts)}", file=sys.stderr)


def validate_explicit_fonts(args: Namespace, style: CaptionStyle) -> None:
    font_dirs = font_dirs_from_args(args)
    for role, selected, explicit_name, explicit_file in (
        ("Latin", style.latin_font, getattr(args, "latin_font", None), getattr(args, "latin_font_file", None)),
        ("CJK", style.cjk_font, getattr(args, "cjk_font", None), getattr(args, "cjk_font_file", None)),
    ):
        if (explicit_name or explicit_file) and not match_font_exact(selected, font_dirs):
            raise ValueError(f"{role} font did not exactly match an installed or provided font family, full name, or PostScript name: {selected}")


def load_font_rules(args: Namespace) -> list[FontRule]:
    rules: list[FontRule] = []
    for value in getattr(args, "font_rule", []) or []:
        data = json.loads(value)
        if not isinstance(data, dict):
            raise ValueError("--font-rule must be a JSON object")
        rules.append(font_rule_from_dict(data))

    rules_path = getattr(args, "font_rules", None)
    if rules_path:
        data = json.loads(rules_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("rules")
        if not isinstance(data, list):
            raise ValueError("--font-rules must contain a JSON array or an object with a 'rules' array")
        for item in data:
            if not isinstance(item, dict):
                raise ValueError("Every font rule must be a JSON object")
            rules.append(font_rule_from_dict(item))
    return rules


def font_dirs_from_args(args: Namespace) -> list[Path]:
    dirs = list(getattr(args, "font_dir", []) or [])
    for font_file in (getattr(args, "cjk_font_file", None), getattr(args, "latin_font_file", None)):
        if font_file:
            dirs.append(font_file.parent)
    result = []
    seen = set()
    for path in dirs:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            result.append(resolved)
    return result


@contextmanager
def ass_font_dirs(args: Namespace):
    dirs = font_dirs_from_args(args)
    font_files = [
        font_file
        for font_file in (getattr(args, "cjk_font_file", None), getattr(args, "latin_font_file", None))
        if font_file
    ]
    if len(dirs) <= 1:
        yield dirs
        return

    with tempfile.TemporaryDirectory(prefix="captionforge-fonts-") as temp_dir:
        staged = Path(temp_dir)
        seen_names: set[str] = set()

        def stage_font(font_file: Path) -> None:
            nonlocal seen_names
            if not font_file.is_file() or font_file.suffix.lower() not in FONT_EXTENSIONS:
                return
            target_name = font_file.name
            if target_name in seen_names:
                target_name = f"{len(seen_names)}-{target_name}"
            seen_names.add(target_name)
            target = staged / target_name
            try:
                target.symlink_to(font_file.resolve())
            except OSError:
                shutil.copy2(font_file, target)

        for directory in dirs:
            if directory.is_dir():
                for font_file in directory.rglob("*"):
                    stage_font(font_file)
        for font_file in font_files:
            stage_font(font_file)
        yield [staged] if seen_names else dirs[:1]


def parse_play_res(value: str) -> tuple[int, int]:
    try:
        width, height = value.lower().split("x", 1)
        parsed = int(width), int(height)
    except ValueError as exc:
        raise ValueError("--play-res must be formatted like 1920x1080") from exc
    if parsed[0] <= 0 or parsed[1] <= 0:
        raise ValueError("--play-res dimensions must be positive")
    return parsed


def parse_resolution(value: str, option_name: str = "--output-res") -> tuple[int, int]:
    try:
        width, height = value.lower().split("x", 1)
        parsed = int(width), int(height)
    except ValueError as exc:
        raise ValueError(f"{option_name} must be formatted like 3840x2160") from exc
    if parsed[0] <= 0 or parsed[1] <= 0:
        raise ValueError(f"{option_name} dimensions must be positive")
    return parsed


def resolve_codec(video: Path, requested: str) -> str:
    if requested == "auto":
        return probe_video_codec(video)
    if requested == "h266":
        return "vvc"
    return requested


def normalize_subtitle_tag(value: str) -> str:
    return value.lower().strip().strip(".-_ ").replace("_", "-").replace(".", "-").replace(" ", "-")


def subtitle_match_score(video_stem: str, subtitle_stem: str, tags: list[str]) -> tuple[int, int] | None:
    video_key = video_stem.lower()
    subtitle_key = subtitle_stem.lower()
    if subtitle_key == video_key:
        return 0, 0

    normalized_tags = {normalize_subtitle_tag(tag) for tag in tags}
    if subtitle_key.startswith(video_key) and len(subtitle_key) > len(video_key):
        separator = subtitle_key[len(video_key)]
        tag = subtitle_key[len(video_key) + 1 :]
        if separator in LANG_SEPARATORS and normalize_subtitle_tag(tag) in normalized_tags:
            return 1, len(tag)

    if subtitle_key.endswith(video_key) and len(subtitle_key) > len(video_key):
        separator = subtitle_key[-len(video_key) - 1]
        tag = subtitle_key[: -len(video_key) - 1]
        if separator in LANG_SEPARATORS and normalize_subtitle_tag(tag) in normalized_tags:
            return 2, len(tag)

    return None


def split_fields(value: str) -> list[str]:
    return [field for field in FIELD_RE.split(value.lower().strip()) if field]


def subtitle_key_for_video(video: Path, subtitle: Path, sibling_video_count: int) -> tuple[str, tuple[int, int, str]] | None:
    video_stem = video.stem.lower()
    subtitle_stem = subtitle.stem.lower()
    if subtitle_stem == video_stem:
        return "default", (0, 0, subtitle.name)

    for separator in LANG_SEPARATORS:
        prefix = f"{video_stem}{separator}"
        suffix = f"{separator}{video_stem}"
        if subtitle_stem.startswith(prefix):
            key = normalize_subtitle_tag(subtitle_stem[len(prefix) :])
            if key:
                return key, (1, len(key), subtitle.name)
        if subtitle_stem.endswith(suffix):
            key = normalize_subtitle_tag(subtitle_stem[: -len(suffix)])
            if key:
                return key, (2, len(key), subtitle.name)

    if subtitle_stem.startswith(video_stem) and len(subtitle_stem) > len(video_stem):
        key = normalize_subtitle_tag(subtitle_stem[len(video_stem) :])
        if key:
            return key, (3, len(key), subtitle.name)

    if subtitle_stem.endswith(video_stem) and len(subtitle_stem) > len(video_stem):
        key = normalize_subtitle_tag(subtitle_stem[: -len(video_stem)])
        if key:
            return key, (4, len(key), subtitle.name)

    fields = split_fields(subtitle_stem)
    video_key = normalize_subtitle_tag(video_stem)
    normalized_fields = [normalize_subtitle_tag(field) for field in fields]
    if video_key in normalized_fields:
        key_fields = [field for field in normalized_fields if field != video_key]
        key = "-".join(key_fields) or "default"
        return key, (5, len(key), subtitle.name)

    if sibling_video_count == 1 and fields:
        return normalize_subtitle_tag(subtitle_stem), (6, len(subtitle_stem), subtitle.name)

    return None


def subtitle_candidates_for_video(video: Path, subtitles: list[Path], sibling_video_count: int) -> list[SubtitleCandidate]:
    candidates = []
    for subtitle in subtitles:
        key_score = subtitle_key_for_video(video, subtitle, sibling_video_count)
        if key_score:
            key, score = key_score
            candidates.append(SubtitleCandidate(subtitle, key, score))
    return sorted(candidates, key=lambda candidate: candidate.score)


def select_subtitles(candidates: list[SubtitleCandidate], selectors: list[str]) -> list[Path]:
    if selectors == ["auto"]:
        return [candidates[0].path] if len(candidates) == 1 else []

    selected = []
    for selector in selectors:
        selector_key = normalize_subtitle_tag(selector)
        selector_path = Path(selector)
        matches = [
            candidate
            for candidate in candidates
            if candidate.key == selector_key
            or candidate.path.name.lower() == selector.lower()
            or candidate.path.stem.lower() == selector.lower()
            or candidate.path == selector_path
        ]
        if not matches:
            raise ValueError(f"No subtitle candidate matched selector: {selector}")
        selected.append(matches[0].path)
    return selected


def find_batch_matches(
    input_dir: Path,
    selectors: list[str],
    recursive: bool = False,
    resolver: object | None = None,
) -> list[BatchMatch]:
    pattern = "**/*" if recursive else "*"
    files = [path for path in input_dir.glob(pattern) if path.is_file()]
    videos = sorted(path for path in files if path.suffix.lower() in VIDEO_EXTENSIONS)
    subtitles = sorted(path for path in files if path.suffix.lower() in SUBTITLE_EXTENSIONS)
    matches = []
    ambiguous = {}
    for video in videos:
        sibling_videos = [candidate for candidate in videos if candidate.parent == video.parent]
        sibling_subtitles = [candidate for candidate in subtitles if candidate.parent == video.parent]
        candidates = subtitle_candidates_for_video(video, sibling_subtitles, len(sibling_videos))
        if not candidates:
            continue
        if selectors == ["auto"] and len(candidates) > 1:
            if resolver:
                selected = resolver(video, candidates)
                if selected:
                    matches.append(BatchMatch(video, selected))
                continue
            ambiguous[video] = candidates
            continue
        selected = select_subtitles(candidates, selectors)
        if selected:
            matches.append(BatchMatch(video, selected))
    if ambiguous:
        raise AmbiguousSubtitleError(ambiguous)
    return matches


def find_batch_pairs(input_dir: Path, tags: list[str], recursive: bool = False) -> list[tuple[Path, Path]]:
    pattern = "**/*" if recursive else "*"
    files = [path for path in input_dir.glob(pattern) if path.is_file()]
    videos = sorted(path for path in files if path.suffix.lower() in VIDEO_EXTENSIONS)
    subtitles = sorted(path for path in files if path.suffix.lower() in SUBTITLE_EXTENSIONS)
    normalized_tags = {normalize_subtitle_tag(tag) for tag in tags}
    pairs = []
    for video in videos:
        sibling_videos = [candidate for candidate in videos if candidate.parent == video.parent]
        sibling_subtitles = [candidate for candidate in subtitles if candidate.parent == video.parent]
        candidates = [
            candidate
            for candidate in subtitle_candidates_for_video(video, sibling_subtitles, len(sibling_videos))
            if candidate.key == "default" or candidate.key in normalized_tags
        ]
        if candidates:
            pairs.append((video, candidates[0].path))
    return pairs


def prompt_subtitle_selection(video: Path, candidates: list[SubtitleCandidate]) -> list[Path]:
    print(f"\nMultiple subtitle candidates for {video}:")
    for index, candidate in enumerate(candidates, 1):
        print(f"  {index}. {candidate.key}\t{candidate.path}")
    answer = input("Select subtitles by number or key, comma-separated; empty skips this video: ").strip()
    if not answer:
        return []

    selected = []
    for token in [part.strip() for part in answer.split(",") if part.strip()]:
        if token.isdigit():
            index = int(token)
            if not 1 <= index <= len(candidates):
                raise ValueError(f"Subtitle selection out of range for {video}: {token}")
            selected.append(candidates[index - 1].path)
        else:
            selected.extend(select_subtitles(candidates, [token]))
    return selected


def print_batch_plan(matches: list[BatchMatch], input_dir: Path, output_dir: Path, suffix: str) -> None:
    print("Batch plan:")
    for match in matches:
        output = batch_output_path(match.video, input_dir, output_dir, suffix)
        subtitles = ", ".join(str(path) for path in match.subtitles)
        print(f"{match.video}\t{subtitles}\t{output}")


def print_batch_output_plan(args: Namespace, matches: list[BatchMatch], input_dir: Path) -> None:
    print("Batch plan:")
    for output in batch_outputs_for_matches(args, matches, input_dir):
        subtitles = ", ".join(str(path) for path in output.subtitles)
        print(f"{output.video}\t{subtitles}\t{output.output}")


def confirm_batch_plan(matches: list[BatchMatch]) -> bool:
    answer = input(f"Proceed with {len(matches)} video(s)? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def subtitle_label_for_video(video: Path, subtitle: Path) -> str:
    key_score = subtitle_key_for_video(video, subtitle, 1)
    if not key_score:
        return normalize_subtitle_tag(subtitle.stem) or "subtitles"
    key, _ = key_score
    return "subtitles" if key == "default" else key


def subtitle_label_for_paths(video: Path, subtitles: list[Path]) -> str:
    return ".".join(subtitle_label_for_video(video, subtitle) for subtitle in subtitles)


def labeled_output_path(video: Path, input_dir: Path, output_dir: Path, suffix: str, label: str | None, label_position: str) -> Path:
    relative_parent = video.parent.relative_to(input_dir)
    stem = f"{video.stem}{suffix}"
    if label and label_position == "prefix":
        stem = f"{label}.{stem}"
    elif label and label_position == "suffix":
        stem = f"{stem}.{label}"
    return output_dir / relative_parent / f"{stem}{video.suffix}"


def batch_outputs_for_match(args: Namespace, match: BatchMatch, input_dir: Path) -> list[BatchOutput]:
    mode = getattr(args, "subtitle_outputs", "combined")
    label_position = getattr(args, "subtitle_label_position", "suffix")
    include_label = label_position != "none"
    outputs: list[BatchOutput] = []

    def make_output(subtitles: list[Path]) -> BatchOutput:
        label = subtitle_label_for_paths(match.video, subtitles) if include_label else None
        output = labeled_output_path(match.video, input_dir, args.output_dir, args.output_suffix, label, label_position)
        return BatchOutput(match.video, subtitles, output)

    if mode in {"separate", "both"}:
        outputs.extend(make_output([subtitle]) for subtitle in match.subtitles)
    if mode in {"combined", "both"}:
        outputs.append(make_output(match.subtitles))
    return outputs


def batch_outputs_for_matches(args: Namespace, matches: list[BatchMatch], input_dir: Path) -> list[BatchOutput]:
    outputs = []
    for match in matches:
        outputs.extend(batch_outputs_for_match(args, match, input_dir))
    paths = [output.output for output in outputs]
    duplicates = sorted({path for path in paths if paths.count(path) > 1})
    if duplicates:
        duplicate_text = ", ".join(str(path) for path in duplicates)
        raise ValueError(f"Batch output filenames collide: {duplicate_text}. Use subtitle labels or a different output suffix.")
    return outputs


def validate_batch_outputs(args: Namespace, outputs: list[BatchOutput]) -> None:
    if getattr(args, "mode", "hard") != "soft":
        return
    multi = [output for output in outputs if len(output.subtitles) != 1]
    if multi:
        raise ValueError("Soft subtitle batch mode supports one subtitle per output. Use --subtitle-outputs separate or --mode hard.")


def run_batch_jobs(
    args: Namespace,
    matches: list[BatchMatch],
    input_dir: Path,
    style: CaptionStyle,
    font_rules: list[FontRule] | None = None,
) -> None:
    jobs = max(1, getattr(args, "jobs", 1))
    outputs = batch_outputs_for_matches(args, matches, input_dir)
    validate_batch_outputs(args, outputs)
    total = len(outputs)

    def run_output(output: BatchOutput) -> Path:
        burn_one(args, output.video, output.subtitles, output.output, style, font_rules)
        return output.output

    if jobs == 1:
        for index, output_job in enumerate(outputs, 1):
            output = run_output(output_job)
            print(f"[CaptionForge] Batch progress: {index}/{total} complete\t{output}", flush=True)
        return

    with ThreadPoolExecutor(max_workers=jobs) as executor:
        future_to_output = {executor.submit(run_output, output): output for output in outputs}
        completed = 0
        for future in as_completed(future_to_output):
            output = future.result()
            completed += 1
            print(f"[CaptionForge] Batch progress: {completed}/{total} complete\t{output}", flush=True)


def batch_output_path(video: Path, input_dir: Path, output_dir: Path, suffix: str) -> Path:
    return labeled_output_path(video, input_dir, output_dir, suffix, None, "none")


def burn_one(
    args: Namespace,
    video: Path,
    subtitle: Path | list[Path],
    output: Path,
    style: CaptionStyle,
    font_rules: list[FontRule] | None = None,
) -> None:
    subtitles = subtitle if isinstance(subtitle, list) else [subtitle]
    if args.mode == "soft":
        if len(subtitles) != 1:
            raise ValueError("Soft subtitle mode supports one subtitle file at a time")
        soft_subtitles(video, subtitles[0], output, args.verbose_ffmpeg)
        return

    if args.render_mode == "rounded":
        output_res = parse_resolution(args.output_res) if getattr(args, "output_res", None) else None
        codec = resolve_codec(video, getattr(args, "codec", "auto"))
        rounded_subtitles(
            video,
            subtitles,
            output,
            style,
            args.quality,
            FontSources(args.cjk_font_file, args.latin_font_file),
            args.rounded_fps,
            args.reference_height,
            args.verbose_ffmpeg,
            args.ffmpeg_arg,
            args.encoder,
            codec,
            output_res,
            getattr(args, "preview_image", None),
            getattr(args, "preview_only", False),
            getattr(args, "preview_format", "auto"),
            font_rules,
        )
        return

    output_res = parse_resolution(args.output_res) if getattr(args, "output_res", None) else None
    play_res = output_res or probe_video_size(video)
    keep_ass = getattr(args, "keep_ass", None)
    ffmpeg = ffmpeg_path(require_subtitles=True)
    codec = resolve_codec(video, getattr(args, "codec", "auto"))
    encoder = select_encoder(args.encoder, codec, ffmpeg)
    fallback_encoder = select_encoder("cpu", codec, ffmpeg) if args.encoder == "auto" and encoder.endswith("_videotoolbox") else None
    with ass_font_dirs(args) as font_dirs:
        if keep_ass:
            ass_path = write_multi_ass(subtitles, keep_ass, style, play_res, args.reference_height, getattr(args, "multi_subtitle_layout", "stack"), font_rules)
            burn_subtitles(video, ass_path, output, args.ffmpeg_arg, args.quality, font_dirs, args.verbose_ffmpeg, encoder, ffmpeg, output_res, fallback_encoder)
            return

        with tempfile.TemporaryDirectory(prefix="captionforge-") as temp_dir:
            ass_path = write_multi_ass(subtitles, Path(temp_dir) / "captions.ass", style, play_res, args.reference_height, getattr(args, "multi_subtitle_layout", "stack"), font_rules)
            burn_subtitles(video, ass_path, output, args.ffmpeg_arg, args.quality, font_dirs, args.verbose_ffmpeg, encoder, ffmpeg, output_res, fallback_encoder)


def transcode_one(args: Namespace) -> None:
    ffmpeg = ffmpeg_path(require_subtitles=False)
    output_res = parse_resolution(args.output_res) if getattr(args, "output_res", None) else None
    codec = resolve_codec(args.video, args.codec)
    encoder = select_encoder(args.encoder, codec, ffmpeg)
    fallback_encoder = select_encoder("cpu", codec, ffmpeg) if args.encoder == "auto" and encoder.endswith("_videotoolbox") else None
    transcode_video(
        args.video,
        args.output,
        args.quality,
        args.verbose_ffmpeg,
        encoder,
        ffmpeg,
        output_res,
        args.ffmpeg_arg,
        fallback_encoder,
    )


def add_style_args(parser: ArgumentParser) -> None:
    parser.add_argument("--template", help="Built-in template name or path to a JSON template.")
    parser.add_argument("--cjk-font", help="Font used for Chinese/CJK characters.")
    parser.add_argument("--latin-font", help="Font used for Latin letters and digits.")
    parser.add_argument("--cjk-font-file", type=Path, help="TTF/OTF file used for Chinese/CJK characters.")
    parser.add_argument("--latin-font-file", type=Path, help="TTF/OTF file used for Latin letters and digits.")
    parser.add_argument("--cjk-font-name-source", choices=["family", "full", "postscript"], default="family", help="Name table field to use from --cjk-font-file. Defaults to family.")
    parser.add_argument("--latin-font-name-source", choices=["family", "full", "postscript"], default="family", help="Name table field to use from --latin-font-file. Defaults to family.")
    parser.add_argument("--font-dir", type=Path, action="append", default=[], help="Extra font directory for libass; repeat as needed.")
    parser.add_argument("--font-size", type=int)
    parser.add_argument("--primary-color")
    parser.add_argument("--outline-color")
    parser.add_argument("--background-color")
    parser.add_argument("--primary-alpha", type=int, help="0 opaque, 255 transparent.")
    parser.add_argument("--outline-alpha", type=int, help="0 opaque, 255 transparent.")
    parser.add_argument("--background-alpha", type=int, help="0 opaque, 255 transparent.")
    parser.add_argument("--outline", type=float)
    parser.add_argument("--shadow", type=float)
    parser.add_argument("--margin-v", type=int)
    parser.add_argument("--margin-l", type=int)
    parser.add_argument("--margin-r", type=int)
    parser.add_argument("--alignment", type=int, choices=range(1, 10))
    parser.add_argument("--box", action="store_true", default=None, help="Use ASS opaque-box mode. Combine with background alpha.")
    parser.add_argument("--corner-radius", type=int, help="Rounded render mode corner radius.")
    parser.add_argument("--padding-h", type=int, help="Rounded render mode horizontal padding.")
    parser.add_argument("--padding-v", type=int, help="Rounded render mode vertical padding.")
    parser.add_argument("--line-spacing", type=int, help="Rounded render mode line spacing.")
    parser.add_argument("--style-override", help="Inline JSON object overriding style fields.")
    parser.add_argument("--font-rule", action="append", default=[], help="JSON font override rule; repeat as needed. Fields: font, pattern, mode.")
    parser.add_argument("--font-rules", type=Path, help="JSON file containing font override rules.")
    parser.add_argument("--reference-height", type=int, default=1080, help="Reference height used when scaling ASS style to video size.")
    parser.add_argument("--output-res", help="Force output video resolution, formatted like 3840x2160. Defaults to the input video resolution.")


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(prog="captionforge", description="Burn multi-format subtitles into video.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ass_parser = subparsers.add_parser("ass", help="Convert a subtitle file to styled ASS.")
    ass_parser.add_argument("subtitle", type=Path)
    ass_parser.add_argument("-o", "--output", type=Path, required=True)
    ass_parser.add_argument("--play-res", help="Target ASS resolution, formatted like 1920x1080.")
    add_style_args(ass_parser)

    subparsers.add_parser("doctor", help="Check local ffmpeg and subtitle rendering support.")

    font_parser = subparsers.add_parser("font", help="List, search, or match installed fonts.")
    font_subparsers = font_parser.add_subparsers(dest="font_command", required=True)
    font_list = font_subparsers.add_parser("list", help="List installed fonts.")
    font_list.add_argument("--font-dir", type=Path, action="append", default=[], help="Extra font directory to scan.")
    font_list.add_argument("--limit", type=int, default=100, help="Maximum rows to print.")
    font_search = font_subparsers.add_parser("search", help="Search installed fonts by family or path.")
    font_search.add_argument("query")
    font_search.add_argument("--font-dir", type=Path, action="append", default=[], help="Extra font directory to scan.")
    font_search.add_argument("--limit", type=int, default=50, help="Maximum rows to print.")
    font_match = font_subparsers.add_parser("match", help="Show the file matched for a font family name.")
    font_match.add_argument("name")
    font_match.add_argument("--font-dir", type=Path, action="append", default=[], help="Extra font directory to scan.")

    template_parser = subparsers.add_parser("template", help="List, show, or export subtitle style templates.")
    template_subparsers = template_parser.add_subparsers(dest="template_command", required=True)
    template_subparsers.add_parser("list", help="List built-in templates.")
    template_show = template_subparsers.add_parser("show", help="Show a built-in template JSON.")
    template_show.add_argument("name", choices=template_names())
    template_export = template_subparsers.add_parser("export", help="Write a built-in template to a JSON file.")
    template_export.add_argument("name", choices=template_names())
    template_export.add_argument("-o", "--output", type=Path, required=True)

    burn_parser = subparsers.add_parser("burn", help="Add subtitles to a video.")
    burn_parser.add_argument("video", type=Path)
    burn_parser.add_argument("subtitle", type=Path, nargs="+")
    burn_parser.add_argument("-o", "--output", type=Path, required=True)
    burn_parser.add_argument("--mode", choices=["hard", "soft"], default="hard", help="hard burns subtitles into pixels; soft embeds a subtitle track.")
    burn_parser.add_argument("--render-mode", choices=["ass", "rounded"], default="ass", help="Hard-subtitle renderer.")
    burn_parser.add_argument("--multi-subtitle-layout", choices=["stack", "merge"], default="stack", help="For multiple ASS subtitles: stack separate lines or merge active text with line breaks.")
    burn_parser.add_argument("--quality", choices=QUALITY_PRESETS.keys(), default="medium", help="Encoding quality for hard mode.")
    burn_parser.add_argument("--encoder", choices=ENCODER_CHOICES, default="auto", help="Video encoder platform or exact ffmpeg encoder. auto picks VideoToolbox on macOS, then NVENC > QSV > AMF > CPU.")
    burn_parser.add_argument("--codec", choices=CODEC_CHOICES, default="auto", help="Output video codec. auto follows h264/hevc/av1/vvc input when possible; h266 is an alias for vvc.")
    burn_parser.add_argument("--rounded-fps", type=int, default=None, help="Overlay frame rate for rounded render mode. Defaults to video frame rate.")
    burn_parser.add_argument("--preview-image", type=Path, help="Write a rounded subtitle preview image before encoding.")
    burn_parser.add_argument("--preview-format", choices=["auto", "png", "jpg", "jpeg", "avif", "jxl"], default="auto", help="Preview image format. auto writes PNG for SDR and AVIF for HDR.")
    burn_parser.add_argument("--preview-only", action="store_true", help="Write --preview-image and exit before encoding.")
    burn_parser.add_argument("--keep-ass", type=Path, help="Also write the generated ASS file to this path.")
    burn_parser.add_argument("--ffmpeg-arg", action="append", default=[], help="Extra ffmpeg output argument; repeat as needed.")
    burn_parser.add_argument("--verbose-ffmpeg", action="store_true", help="Show ffmpeg progress and diagnostic logs.")
    add_style_args(burn_parser)

    transcode_parser = subparsers.add_parser("transcode", help="Convert video encoding without adding subtitles.")
    transcode_parser.add_argument("video", type=Path)
    transcode_parser.add_argument("-o", "--output", type=Path, required=True)
    transcode_parser.add_argument("--quality", choices=QUALITY_PRESETS.keys(), default="medium", help="Encoding quality. high keeps more detail; medium is smaller.")
    transcode_parser.add_argument("--encoder", choices=ENCODER_CHOICES, default="auto", help="Video encoder platform or exact ffmpeg encoder. auto picks VideoToolbox on macOS, then NVENC > QSV > AMF > CPU.")
    transcode_parser.add_argument("--codec", choices=CODEC_CHOICES, default="auto", help="Output video codec. Use hevc for H.265 or vvc/h266 for H.266.")
    transcode_parser.add_argument("--output-res", help="Force output video resolution, formatted like 3840x2160. Defaults to the input video resolution.")
    transcode_parser.add_argument("--ffmpeg-arg", action="append", default=[], help="Extra ffmpeg output argument; repeat as needed.")
    transcode_parser.add_argument("--verbose-ffmpeg", action="store_true", help="Show ffmpeg progress and diagnostic logs.")

    batch_parser = subparsers.add_parser("batch", help="Add matching subtitles to every video in a directory.")
    batch_parser.add_argument("input_dir", type=Path)
    batch_parser.add_argument("-o", "--output-dir", type=Path, required=True)
    batch_parser.add_argument("--recursive", action="store_true", help="Search subdirectories and preserve their layout under output-dir.")
    batch_parser.add_argument("--output-suffix", default="-captioned", help="Suffix added before the video extension.")
    batch_parser.add_argument("--subtitle-label-position", choices=["suffix", "prefix", "none"], default="suffix", help="Where to add subtitle labels in batch output filenames.")
    batch_parser.add_argument("--subtitle-outputs", choices=["combined", "separate", "both"], default="combined", help="For multiple selected subtitles, write one combined file, one file per subtitle, or both.")
    batch_parser.add_argument("--subtitle", action="append", default=None, help="Subtitle selector for each video. Use auto, a language key like en/zh-cn, or a filename; repeat to burn multiple.")
    batch_parser.add_argument("--subtitle-tag", action="append", default=[], help="Deprecated alias for --subtitle.")
    batch_parser.add_argument("--dry-run", action="store_true", help="Print matched input/output paths without running ffmpeg.")
    batch_parser.add_argument("--yes", action="store_true", help="Run without interactive confirmation.")
    batch_parser.add_argument("--jobs", type=int, default=1, help="Number of videos to process in parallel.")
    batch_parser.add_argument("--mode", choices=["hard", "soft"], default="hard", help="hard burns subtitles into pixels; soft embeds a subtitle track.")
    batch_parser.add_argument("--render-mode", choices=["ass", "rounded"], default="ass", help="Hard-subtitle renderer.")
    batch_parser.add_argument("--multi-subtitle-layout", choices=["stack", "merge"], default="stack", help="For multiple ASS subtitles: stack separate lines or merge active text with line breaks.")
    batch_parser.add_argument("--quality", choices=QUALITY_PRESETS.keys(), default="medium", help="Encoding quality for hard mode.")
    batch_parser.add_argument("--encoder", choices=ENCODER_CHOICES, default="auto", help="Video encoder platform or exact ffmpeg encoder. auto picks VideoToolbox on macOS, then NVENC > QSV > AMF > CPU.")
    batch_parser.add_argument("--codec", choices=CODEC_CHOICES, default="auto", help="Output video codec. auto follows h264/hevc/av1/vvc input when possible; h266 is an alias for vvc.")
    batch_parser.add_argument("--rounded-fps", type=int, default=None, help="Overlay frame rate for rounded render mode. Defaults to video frame rate.")
    batch_parser.add_argument("--preview-image", type=Path, help="Write a rounded subtitle preview image before encoding.")
    batch_parser.add_argument("--preview-format", choices=["auto", "png", "jpg", "jpeg", "avif", "jxl"], default="auto", help="Preview image format. auto writes PNG for SDR and AVIF for HDR.")
    batch_parser.add_argument("--preview-only", action="store_true", help="Write --preview-image and exit before encoding.")
    batch_parser.add_argument("--ffmpeg-arg", action="append", default=[], help="Extra ffmpeg output argument; repeat as needed.")
    batch_parser.add_argument("--verbose-ffmpeg", action="store_true", help="Show ffmpeg progress and diagnostic logs.")
    add_style_args(batch_parser)

    return parser


def run(args: Namespace) -> None:
    if args.command == "doctor":
        path_ffmpeg = shutil.which("ffmpeg")
        print(f"ffmpeg on PATH: {path_ffmpeg or 'missing'}")
        print(f"ffprobe selected: {ffprobe_path()}")
        selected = ffmpeg_path(require_subtitles=False)
        hard_selected = ffmpeg_path(require_subtitles=True)
        print(f"ffmpeg selected: {selected}")
        print(f"ffmpeg for hard subtitles: {hard_selected}")
        filters = available_filters(hard_selected)
        print(f"ass filter: {'yes' if 'ass' in filters else 'no'}")
        print(f"subtitles filter: {'yes' if 'subtitles' in filters else 'no'}")
        return

    if args.command == "template":
        if args.template_command == "list":
            for name in template_names():
                print(f"{name}\t{BUILTIN_TEMPLATES[name]['description']}")
            return
        if args.template_command == "show":
            print(template_json(args.name), end="")
            return
        if args.template_command == "export":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(template_json(args.name), encoding="utf-8")
            print(args.output)
            return

    if args.command == "font":
        if args.font_command == "list":
            records = list_fonts(args.font_dir)
            for record in records[: args.limit]:
                print(format_font_record(record))
            return
        if args.font_command == "search":
            records = search_fonts(args.query, args.font_dir)
            for record in records[: args.limit]:
                print(format_font_record(record))
            return
        if args.font_command == "match":
            record = match_font(args.name, args.font_dir)
            if not record:
                raise ValueError(f"No font matched: {args.name}")
            print(format_font_record(record))
            return

    if args.command == "transcode":
        transcode_one(args)
        return

    style = style_from_args(args)
    print_selected_default_fonts(args, style)
    validate_explicit_fonts(args, style)
    print_selected_font_faces(args, style)
    font_rules = load_font_rules(args)
    if args.command == "ass":
        play_res = parse_play_res(args.play_res) if args.play_res else None
        write_ass(args.subtitle, args.output, style, play_res, args.reference_height, font_rules)
        print(args.output)
        return

    if args.command == "burn":
        burn_one(args, args.video, args.subtitle, args.output, style, font_rules)
        return

    if args.command == "batch":
        input_dir = args.input_dir.resolve()
        if not input_dir.is_dir():
            raise ValueError(f"Batch input must be a directory: {args.input_dir}")
        selectors = args.subtitle or args.subtitle_tag or ["auto"]
        resolver = prompt_subtitle_selection if selectors == ["auto"] and sys.stdin.isatty() and sys.stdout.isatty() else None
        matches = find_batch_matches(input_dir, selectors, args.recursive, resolver)
        if not matches:
            raise ValueError(f"No matching video/subtitle pairs found in {args.input_dir}")
        validate_batch_outputs(args, batch_outputs_for_matches(args, matches, input_dir))
        print_batch_output_plan(args, matches, input_dir)
        if args.dry_run:
            return
        if not args.yes and sys.stdin.isatty() and sys.stdout.isatty() and not confirm_batch_plan(matches):
            print("Cancelled.")
            return
        run_batch_jobs(args, matches, input_dir, style, font_rules)


def main() -> None:
    parser = build_parser()
    try:
        run(parser.parse_args())
    except (RuntimeError, ValueError) as exc:
        print(f"captionforge: error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except subprocess.CalledProcessError as exc:
        print(f"captionforge: error: ffmpeg failed with exit code {exc.returncode}", file=sys.stderr)
        raise SystemExit(exc.returncode) from exc


if __name__ == "__main__":
    main()
