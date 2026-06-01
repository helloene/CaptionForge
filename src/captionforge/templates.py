from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .styles import CaptionStyle, STYLE_OVERRIDE_KEYS, apply_style_override


BUILTIN_TEMPLATES: dict[str, dict[str, Any]] = {
    "clean": {
        "description": "Transparent background, white text, subtle black outline.",
        "style": {
            "font_size": 48,
            "primary_color": "#ffffff",
            "outline_color": "#000000",
            "background_alpha": 255,
            "outline": 2.0,
            "shadow": 0.0,
            "margin_v": 48,
            "boxed": False,
        },
    },
    "box": {
        "description": "Semi-transparent black subtitle box.",
        "style": {
            "font_size": 48,
            "primary_color": "#ffffff",
            "outline_color": "#000000",
            "background_color": "#000000",
            "background_alpha": 140,
            "outline": 0.0,
            "shadow": 0.0,
            "margin_v": 48,
            "boxed": True,
        },
    },
    "large": {
        "description": "Large, high-contrast subtitles for mobile viewing.",
        "style": {
            "font_size": 64,
            "primary_color": "#ffffff",
            "outline_color": "#000000",
            "background_alpha": 255,
            "outline": 3.0,
            "shadow": 0.0,
            "margin_v": 56,
            "boxed": False,
        },
    },
    "rounded": {
        "description": "Rounded semi-transparent black caption box.",
        "style": {
            "font_size": 48,
            "primary_color": "#ffffff",
            "outline_color": "#000000",
            "background_color": "#000000",
            "background_alpha": 110,
            "outline": 0.0,
            "shadow": 0.0,
            "margin_v": 48,
            "corner_radius": 18,
            "padding_h": 28,
            "padding_v": 16,
            "line_spacing": 8,
            "boxed": False,
        },
    },
    "rounded-white": {
        "description": "Rounded white caption box with black text.",
        "style": {
            "font_size": 48,
            "primary_color": "#000000",
            "outline_color": "#000000",
            "background_color": "#ffffff",
            "background_alpha": 0,
            "outline": 0.0,
            "shadow": 0.0,
            "margin_v": 48,
            "corner_radius": 18,
            "padding_h": 28,
            "padding_v": 16,
            "line_spacing": 8,
            "boxed": False,
        },
    },
}


def template_names() -> list[str]:
    return sorted(BUILTIN_TEMPLATES)


def validate_template_style(data: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(data) - STYLE_OVERRIDE_KEYS)
    if unknown:
        raise ValueError(f"Unknown template style field(s): {', '.join(unknown)}")
    return data


def load_template(name_or_path: str | Path) -> tuple[str, str, dict[str, Any]]:
    text = str(name_or_path)
    if text in BUILTIN_TEMPLATES:
        template = BUILTIN_TEMPLATES[text]
        return text, str(template["description"]), validate_template_style(dict(template["style"]))

    path = Path(name_or_path)
    if not path.exists():
        raise ValueError(f"Template not found: {name_or_path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Template file must contain a JSON object")
    style = data.get("style", data)
    if not isinstance(style, dict):
        raise ValueError("Template 'style' must be a JSON object")
    return path.stem, str(data.get("description", "")), validate_template_style(style)


def style_from_template(name_or_path: str | Path, base: CaptionStyle) -> CaptionStyle:
    _, _, style_data = load_template(name_or_path)
    return apply_style_override(base, style_data)


def template_json(name: str) -> str:
    if name not in BUILTIN_TEMPLATES:
        raise ValueError(f"Unknown built-in template: {name}")
    return json.dumps(BUILTIN_TEMPLATES[name], ensure_ascii=False, indent=2) + "\n"
