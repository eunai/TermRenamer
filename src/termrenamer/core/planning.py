"""Plan the queued Sources: the one entry point that builds a Plan.

:func:`plan_queue` takes the queue, the plan options and the build's Provider, and
returns one Plan. It touches the filesystem only to list the Sources and the source
folders, to stat their files and to test the wanted names; nothing is renamed.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import overload

from termrenamer.api.base import FilmMetadataProvider, TvMetadataProvider
from termrenamer.api.lookup import FilmLookup, TvLookup
from termrenamer.core.collisions import claim_name
from termrenamer.core.models import (
    Candidate,
    EntryStatus,
    EpisodeMetadata,
    FileKind,
    FilmParseResult,
    MovieMetadata,
    ParseResult,
    Plan,
    PlanEntry,
    PlanFingerprint,
    PlanOptions,
    ScanMode,
    SourceFolder,
    Title,
)
from termrenamer.core.parse import parse_filename, parse_film_filename
from termrenamer.core.paths import path_key
from termrenamer.core.progress import (
    BuildFinished,
    CancelSignal,
    FileLookedUp,
    PlanEvent,
    PlanListener,
    Scanned,
    ScannedTitle,
    TitleLookedUp,
    TitleLookupStarted,
)
from termrenamer.core.scan import classify, scan
from termrenamer.core.stragglers import plan_stragglers
from termrenamer.core.templates import format_film_destination, format_tv_destination
from termrenamer.util.errors import ParseError

_LOG = logging.getLogger(__name__)


def fingerprint(path: Path) -> PlanFingerprint:
    """The source's size and modification time, as planning records them and Apply checks."""
    st = path.stat()
    return PlanFingerprint(path=path, size=st.st_size, mtime_ns=int(st.st_mtime_ns))


# --------------------------------------------------------------------------
# Plan the queued Sources: the one entry point.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlanBuild:
    """What :func:`plan_queue` returns: the Plan, and a message for each Source skipped."""

    plan: Plan
    messages: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Found:
    """A video or Sidecar of the queue, with the folder of its owning Source, and
    whether that Source is a folder."""

    path: Path
    root: Path
    kind: FileKind
    in_folder_source: bool = False


@dataclass(frozen=True, slots=True)
class _Video:
    """A recognised video: its name read for a title hint (and for TV, an episode)."""

    path: Path
    root: Path
    parsed: ParseResult | FilmParseResult

    @property
    def hint(self) -> str:
        if isinstance(self.parsed, ParseResult):
            return self.parsed.show_hint
        return self.parsed.title_hint

    @property
    def year_hint(self) -> int | None:
        return self.parsed.year_hint if isinstance(self.parsed, FilmParseResult) else None

    @property
    def group_key(self) -> tuple[str, int]:
        """Videos are grouped by title hint, and for Film the year hint too."""
        year = self.year_hint
        return (_hint_key(self.hint), year if year is not None else -1)


def _seasons(members: Sequence[_Video]) -> tuple[int, ...]:
    return tuple(sorted({v.parsed.season for v in members if isinstance(v.parsed, ParseResult)}))


def _hint_key(hint: str) -> str:
    return hint.casefold().strip()


def _pair_key(path: Path) -> tuple[str, str]:
    """The pairing rule's key: a Sidecar belongs to the video in its folder with its stem."""
    return (str(path.parent).casefold(), path.stem.casefold())


def _file_source(path: Path) -> list[_Found]:
    """A file Source's video, and the Sidecars the pairing rule ties to it."""
    root = path.parent
    found = [_Found(path=path, root=root, kind=FileKind.VIDEO)]
    for sibling in sorted(root.iterdir(), key=lambda p: p.name.casefold()):
        if (
            sibling.is_file()
            and classify(sibling.suffix) is FileKind.SIDECAR
            and _pair_key(sibling) == _pair_key(path)
        ):
            found.append(_Found(path=sibling, root=root, kind=FileKind.SIDECAR))
    return found


