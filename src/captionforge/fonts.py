from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
import platform
import shutil
import subprocess

from .styles import font_names


FONT_EXTENSIONS = {".ttf", ".ttc", ".otf", ".otc"}

DEFAULT_LATIN_FONT_CANDIDATES = [
    # Prefer Apple's Latin UI faces so Latin text does not fall through to CJK fonts.
    "SF Pro Text",
    "SF Pro Display",
    ".AppleSystemUIFont",
    "Helvetica Neue",
    # Portable open-source families commonly available on Linux.
    "Lato",
    "Inter",
    "Noto Sans",
    "DejaVu Sans",
    "Liberation Sans",
    # Windows UI and document defaults.
    "Aptos",
    "Segoe UI",
    "Arial",
]

DEFAULT_CJK_FONT_CANDIDATES = [
    # macOS Chinese families.
    "PingFang SC",
    "PingFang HK",
    "PingFang TC",
    # macOS Japanese and Korean families.
    "Hiragino Sans",
    "Hiragino Kaku Gothic ProN",
    "Apple SD Gothic Neo",
    # Portable CJK superfamilies commonly available on Linux.
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
    # Windows Chinese, Japanese, and Korean families.
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
    full_name: str | None = None
    postscript_name: str | None = None

    def searchable_names(self) -> tuple[str, ...]:
        return tuple(name for name in (self.family, self.full_name, self.postscript_name) if name)


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
    result = subprocess.run([fc_list, "-f", "%{family}\t%{fullname}\t%{postscriptname}\t%{file}\n"], check=False, capture_output=True, text=True)
    records = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        family_text, full_text, postscript_text, file_text = parts
        path = Path(file_text.strip())
        if not path.exists():
            continue
        families = [name.strip() for name in family_text.split(",") if name.strip()]
        full_names = [name.strip() for name in full_text.split(",") if name.strip()]
        postscript_names = [name.strip() for name in postscript_text.split(",") if name.strip()]
        for family in families:
            full_name = next((name for name in full_names if name.lower().startswith(family.lower())), full_names[0] if full_names else None)
            postscript_name = postscript_names[0] if postscript_names else None
            family = family.strip()
            if family:
                records.append(FontRecord(family, path, "fontconfig", full_name, postscript_name))
    return records


def scan_fonts(extra_dirs: list[Path] | None = None) -> list[FontRecord]:
    records = []
    for path in iter_font_files(extra_dirs):
        try:
            names = font_names(path)
        except Exception:
            continue
        records.append(FontRecord(names.family, path, "scan", names.full_name, names.postscript_name))
    return records


@lru_cache(maxsize=16)
def _list_fonts_cached(extra_dir_texts: tuple[str, ...]) -> tuple[FontRecord, ...]:
    extra_dirs = [Path(path) for path in extra_dir_texts]
    records = [*fontconfig_list(), *scan_fonts(extra_dirs)]
    deduped = {}
    for record in records:
        key = (record.family.lower(), (record.full_name or "").lower(), (record.postscript_name or "").lower(), str(record.path))
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
        if any(needle in name.lower() for name in record.searchable_names()) or needle in str(record.path).lower()
    ]


def match_font_exact(name: str, extra_dirs: list[Path] | None = None) -> FontRecord | None:
    lowered = name.lower()
    for record in list_fonts(extra_dirs):
        if any(candidate.lower() == lowered for candidate in record.searchable_names()):
            return record
    return None


def match_font(name: str, extra_dirs: list[Path] | None = None) -> FontRecord | None:
    records = list_fonts(extra_dirs)
    exact = match_font_exact(name, extra_dirs)
    if exact:
        return exact

    matches = search_fonts(name, extra_dirs)
    if matches:
        return matches[0]

    fc_match = shutil.which("fc-match")
    if fc_match:
        result = subprocess.run([fc_match, "-f", "%{family}\t%{fullname}\t%{postscriptname}\t%{file}", name], check=False, capture_output=True, text=True)
        parts = result.stdout.split("\t")
        if len(parts) == 4:
            family, full_name, postscript_name, file_text = parts
            path = Path(file_text.strip())
            if path.exists():
                return FontRecord(
                    family.split(",")[0].strip() or name,
                    path,
                    "fontconfig",
                    full_name.split(",")[0].strip() or None,
                    postscript_name.split(",")[0].strip() or None,
                )
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
