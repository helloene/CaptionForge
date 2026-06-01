from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pysubs2

from .fontsplit import FontRule, apply_mixed_fonts
from .styles import CaptionStyle, rgb_alpha, scaled_style


def load_subtitles(path: Path) -> pysubs2.SSAFile:
    try:
        return pysubs2.load(str(path))
    except Exception as exc:
        raise ValueError(f"Could not load subtitle file {path}: {exc}") from exc


def style_subtitles(
    subs: pysubs2.SSAFile,
    style: CaptionStyle,
    play_res: tuple[int, int] | None = None,
    reference_height: int = 720,
    font_rules: list[FontRule] | None = None,
) -> pysubs2.SSAFile:
    styled = deepcopy(subs)
    if play_res:
        width, height = play_res
        styled.info["PlayResX"] = str(width)
        styled.info["PlayResY"] = str(height)
        style = scaled_style(style, height / reference_height)

    default = pysubs2.SSAStyle()
    default.fontname = style.latin_font
    default.fontsize = style.font_size
    default.primarycolor = pysubs2.Color(*rgb_alpha(style.primary_color, style.primary_alpha))
    default.outlinecolor = pysubs2.Color(*rgb_alpha(style.outline_color, style.outline_alpha))
    default.backcolor = pysubs2.Color(*rgb_alpha(style.background_color, style.background_alpha))
    default.bold = False
    default.italic = False
    default.borderstyle = 3 if style.boxed else 1
    default.outline = style.outline
    default.shadow = style.shadow
    default.alignment = pysubs2.Alignment(style.alignment)
    default.marginl = style.margin_l
    default.marginr = style.margin_r
    default.marginv = style.margin_v
    styled.styles["Default"] = default

    for event in styled.events:
        event.style = "Default"
        event.text = apply_mixed_fonts(event.text, style.cjk_font, style.latin_font, font_rules)

    return styled


def make_style(style: CaptionStyle) -> pysubs2.SSAStyle:
    ass_style = pysubs2.SSAStyle()
    ass_style.fontname = style.latin_font
    ass_style.fontsize = style.font_size
    ass_style.primarycolor = pysubs2.Color(*rgb_alpha(style.primary_color, style.primary_alpha))
    ass_style.outlinecolor = pysubs2.Color(*rgb_alpha(style.outline_color, style.outline_alpha))
    ass_style.backcolor = pysubs2.Color(*rgb_alpha(style.background_color, style.background_alpha))
    ass_style.bold = False
    ass_style.italic = False
    ass_style.borderstyle = 3 if style.boxed else 1
    ass_style.outline = style.outline
    ass_style.shadow = style.shadow
    ass_style.alignment = pysubs2.Alignment(style.alignment)
    ass_style.marginl = style.margin_l
    ass_style.marginr = style.margin_r
    ass_style.marginv = style.margin_v
    return ass_style


def styled_event(
    event: pysubs2.SSAEvent,
    style_name: str,
    style: CaptionStyle,
    font_rules: list[FontRule] | None = None,
) -> pysubs2.SSAEvent:
    copied = deepcopy(event)
    copied.style = style_name
    copied.text = apply_mixed_fonts(copied.text, style.cjk_font, style.latin_font, font_rules)
    return copied


def merged_events_by_active_text(
    subtitle_paths: list[Path],
    style: CaptionStyle,
    font_rules: list[FontRule] | None = None,
) -> list[pysubs2.SSAEvent]:
    tracks = []
    boundaries = set()
    for path in subtitle_paths:
        events = [event for event in load_subtitles(path).events if event.text.strip()]
        tracks.append(events)
        for event in events:
            boundaries.add(event.start)
            boundaries.add(event.end)

    merged = []
    sorted_boundaries = sorted(boundaries)
    for start, end in zip(sorted_boundaries, sorted_boundaries[1:]):
        if start >= end:
            continue
        lines = []
        for events in tracks:
            active = [event for event in events if event.start <= start and event.end >= end]
            if active:
                lines.append(active[0].text)
        if not lines:
            continue
        text = r"\N".join(apply_mixed_fonts(line, style.cjk_font, style.latin_font, font_rules) for line in lines)
        if merged and merged[-1].end == start and merged[-1].text == text:
            merged[-1].end = end
        else:
            merged.append(pysubs2.SSAEvent(start=start, end=end, text=text, style="Default"))
    return merged


def write_ass(
    input_path: Path,
    output_path: Path,
    style: CaptionStyle,
    play_res: tuple[int, int] | None = None,
    reference_height: int = 720,
    font_rules: list[FontRule] | None = None,
) -> Path:
    subs = style_subtitles(load_subtitles(input_path), style, play_res, reference_height, font_rules)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subs.save(str(output_path), format_="ass")
    return output_path


def write_multi_ass(
    input_paths: list[Path],
    output_path: Path,
    style: CaptionStyle,
    play_res: tuple[int, int] | None = None,
    reference_height: int = 720,
    layout: str = "stack",
    font_rules: list[FontRule] | None = None,
) -> Path:
    if not input_paths:
        raise ValueError("At least one subtitle file is required")
    if len(input_paths) == 1:
        return write_ass(input_paths[0], output_path, style, play_res, reference_height, font_rules)
    if layout not in {"stack", "merge"}:
        raise ValueError("--multi-subtitle-layout must be stack or merge")

    result = pysubs2.SSAFile()
    if play_res:
        width, height = play_res
        result.info["PlayResX"] = str(width)
        result.info["PlayResY"] = str(height)
        style = scaled_style(style, height / reference_height)

    if layout == "merge":
        result.styles["Default"] = make_style(style)
        result.events = merged_events_by_active_text(input_paths, style, font_rules)
    else:
        line_step = round(style.font_size * 1.25 + style.line_spacing)
        for index, input_path in enumerate(input_paths):
            style_name = f"Subtitle{index + 1}"
            track_style = make_style(style)
            track_style.marginv = style.margin_v + line_step * (len(input_paths) - index - 1)
            result.styles[style_name] = track_style
            for event in load_subtitles(input_path).events:
                result.events.append(styled_event(event, style_name, style, font_rules))

    result.events.sort(key=lambda event: (event.start, event.end, event.style))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(str(output_path), format_="ass")
    return output_path