def _collect(sources: Sequence[Path]) -> tuple[list[_Found], list[str]]:
    """Every video and Sidecar the queued Sources contribute, each once.

    A file reached by more than one Source belongs to the outermost folder Source
    that contains it, otherwise to its file Source.
    """
    owned: dict[str, tuple[tuple[int, int], _Found]] = {}
    messages: list[str] = []
    for source in sources:
        resolved = source.resolve()
        if not resolved.exists():
            messages.append(f"Skipped {source}: it no longer exists.")
            continue
        if resolved.is_dir():
            rank = (0, len(resolved.parts))
            contributed = [
                _Found(path=f.path, root=resolved, kind=f.kind, in_folder_source=True)
                for f in scan(root=resolved)
            ]
        elif classify(resolved.suffix) is FileKind.VIDEO:
            rank = (1, 0)
            contributed = _file_source(resolved)
        else:
            messages.append(f"Skipped {source}: it is not a video.")
            continue
        for found_file in contributed:
            key = path_key(found_file.path)
            if key not in owned or rank < owned[key][0]:
                owned[key] = (rank, found_file)
    return [found_file for _rank, found_file in owned.values()], messages


def _entry(
    found: _Found | _Video,
    *,
    destination: Path | None,
    status: EntryStatus,
    title: Title | None,
    video: PlanEntry | None = None,
) -> PlanEntry:
    parsed = found.parsed if isinstance(found, _Video) else None
    season = parsed.season if isinstance(parsed, ParseResult) else None
    episode = parsed.primary_episode if isinstance(parsed, ParseResult) else None
    if video is not None:
        season, episode = video.season, video.episode
    return PlanEntry(
        source=found.path,
        destination=destination,
        status=status,
        title=title,
        video=video.source if video is not None else None,
        season=season,
        episode=episode,
        root=found.root,
        fingerprint=fingerprint(found.path),
    )


def _titles(
    found_groups: Sequence[tuple[list[_Video], tuple[Candidate, ...]]],
) -> dict[Path, Title]:
    """Make the Titles: groups with the same Match are one Title, a group with none its own.

    ``found_groups`` is in title-hint order; a merged Title keeps the Candidates of
    its first group.
    """
    merged: dict[str, tuple[list[_Video], tuple[Candidate, ...]]] = {}
    no_match: list[list[_Video]] = []
    for members, candidates_found in found_groups:
        if not candidates_found:
            no_match.append(members)
        elif candidates_found[0].id in merged:
            merged[candidates_found[0].id][0].extend(members)
        else:
            merged[candidates_found[0].id] = (list(members), candidates_found)

    title_of: dict[Path, Title] = {}
    for members, candidates_found in merged.values():
        match = candidates_found[0]
        title = Title(
            name=match.name,
            year=match.year,
            seasons=_seasons(members),
            match=match,
            candidates=candidates_found[1:],
        )
        title_of.update((v.path, title) for v in members)
    for members in no_match:
        title = Title(
            name=members[0].hint,
            year=members[0].year_hint,
            seasons=_seasons(members),
            match=None,
            candidates=(),
        )
        title_of.update((v.path, title) for v in members)
    return title_of


def _lookup(
    provider: TvMetadataProvider | FilmMetadataProvider, mode: ScanMode
) -> TvLookup | FilmLookup:
    """The build's lookup; a bare Provider gets one of its own, with no cache."""
    if mode is ScanMode.TV:
        if not isinstance(provider, TvMetadataProvider):
            msg = "TV mode requires a TvMetadataProvider"
            raise TypeError(msg)
        return provider if isinstance(provider, TvLookup) else TvLookup(provider)
    if not isinstance(provider, FilmMetadataProvider):
        msg = "Film mode requires a FilmMetadataProvider"
        raise TypeError(msg)
    return provider if isinstance(provider, FilmLookup) else FilmLookup(provider)


def _search(lookup: TvLookup | FilmLookup, video: _Video) -> tuple[Candidate, ...]:
    """One group's search, in the Provider's order; a film without a year is dropped."""
    if isinstance(lookup, TvLookup):
        return lookup.search_shows(hint=video.hint)
    films = lookup.search_films(hint=video.hint, year=video.year_hint)
    return tuple(film for film in films if film.year is not None)


