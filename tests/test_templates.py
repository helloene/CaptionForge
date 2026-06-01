import json

from captionforge.styles import CaptionStyle
from captionforge.templates import load_template, style_from_template, template_json, template_names


def test_builtin_template_names_include_clean():
    assert "clean" in template_names()


def test_style_from_builtin_template():
    style = style_from_template("large", CaptionStyle(font_size=12))
    assert style.font_size == 64
    assert style.outline == 3.0


def test_rounded_template_uses_box_without_text_outline():
    style = style_from_template("rounded", CaptionStyle())
    assert style.background_alpha < 255
    assert style.outline == 0.0


def test_rounded_white_template_uses_white_box_and_black_text():
    style = style_from_template("rounded-white", CaptionStyle())
    assert style.primary_color == "#000000"
    assert style.background_color == "#ffffff"
    assert style.background_alpha == 0
    assert style.corner_radius > 0
    assert style.outline == 0.0


def test_load_template_from_file(tmp_path):
    path = tmp_path / "custom.json"
    path.write_text(json.dumps({"description": "x", "style": {"font_size": 50}}), encoding="utf-8")
    name, description, style = load_template(path)
    assert name == "custom"
    assert description == "x"
    assert style == {"font_size": 50}


def test_template_json_is_json():
    assert json.loads(template_json("clean"))["style"]["background_alpha"] == 255
