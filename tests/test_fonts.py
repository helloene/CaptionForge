from pathlib import Path

from captionforge.fonts import FontRecord, default_font, match_font, search_fonts, system_font_dirs


def test_system_font_dirs_returns_paths():
    assert all(isinstance(path, Path) for path in system_font_dirs())


def test_search_fonts_filters_records(monkeypatch):
    records = [
        FontRecord("Alpha Sans", Path("/fonts/alpha.ttf")),
        FontRecord("Beta Serif", Path("/fonts/beta.ttf")),
    ]
    monkeypatch.setattr("captionforge.fonts.list_fonts", lambda extra_dirs=None: records)
    assert search_fonts("alpha") == [records[0]]


def test_match_font_uses_exact_match_without_fontconfig(monkeypatch):
    records = [FontRecord("Alpha Sans", Path("/fonts/alpha.ttf"))]
    monkeypatch.setattr("captionforge.fonts.shutil.which", lambda name: None)
    monkeypatch.setattr("captionforge.fonts.list_fonts", lambda extra_dirs=None: records)
    assert match_font("Alpha Sans") == records[0]


def test_match_font_prefers_exact_match_before_fontconfig(monkeypatch):
    records = [FontRecord("Alpha Sans", Path("/fonts/alpha.ttf"))]
    monkeypatch.setattr("captionforge.fonts.list_fonts", lambda extra_dirs=None: records)
    monkeypatch.setattr("captionforge.fonts.shutil.which", lambda name: "/usr/bin/fc-match")
    assert match_font("Alpha Sans") == records[0]


def test_default_latin_font_prefers_macos_then_linux_then_windows(monkeypatch):
    records = [
        FontRecord("Segoe UI", Path("/fonts/segoe.ttf")),
        FontRecord("Lato", Path("/fonts/lato.ttf")),
        FontRecord("Helvetica Neue", Path("/fonts/helvetica.ttf")),
    ]
    monkeypatch.setattr("captionforge.fonts.list_fonts", lambda extra_dirs=None: records)

    assert default_font("latin") == "Helvetica Neue"


def test_default_cjk_font_prefers_macos_cjk_stack(monkeypatch):
    records = [
        FontRecord("Noto Sans CJK JP", Path("/fonts/noto-jp.otf")),
        FontRecord("Microsoft YaHei UI", Path("/fonts/msyh.ttc")),
        FontRecord("PingFang SC", Path("/fonts/pingfang.ttc")),
    ]
    monkeypatch.setattr("captionforge.fonts.list_fonts", lambda extra_dirs=None: records)

    assert default_font("cjk") == "PingFang SC"


def test_default_cjk_font_falls_back_to_linux_and_windows(monkeypatch):
    monkeypatch.setattr(
        "captionforge.fonts.list_fonts",
        lambda extra_dirs=None: [
            FontRecord("Malgun Gothic", Path("/fonts/malgun.ttf")),
            FontRecord("Noto Sans CJK TC", Path("/fonts/noto-tc.otf")),
        ],
    )

    assert default_font("cjk") == "Noto Sans CJK TC"


def test_default_font_uses_installed_fallback_when_candidates_are_missing(monkeypatch):
    monkeypatch.setattr(
        "captionforge.fonts.list_fonts",
        lambda extra_dirs=None: [
            FontRecord(".Hidden UI", Path("/fonts/hidden.ttf")),
            FontRecord("Fallback Sans", Path("/fonts/fallback.ttf")),
        ],
    )

    assert default_font("latin") == "Fallback Sans"
