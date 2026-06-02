from pathlib import Path

import pytest

from captionforge.styles import CaptionStyle, apply_style_override, ass_color, font_collection_index, font_family_name, font_names, rgb_alpha, scaled_style


def test_ass_color_converts_rgb_to_ass_bgr_with_alpha():
    assert ass_color("#123456", 255) == "&HFF563412"


def test_ass_color_rejects_invalid_alpha():
    with pytest.raises(ValueError):
        ass_color("#ffffff", 300)


def test_rgb_alpha_returns_rgba_tuple():
    assert rgb_alpha("#123456", 12) == (18, 52, 86, 12)


def test_scaled_style_scales_size_outline_and_margins():
    style = scaled_style(CaptionStyle(font_size=48, outline=2, margin_v=48), 0.5)
    assert style.font_size == 24
    assert style.outline == 1
    assert style.margin_v == 24


def test_apply_style_override_validates_types_and_ranges():
    with pytest.raises(ValueError, match="font_size"):
        apply_style_override(CaptionStyle(), {"font_size": "large"})

    with pytest.raises(ValueError, match="primary_alpha"):
        apply_style_override(CaptionStyle(), {"primary_alpha": 300})

    with pytest.raises(ValueError, match="alignment"):
        apply_style_override(CaptionStyle(), {"alignment": 10})


def test_font_family_name_reads_first_font_from_collection(monkeypatch):
    class FakeName:
        def toUnicode(self):
            return "Collection Sans"

    class FakeNameTable:
        names = []

        def getName(self, name_id, platform_id, encoding_id, language_id):
            return FakeName()

    class FakeFont:
        def __getitem__(self, key):
            assert key == "name"
            return FakeNameTable()

    class FakeCollection:
        def __init__(self, path):
            self.fonts = [FakeFont()]
            self.closed = False

        def close(self):
            self.closed = True

    monkeypatch.setattr("fontTools.ttLib.TTCollection", FakeCollection)

    assert font_family_name(Path("example.ttc")) == "Collection Sans"


def test_font_names_reads_family_full_and_postscript(monkeypatch):
    class FakeName:
        def __init__(self, value, name_id):
            self.value = value
            self.nameID = name_id

        def toUnicode(self):
            return self.value

    class FakeNameTable:
        names = []

        def getName(self, name_id, platform_id, encoding_id, language_id):
            values = {
                1: "Example Sans",
                4: "Example Sans Regular",
                6: "ExampleSans-Regular",
            }
            value = values.get(name_id)
            return FakeName(value, name_id) if value else None

    class FakeFont:
        def __getitem__(self, key):
            assert key == "name"
            return FakeNameTable()

        def close(self):
            pass

    monkeypatch.setattr("fontTools.ttLib.TTFont", lambda path: FakeFont())

    names = font_names(Path("example.ttf"))

    assert names.family == "Example Sans"
    assert names.full_name == "Example Sans Regular"
    assert names.postscript_name == "ExampleSans-Regular"
    assert names.selected("postscript") == "ExampleSans-Regular"


def test_font_collection_index_matches_family_name(monkeypatch):
    class FakeName:
        def __init__(self, value):
            self.value = value

        def toUnicode(self):
            return self.value

    class FakeNameTable:
        def __init__(self, value):
            self.names = []
            self.value = value

        def getName(self, name_id, platform_id, encoding_id, language_id):
            return FakeName(self.value)

    class FakeFont:
        def __init__(self, value):
            self.value = value

        def __getitem__(self, key):
            assert key == "name"
            return FakeNameTable(self.value)

    class FakeCollection:
        def __init__(self, path):
            self.fonts = [FakeFont("PingFang HK"), FakeFont("PingFang TC"), FakeFont("PingFang SC")]

        def close(self):
            pass

    monkeypatch.setattr("fontTools.ttLib.TTCollection", FakeCollection)

    assert font_collection_index(Path("PingFang.ttc"), "PingFang SC") == 2
