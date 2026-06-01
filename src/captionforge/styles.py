from __future__ import annotations

from dataclasses import dataclass, fields, replace
from pathlib import Path
import re
from typing import Any


HEX_COLOR_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


@dataclass(frozen=True)
class CaptionStyle:
    cjk_font: str = "PingFang SC"
    latin_font: str = "Arial"
    font_size: int = 36
    primary_color: str = "#ffffff"
    outline_color: str = "#000000"
    background_color: str = "#000000"
    primary_alpha: int = 0
    outline_alpha: int = 0
    background_alpha: int = 255
    outline: float = 2.0
    shadow: float = 0.0
    margin_v: int = 48
    margin_l: int = 32
    margin_r: int = 32
    alignment: int = 2
    boxed: bool = False
    corner_radius: int = 14
    padding_h: int = 24
    padding_v: int = 14
    line_spacing: int = 8


def scaled_style(style: CaptionStyle, scale: float) -> CaptionStyle:
    if scale == 1:
        return style
    return replace(
        style,
        font_size=max(1, round(style.font_size * scale)),
        outline=style.outline * scale,
        shadow=style.shadow * scale,
        margin_v=max(0, round(style.margin_v * scale)),
        margin_l=max(0, round(style.margin_l * scale)),
        margin_r=max(0, round(style.margin_r * scale)),
        corner_radius=max(0, round(style.corner_radius * scale)),
        padding_h=max(0, round(style.padding_h * scale)),
        padding_v=max(0, round(style.padding_v * scale)),
        line_spacing=max(0, round(style.line_spacing * scale)),
    )


def ass_color(hex_color: str, alpha: int = 0) -> str:
    match = HEX_COLOR_RE.match(hex_color.strip())
    if not match:
        raise ValueError(f"Invalid color {hex_color!r}; expected #RRGGBB")
    if not 0 <= alpha <= 255:
        raise ValueError("Alpha must be in the range 0..255")
    rgb = match.group(1)
    rr, gg, bb = rgb[0:2], rgb[2:4], rgb[4:6]
    return f"&H{alpha:02X}{bb}{gg}{rr}"


def rgb_alpha(hex_color: str, alpha: int = 0) -> tuple[int, int, int, int]:
    match = HEX_COLOR_RE.match(hex_color.strip())
    if not match:
        raise ValueError(f"Invalid color {hex_color!r}; expected #RRGGBB")
    if not 0 <= alpha <= 255:
        raise ValueError("Alpha must be in the range 0..255")
    rgb = match.group(1)
    return int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16), alpha


def escape_ass_text(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


STYLE_OVERRIDE_KEYS = set(CaptionStyle.__dataclass_fields__)


def validate_style(style: CaptionStyle) -> CaptionStyle:
    for field in fields(CaptionStyle):
        value = getattr(style, field.name)
        expected = field.type
        if expected == "str" and not isinstance(value, str):
            raise ValueError(f"Style field {field.name!r} must be a string")
        if expected == "bool" and not isinstance(value, bool):
            raise ValueError(f"Style field {field.name!r} must be a boolean")
        if expected == "int" and (not isinstance(value, int) or isinstance(value, bool)):
            raise ValueError(f"Style field {field.name!r} must be an integer")
        if expected == "float" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
            raise ValueError(f"Style field {field.name!r} must be a number")

    for color_field in ("primary_color", "outline_color", "background_color"):
        rgb_alpha(getattr(style, color_field))
    for alpha_field in ("primary_alpha", "outline_alpha", "background_alpha"):
        alpha = getattr(style, alpha_field)
        if not 0 <= alpha <= 255:
            raise ValueError(f"Style field {alpha_field!r} must be in the range 0..255")
    if style.font_size <= 0:
        raise ValueError("Style field 'font_size' must be positive")
    if style.alignment not in range(1, 10):
        raise ValueError("Style field 'alignment' must be in the range 1..9")
    for name in ("margin_v", "margin_l", "margin_r", "corner_radius", "padding_h", "padding_v", "line_spacing"):
        if getattr(style, name) < 0:
            raise ValueError(f"Style field {name!r} must be non-negative")
    for name in ("outline", "shadow"):
        if getattr(style, name) < 0:
            raise ValueError(f"Style field {name!r} must be non-negative")
    return style


def apply_style_override(style: CaptionStyle, override: dict[str, Any]) -> CaptionStyle:
    unknown = sorted(set(override) - STYLE_OVERRIDE_KEYS)
    if unknown:
        raise ValueError(f"Unknown style override field(s): {', '.join(unknown)}")
    return validate_style(CaptionStyle(**{**style.__dict__, **override}))


def font_family_name(font_path: Path) -> str:
    from fontTools.ttLib import TTCollection, TTFont

    if font_path.suffix.lower() in {".ttc", ".otc"}:
        collection = TTCollection(str(font_path))
        try:
            if not collection.fonts:
                return font_path.stem
            font = collection.fonts[0]
            return _font_family_from_ttfont(font, font_path)
        finally:
            collection.close()

    font = TTFont(str(font_path))
    try:
        return _font_family_from_ttfont(font, font_path)
    finally:
        font.close()


def font_collection_index(font_path: Path, family_name: str) -> int:
    if font_path.suffix.lower() not in {".ttc", ".otc"}:
        return 0

    from fontTools.ttLib import TTCollection

    collection = TTCollection(str(font_path))
    try:
        lowered = family_name.lower()
        for index, font in enumerate(collection.fonts):
            names = _font_family_names_from_ttfont(font)
            if any(name.lower() == lowered for name in names):
                return index
        for index, font in enumerate(collection.fonts):
            names = _font_family_names_from_ttfont(font)
            if any(lowered in name.lower() for name in names):
                return index
    finally:
        collection.close()
    return 0


def _font_family_from_ttfont(font: Any, font_path: Path) -> str:
    names = _font_family_names_from_ttfont(font)
    return names[0] if names else font_path.stem


def _font_family_names_from_ttfont(font: Any) -> list[str]:
    names = []
    for platform_id, encoding_id, language_id in (
        (3, 1, 0x409),
        (1, 0, 0),
    ):
        name = font["name"].getName(1, platform_id, encoding_id, language_id)
        if name:
            names.append(name.toUnicode())
    for name in font["name"].names:
        if name.nameID == 1:
            names.append(name.toUnicode())
    deduped = []
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        deduped.append(name)
    return deduped