def _parse(path: Path, mode: ScanMode) -> ParseResult | FilmParseResult:
    if mode is ScanMode.TV:
        return parse_filename(name=path.name, mode=ScanMode.TV)
    return parse_film_filename(name=path.name)


def _wanted_name(
    video: _Video, match: Candidate, episode_title: str | None, options: PlanOptions
) -> Path | None:
    """The name today's templates give ``video`` for ``match``; ``None`` for no episode."""
    if isinstance(video.parsed, ParseResult):
        if episode_title is None:
            return None
        return format_tv_destination(
            root=video.root,
            parse=video.parsed,
            metadata=EpisodeMetadata(show_title=match.name, episode_title=episode_title),
            original_path=video.path,
            dest_root=options.destination_root,
            enable_folder_rename=options.folder_rename,
            enable_season_folders=options.season_folders,
        )
    assert match.year is not None
    return format_film_destination(
        root=video.root,
        metadata=MovieMetadata(title=match.name, year=match.year),
        original_path=video.path,
        dest_root=options.destination_root,
        enable_folder_rename=options.folder_rename,
    )


@overload
def plan_queue(
    sources: Sequence[Path],
    options: PlanOptions,
    provider: TvMetadataProvider | FilmMetadataProvider,
    *,
    listener: PlanListener | None = None,
    cancel: None = None,
) -> PlanBuild: ...


@overload
def plan_queue(
    sources: Sequence[Path],
    options: PlanOptions,
    provider: TvMetadataProvider | FilmMetadataProvider,
    *,
    listener: PlanListener | None = None,
    cancel: CancelSignal,
) -> PlanBuild | None: ...


