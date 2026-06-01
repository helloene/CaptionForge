from pathlib import Path

from captionforge.styles import CaptionStyle
from captionforge.subtitles import write_ass, write_multi_ass


def test_write_ass_adds_play_res_and_scales_style(tmp_path: Path):
    srt = tmp_path / "in.srt"
    out = tmp_path / "out.ass"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello 世界\n", encoding="utf-8")

    write_ass(srt, out, CaptionStyle(font_size=48, outline=2, margin_v=48), (640, 360), 720)

    text = out.read_text(encoding="utf-8")
    assert "PlayResX: 640" in text
    assert "PlayResY: 360" in text
    assert "Style: Default,Arial,24," in text
    assert ",1,1,0,2,16,16,24,1" in text


def test_write_multi_ass_stacks_subtitles(tmp_path: Path):
    en = tmp_path / "en.srt"
    zh = tmp_path / "zh.srt"
    out = tmp_path / "out.ass"
    en.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
    zh.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")

    write_multi_ass([en, zh], out, CaptionStyle(font_size=48, margin_v=48), (1280, 720), layout="stack")

    text = out.read_text(encoding="utf-8")
    assert "Style: Subtitle1" in text
    assert "Style: Subtitle2" in text
    assert "Dialogue:" in text
    assert r"{\fnArial}Hello" in text


def test_write_multi_ass_merges_active_text_with_newline(tmp_path: Path):
    en = tmp_path / "en.srt"
    zh = tmp_path / "zh.srt"
    out = tmp_path / "out.ass"
    en.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
    zh.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")

    write_multi_ass([en, zh], out, CaptionStyle(), (1280, 720), layout="merge")

    text = out.read_text(encoding="utf-8")
    assert r"Hello\N" in text
    assert "你好" in text
