from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Tuple


ASS_TAG_RE = re.compile(r"(\{[^{}]*\})")
FONT_RULE_MODES = {
    "contains",
    "contains-ignore-case",
    "exact",
    "exact-ignore-case",
    "any-char",
    "any-char-ignore-case",
}


@dataclass(frozen=True)
class FontRule:
    font: str
    pattern: str
    mode: str = "contains"


def font_rule_from_dict(data: dict[str, Any]) -> FontRule:
    font = data.get("font")
    pattern = data.get("pattern", data.get("text", data.get("match")))
    mode = data.get("mode", "contains")
    if not isinstance(font, str) or not font:
        raise ValueError("Font rule field 'font' must be a non-empty string")
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("Font rule field 'pattern' must be a non-empty string")
    if mode not in FONT_RULE_MODES:
        raise ValueError(f"Font rule mode must be one of {', '.join(sorted(FONT_RULE_MODES))}")
    return FontRule(font=font, pattern=pattern, mode=mode)


def _find_rule_spans(text: str, rule: FontRule) -> list[tuple[int, int, str]]:
    if rule.mode in {"exact", "exact-ignore-case"}:
        haystack = text.casefold() if rule.mode.endswith("ignore-case") else text
        needle = rule.pattern.casefold() if rule.mode.endswith("ignore-case") else rule.pattern
        return [(0, len(text), rule.font)] if haystack == needle else []

    if rule.mode in {"any-char", "any-char-ignore-case"}:
        chars = set(rule.pattern.casefold() if rule.mode.endswith("ignore-case") else rule.pattern)
        spans = []
        for index, char in enumerate(text):
            key = char.casefold() if rule.mode.endswith("ignore-case") else char
            if key in chars:
                spans.append((index, index + 1, rule.font))
        return spans

    ignore_case = rule.mode.endswith("ignore-case")
    haystack = text.casefold() if ignore_case else text
    needle = rule.pattern.casefold() if ignore_case else rule.pattern
    spans = []
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index < 0:
            break
        spans.append((index, index + len(rule.pattern), rule.font))
        start = index + max(1, len(rule.pattern))
    return spans


def split_rule_font_runs(text: str, rules: list[FontRule]) -> Iterator[tuple[str | None, str]]:
    if not rules or not text:
        yield None, text
        return

    assignments: list[str | None] = [None] * len(text)
    for rule in rules:
        for start, end, font in _find_rule_spans(text, rule):
            for index in range(max(0, start), min(len(text), end)):
                assignments[index] = font

    start = 0
    current = assignments[0]
    for index, font in enumerate(assignments[1:], 1):
        if font != current:
            yield current, text[start:index]
            start = index
            current = font
    yield current, text[start:]


def is_cjk(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x3040 <= codepoint <= 0x30FF
        or 0xAC00 <= codepoint <= 0xD7AF
        or 0x3000 <= codepoint <= 0x303F
        or 0xFF00 <= codepoint <= 0xFFEF
    )


def is_latin(char: str) -> bool:
    return char.isascii() and (char.isalpha() or char.isdigit())


def split_text_runs(text: str) -> Iterator[Tuple[str, str]]:
    current_kind = "neutral"
    buffer = []

    def flush() -> Iterator[Tuple[str, str]]:
        nonlocal buffer
        if buffer:
            yield current_kind, "".join(buffer)
            buffer = []

    for char in text:
        if is_cjk(char):
            kind = "cjk"
        elif is_latin(char):
            kind = "latin"
        else:
            kind = current_kind if current_kind in {"cjk", "latin"} else "neutral"

        if buffer and kind != current_kind:
            yield from flush()
        current_kind = kind
        buffer.append(char)

    yield from flush()


def font_for_kind(kind: str, cjk_font: str, latin_font: str, current_font: str | None) -> str | None:
    if kind == "cjk":
        return cjk_font
    if kind == "latin":
        return latin_font
    return current_font


def split_mixed_font_runs(
    text: str,
    cjk_font: str,
    latin_font: str,
    rules: list[FontRule] | None = None,
) -> Iterator[tuple[str | None, str]]:
    current_font = None
    for segment in ASS_TAG_RE.split(text):
        if not segment:
            continue
        if ASS_TAG_RE.fullmatch(segment):
            yield None, segment
            continue

        for rule_font, rule_value in split_rule_font_runs(segment, rules or []):
            if rule_font:
                yield rule_font, rule_value
                continue
            for kind, value in split_text_runs(rule_value):
                font = font_for_kind(kind, cjk_font, latin_font, current_font)
                yield font, value
                if font:
                    current_font = font


def apply_mixed_fonts(text: str, cjk_font: str, latin_font: str, rules: list[FontRule] | None = None) -> str:
    parts = []
    current_font = None

    for font, value in split_mixed_font_runs(text, cjk_font, latin_font, rules):
        if font is None:
            parts.append(value)
            continue
        if font != current_font:
            parts.append(r"{\fn" + font + "}")
            current_font = font
        parts.append(value)

    return "".join(parts)
