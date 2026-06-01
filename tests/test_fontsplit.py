from captionforge.fontsplit import FontRule, apply_mixed_fonts, font_rule_from_dict


def test_applies_cjk_and_latin_fonts_in_one_line():
    assert apply_mixed_fonts("你好 ABC 世界123", "Songti SC", "Avenir") == (
        r"{\fnSongti SC}你好 "
        r"{\fnAvenir}ABC "
        r"{\fnSongti SC}世界"
        r"{\fnAvenir}123"
    )


def test_preserves_existing_ass_tags():
    assert apply_mixed_fonts(r"{\i1}Hi 世界", "CJK", "Latin") == r"{\i1}{\fnLatin}Hi {\fnCJK}世界"


def test_font_rule_overrides_matching_text():
    assert apply_mixed_fonts(
        "plain McDonald chicken",
        "CJK",
        "Latin",
        [
            FontRule(font="Special", pattern="McDonald", mode="contains"),
            FontRule(font="Special", pattern="chicken", mode="contains-ignore-case"),
        ],
    ) == r"{\fnLatin}plain {\fnSpecial}McDonald{\fnLatin} {\fnSpecial}chicken"


def test_font_rule_can_match_any_character_ignore_case():
    assert apply_mixed_fonts(
        "abc XYZ",
        "CJK",
        "Latin",
        [FontRule(font="Letters", pattern="cz", mode="any-char-ignore-case")],
    ) == r"{\fnLatin}ab{\fnLetters}c{\fnLatin} XY{\fnLetters}Z"


def test_font_rule_from_dict_accepts_match_alias():
    rule = font_rule_from_dict({"font": "Special", "match": "word", "mode": "exact-ignore-case"})

    assert rule == FontRule(font="Special", pattern="word", mode="exact-ignore-case")