def plan_queue(
    sources: Sequence[Path],
    options: PlanOptions,
    provider: TvMetadataProvider | FilmMetadataProvider,
    *,
    listener: PlanListener | None = None,
    cancel: CancelSignal | None = None,
) -> PlanBuild | None:
    """Plan every file of the queued ``sources`` with ``options``, in one Plan.

    Returns the Plan and a message for each Source that was skipped (it no longer
    exists, or it is a file that is not a video). The Plan records the children of each
    source folder inside a folder Source and, with Folder rename on, lists its
    Stragglers (:func:`~termrenamer.core.stragglers.plan_stragglers`). ``listener`` is
    told each event of :mod:`termrenamer.core.progress` as the build runs; an exception
    it raises stops the build. ``cancel`` is checked before each lookup: once it is set,
    the build stops and returns ``None``.
    """
    lookup = _lookup(provider, options.mode)
    found, messages = _collect(sources)
    entries: list[PlanEntry] = []
    videos: list[_Video] = []
    for found_file in sorted(found, key=lambda f: path_key(f.path)):
        if found_file.kind is not FileKind.VIDEO:
            continue
        try:
            parsed = _parse(found_file.path, options.mode)
        except ParseError:
            _LOG.info("Not recognised: %s", found_file.path)
            entries.append(
                _entry(found_file, destination=None, status=EntryStatus.NOT_RECOGNISED, title=None)
            )
            continue
        videos.append(_Video(path=found_file.path, root=found_file.root, parsed=parsed))

    groups: dict[tuple[str, int], list[_Video]] = {}
    for video in videos:
        groups.setdefault(video.group_key, []).append(video)
    ordered = [groups[key] for key in sorted(groups)]

    def tell(event: PlanEvent) -> None:
        if listener is not None:
            listener(event)

    def cancelled() -> bool:
        return cancel is not None and cancel.is_set()

    tell(
        Scanned(
            files=len(videos),
            titles=tuple(
                ScannedTitle(name=m[0].hint, year=m[0].year_hint, videos=len(m)) for m in ordered
            ),
            not_recognised=tuple(e.source for e in entries),
        )
    )

    # Lookups: one search per group, then in TV Mode one episode lookup per file.
    found_groups: list[tuple[list[_Video], tuple[Candidate, ...]]] = []
    episode_titles: dict[Path, str | None] = {}
    for members in ordered:
        name, year = members[0].hint, members[0].year_hint
        if cancelled():
            return None
        tell(TitleLookupStarted(name=name, year=year))
        candidates_found = _search(lookup, members[0])
        found_groups.append((members, candidates_found))
        tell(
            TitleLookedUp(
                name=name, year=year, match=candidates_found[0] if candidates_found else None
            )
        )
        if not candidates_found or not isinstance(lookup, TvLookup):
            for video in members:
                tell(FileLookedUp(path=video.path, matched=bool(candidates_found)))
            continue
        for video in members:
            assert isinstance(video.parsed, ParseResult)
            if cancelled():
                return None
            episode_title = lookup.episode_title(
                show_id=candidates_found[0].id,
                season=video.parsed.season,
                episode=video.parsed.primary_episode,
            )
            episode_titles[video.path] = episode_title
            tell(FileLookedUp(path=video.path, matched=episode_title is not None))
    tell(BuildFinished())

    title_of = _titles(found_groups)

    # Names, claimed in source-path order by the entries that will be applied.
    occupied: set[str] = set()
    for video in videos:
        title = title_of[video.path]
        desired = (
            _wanted_name(video, title.match, episode_titles.get(video.path), options)
            if title.match is not None
            else None
        )
        if desired is None:
            entries.append(
                _entry(video, destination=None, status=EntryStatus.NO_MATCH, title=title)
            )
            continue
        final = claim_name(desired, source=video.path, occupied=occupied, policy=options.name_taken)
        status = EntryStatus.READY if final == desired else EntryStatus.NAME_TAKEN
        entries.append(_entry(video, destination=final, status=status, title=title))

    by_pair: dict[tuple[str, str], PlanEntry] = {}
    for video_entry in sorted(entries, key=lambda e: path_key(e.source)):
        by_pair.setdefault(_pair_key(video_entry.source), video_entry)
    for sidecar in sorted(found, key=lambda f: path_key(f.path)):
        owner = by_pair.get(_pair_key(sidecar.path)) if sidecar.kind is FileKind.SIDECAR else None
        if owner is None:
            continue
        # A Sidecar whose video is not applied has its video's status; any other is
        # tested on its own, after its video.
        destination = None
        status = owner.status
        if owner.destination is not None:
            desired = owner.destination.with_suffix(sidecar.path.suffix.lower())
            destination = claim_name(
                desired, source=sidecar.path, occupied=occupied, policy=options.name_taken
            )
            status = EntryStatus.READY if destination == desired else EntryStatus.NAME_TAKEN
        entries.append(
            _entry(
                sidecar,
                destination=destination,
                status=status,
                title=owner.title,
                video=owner,
            )
        )

    entries.sort(key=lambda e: path_key(e.source))
    titles = sorted(set(title_of.values()), key=lambda t: (t.name.casefold(), t.year or 0))
    in_folder_source = {path_key(f.path) for f in found if f.in_folder_source}
    folders = _source_folders(
        e.source.parent for e in entries if path_key(e.source) in in_folder_source
    )
    plan = Plan(
        options=options,
        titles=tuple(titles),
        entries=tuple(entries),
        stragglers=plan_stragglers(options, entries, folders),
        source_folders=folders,
    )
    return PlanBuild(plan=plan, messages=tuple(messages))


def _source_folders(folders: Iterable[Path]) -> tuple[SourceFolder, ...]:
    """Each of ``folders`` once, in source-path order, with its direct children now.

    The folder that holds a file Source is never passed here, so the files beside a
    queued file are never Stragglers. A folder that cannot be listed has no children,
    with a logged warning.
    """
    unique = {path_key(folder): folder for folder in folders}
    recorded = []
    for key in sorted(unique):
        folder = unique[key]
        try:
            children = sorted(folder.iterdir(), key=path_key)
        except OSError as exc:
            _LOG.warning("Cannot list %s for Stragglers: %s", folder, exc)
            children = []
        is_folder = {child: child.is_dir(follow_symlinks=False) for child in children}
        recorded.append(
            SourceFolder(
                path=folder,
                files=tuple(c for c in children if not is_folder[c]),
                folders=tuple(c for c in children if is_folder[c]),
            )
        )
    return tuple(recorded)
