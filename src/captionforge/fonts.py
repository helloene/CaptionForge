from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
import platform
import shutil
import subprocess

from .styles import font_family_name


FONT_EXTENSIONS = {".ttf", ".ttc", ".otf", ".otc"}

DEFAULT_LATIN_FONT_CANDIDATES = [
    # macOS: match Apple's Latin UI face instead of letting Latin text fall
    # through to PingFang.
    "SF Pro Text",
    "SF Pro Display",
    ".AppleSystemUIFont",
    "Helvetica Neue",
    # Linux / portable open fonts.
    "Lato",
    "Inter",
    "Noto Sans",
    "DejaVu Sans",
    "Liberation Sans",
    # Windows.
    "Aptos",
    "Segoe UI",
    "Arial",
]

DEFAULT_CJK_FONT_CANDIDATES = [
    # macOS Chinese.
    "PingFang SC",
    "PingFang HK",
    "PingFang TC",
    # macOS Japanese / Korean.
    "Hiragino Sans",
    "Hiragino Kaku Gothic ProN",
    "Apple SD Gothic Neo",
    # Linux / portable CJK superfamilies.
    "Noto Sans CJK SC",
    "Noto Sans CJK HK",
    "Noto Sans CJK TC",
    "Noto Sans CJK JP",
    "Noto Sans CJK KR",
    "Source Han Sans SC",
    "Source Han Sans HK",
    "Source Han Sans TC",
    "Source Han Sans JP",
    "Source Han Sans KR",
    # Windows Chinese / Japanese / Korean.
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "Microsoft JhengHei UI",
    "Microsoft JhengHei",
    "Yu Gothic UI",
    "Yu Gothic",
    "Malgun Gothic",
    "SimHei",
]


@dataclass(frozen=True)
class FontRecord:
    family: str
    path: Path
    source: str = "scan"


def system_font_dirs() -> list[Path]:
    system = platform.system().lower()
    dirs: list[Path] = []
    if system == "windows":
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        local = os.environ.get("LOCALAPPDATA")
        dirs.extend([windir / "Fonts"])
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    elif system == "darwin":
        dirs.extend(
            [
                Path("/System/Library/Fonts"),
                Path("/System/Library/Fonts/Supplemental"),
                Path("/Library/Fonts"),
                Path.home() / "Library" / "Fonts",
            ]
        )
    else:
        dirs.extend(
            [
                Path("/usr/share/fonts"),
                Path("/usr/local/share/fonts"),
                Path.home() / ".fonts",
                Path.home() / ".local/share/fonts",
            ]
        )
    return dirs


def iter_font_files(extra_dirs: list[Path] | None = None) -> list[Path]:
    dirs = [*system_font_dirs(), *(extra_dirs or [])]
    files = []
    seen = set()
    for directory in dirs:
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.suffix.lower() not in FONT_EXTENSIONS:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append(resolved)
    return files


def fontconfig_list() -> list[FontRecord]:
    fc_list = shutil.which("fc-list")
    if not fc_list:
        return []
    result = subprocess.run([fc_list, "-f", "%{family}\t%{file}\n"], check=False, capture_output=True, text=True)
    records = []
    for line in result.stdout.splitlines():
        if "\t" not in line:
            continue
        family_text, file_text = line.split("\t", 1)
        path = Path(file_text)
        if not path.exists():
            continue
        for family in family_text.split(","):
            family = family.strip()
            if family:
                records.append(FontRecord(family, path, "fontconfig"))
    return records


def scan_fonts(extra_dirs: list[Path] | None = None) -> list[FontRecord]:
    records = []
    for path in iter_font_files(extra_dirs):
        try:
            family = font_family_name(path)
        except Exception:
            continue
        records.append(FontRecord(family, path, "scan"))
    return records


@lru_cache(maxsize=16)
def _list_fonts_cached(extra_dir_texts: tuple[str, ...]) -> tuple[FontRecord, ...]:
    extra_dirs = [Path(path) for path in extra_dir_texts]
    records = [*fontconfig_list(), *scan_fonts(extra_dirs)]
    deduped = {}
    for record in records:
        key = (record.family.lower(), str(record.path))
        deduped[key] = record
    return tuple(sorted(deduped.values(), key=lambda item: (item.family.lower(), str(item.path))))


def list_fonts(extra_dirs: list[Path] | None = None) -> list[FontRecord]:
    extra_dir_texts = tuple(str(path.resolve()) for path in (extra_dirs or []))
    return list(_list_fonts_cached(extra_dir_texts))


def search_fonts(query: str, extra_dirs: list[Path] | None = None) -> list[FontRecord]:
    needle = query.lower()
    return [
        record
        for record in list_fonts(extra_dirs)
        if needle in record.family.lower() or needle in str(record.path).lower()
    ]


def match_font(name: str, extra_dirs: list[Path] | None = None) -> FontRecord | None:
    records = list_fonts(extra_dirs)
    lowered = name.lower()
    for record in records:
        if record.family.lower() == lowered:
            return record

    matches = search_fonts(name, extra_dirs)
    if matches:
        return matches[0]

    fc_match = shutil.which("fc-match")
    if fc_match:
        result = subprocess.run([fc_match, "-f", "%{family}\t%{file}", name], check=False, capture_output=True, text=True)
        if "\t" in result.stdout:
            family, file_text = result.stdout.split("\t", 1)
            path = Path(file_text.strip())
            if path.exists():
                return FontRecord(family.split(",")[0].strip() or name, path, "fontconfig")
    return None


def default_font(role: str, extra_dirs: list[Path] | None = None) -> str:
    if role == "latin":
        candidates = DEFAULT_LATIN_FONT_CANDIDATES
    elif role == "cjk":
        candidates = DEFAULT_CJK_FONT_CANDIDATES
    else:
        raise ValueError("Font role must be 'latin' or 'cjk'")

    records = list_fonts(extra_dirs)
    by_family = {record.family.lower(): record.family for record in records}
    for candidate in candidates:
        exact = by_family.get(candidate.lower())
        if exact:
            return exact

    for candidate in candidates:
        needle = candidate.lower()
        for record in records:
            if needle in record.family.lower():
                return record.family

    for record in records:
        if not record.family.startswith("."):
            return record.family

    if records:
        return records[0].family

    return candidates[0]
