"""Parse TV release-style filenames for season/episode hints."""

from __future__ import annotations

import re
from pathlib import Path

from termrenamer.core.models import FilmParseResult, ParseResult, ScanMode
from termrenamer.util.errors import ParseError

_SXXEYY = re.compile(
    r"(?i)(?<![0-9a-z])(?:S(?P<season>\d{1,2}))(?:E(?P<ep1>\d{1,3}))(?:E(?P<ep2>\d{1,3}))?",
)

_YEAR_TOKEN = re.compile(r"(?<![0-9])(?:19|20)\d{2}(?![0-9])")

# Trailing release tags often not part of the title (heuristic).
_FILM_JUNK = frozenset(
    {
        "1080p",
        "720p",
        "480p",
        "2160p",
        "4k",
        "8k",
        "h264",
        "h265",
        "x264",
        "x265",
        "hevc",
        "av1",
        "bluray",
        "blu-ray",
        "webrip",
        "web-dl",
        "webdl",
        "dvdrip",
        "hdtv",
        "amzn",
        "repack",
        "proper",
        "remastered",
        "extended",
        "theatrical",
        "directors",
        "cut",
        "hdr",
        "sdr",
        "atmos",
        "ddp",
        "dd5",
        "aac",
        "dts",
    },
)


def _clean_show_name(raw: str) -> str:
    s = raw.replace(".", " ").replace("_", " ").strip(" -_.")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def parse_filename(*, name: str, mode: ScanMode) -> ParseResult:
    """Extract TV show hint and SxxEyy episode indices from a filename stem.

    Raises:
        ParseError: If the name is not usable for TV parsing.
    """
    if mode is not ScanMode.TV:
        msg = "Use parse_film_filename() for film mode"
        raise ParseError(msg)

    stem = Path(name).stem
    match = _SXXEYY.search(stem)
    if not match:
        msg = f"No SxxEyy pattern found in {name!r}"
        raise ParseError(msg)

    season = int(match.group("season"))
    ep1 = int(match.group("ep1"))
    episodes: tuple[int, ...] = (ep1,)
    if match.group("ep2") is not None:
        ep2 = int(match.group("ep2"))
        episodes = tuple(sorted({ep1, ep2}))

    show_part = stem[: match.start()]
    show_hint = _clean_show_name(show_part)
    if not show_hint:
        msg = f"Could not derive show name from {name!r}"
        raise ParseError(msg)

    return ParseResult(show_hint=show_hint, season=season, episodes=episodes)


def parse_film_filename(*, name: str) -> FilmParseResult:
    """Extract a title hint and optional release year from a film filename stem."""
    stem = Path(name).stem
    parts = [p for p in re.split(r"[._\s()]+", stem) if p]
    year_hint: int | None = None
    year_idx: int | None = None
    for i, part in enumerate(parts):
        if _YEAR_TOKEN.fullmatch(part):
            year_hint = int(part)
            year_idx = i
            break
    title_parts = parts[:year_idx] if year_idx is not None else parts[:]

    while title_parts and title_parts[-1].lower() in _FILM_JUNK:
        title_parts.pop()

    title_hint = " ".join(title_parts).strip()
    title_hint = re.sub(r"\s+", " ", title_hint)
    if not title_hint:
        msg = f"Could not derive film title from {name!r}"
        raise ParseError(msg)

    return FilmParseResult(title_hint=title_hint, year_hint=year_hint)
