"""Plan the queued Sources: the one entry point that builds a Plan.

:func:`plan_queue` takes the queue, the plan options and the build's Provider, and
returns one Plan. It touches the filesystem only to list the Sources and to stat
their files; nothing is renamed.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
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
from termrenamer.core.templates import format_film_destination, format_tv_destination
from termrenamer.util.errors import ParseError

_LOG = logging.getLogger(__name__)

NO_TV_MATCH_BY_HAND = "Matching a not recognised TV file by hand is not available yet."
"""Why a not recognised TV file cannot be given a Match (ticket #14 will allow it)."""


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
    """A video or Sidecar of the queue, with the folder of its owning Source."""

    path: Path
    root: Path
    kind: FileKind


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
                _Found(path=f.path, root=resolved, kind=f.kind) for f in scan(root=resolved)
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
    wanted: Path | None = None,
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
        wanted=wanted,
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
    source: Path,
    root: Path,
    episode: tuple[int, int] | None,
    match: Candidate,
    episode_title: str | None,
    options: PlanOptions,
) -> Path | None:
    """The name today's templates give the video ``source`` for ``match``.

    ``episode`` is a TV video's season and first episode, ``None`` for a film; a TV
    video with no ``episode_title`` (its episode was not found) gets ``None``. A built
    and a derived Plan both name their videos here, so a name from a Provider always
    goes through the templates' cleaning of path separators and dots.
    """
    if options.mode is ScanMode.TV:
        if episode is None or episode_title is None:
            return None
        season, number = episode
        return format_tv_destination(
            root=root,
            parse=ParseResult(show_hint=match.name, season=season, episodes=(number,)),
            metadata=EpisodeMetadata(show_title=match.name, episode_title=episode_title),
            original_path=source,
            dest_root=options.destination_root,
            enable_folder_rename=options.folder_rename,
            enable_season_folders=options.season_folders,
        )
    if match.year is None:
        return None
    return format_film_destination(
        root=root,
        metadata=MovieMetadata(title=match.name, year=match.year),
        original_path=source,
        dest_root=options.destination_root,
        enable_folder_rename=options.folder_rename,
    )


def _episode_of(parsed: ParseResult | FilmParseResult) -> tuple[int, int] | None:
    """A parsed TV name's season and first episode; ``None`` for a film."""
    if isinstance(parsed, ParseResult):
        return (parsed.season, parsed.primary_episode)
    return None


def _recorded_episode(entry: PlanEntry) -> tuple[int, int] | None:
    """The season and first episode the build recorded for ``entry``; ``None`` for a film."""
    if entry.season is None or entry.episode is None:
        return None
    return (entry.season, entry.episode)


def _named_status(wanted: Path | None) -> EntryStatus:
    """A video's status before names are claimed: ready when it has a name, else no match."""
    return EntryStatus.READY if wanted is not None else EntryStatus.NO_MATCH


def _title_order(title: Title) -> tuple[str, int]:
    """Titles are listed by name, ignoring case, then by year."""
    return (title.name.casefold(), title.year or 0)


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
    exists, or it is a file that is not a video). ``listener`` is told each event of
    :mod:`termrenamer.core.progress` as the build runs; an exception it raises stops
    the build. ``cancel`` is checked before each lookup: once it is set, the build
    stops and returns ``None``.
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

    # Each video's wanted name; the names are claimed below, with the Sidecars'.
    for video in videos:
        title = title_of[video.path]
        wanted = (
            _wanted_name(
                video.path,
                video.root,
                _episode_of(video.parsed),
                title.match,
                episode_titles.get(video.path),
                options,
            )
            if title.match is not None
            else None
        )
        status = EntryStatus.NO_MATCH if wanted is None else EntryStatus.READY
        entries.append(_entry(video, destination=None, status=status, title=title, wanted=wanted))

    by_pair: dict[tuple[str, str], PlanEntry] = {}
    for video_entry in sorted(entries, key=lambda e: path_key(e.source)):
        by_pair.setdefault(_pair_key(video_entry.source), video_entry)
    for sidecar in sorted(found, key=lambda f: path_key(f.path)):
        owner = by_pair.get(_pair_key(sidecar.path)) if sidecar.kind is FileKind.SIDECAR else None
        if owner is None:
            continue
        entries.append(
            _entry(
                sidecar,
                destination=None,
                status=owner.status,
                title=owner.title,
                video=owner,
            )
        )

    titles = sorted(set(title_of.values()), key=_title_order)
    # Source-path order is fixed here, once; a derived Plan keeps it.
    entries.sort(key=lambda e: path_key(e.source))
    plan = _plan_of(options, tuple(titles), _claim_names(entries, options))
    return PlanBuild(plan=plan, messages=tuple(messages))


def _claim_names(entries: Sequence[PlanEntry], options: PlanOptions) -> tuple[PlanEntry, ...]:
    """Work out every entry's destination and status by claiming names across the Plan.

    ``entries`` are in source-path order, as the first build fixed it; that order is
    kept and no source is read again. Videos claim first, then Sidecars, and only
    entries that will be applied claim a name, so numbering is the same however the
    Plan was reached. A left out video, and one with no wanted name (no match, not
    recognised), keeps its status and gets no destination. Each wanted path is tested
    on disk again. A Sidecar whose video is not applied has its video's status; any
    other is tested on its own, under its video's new name.
    """
    ordered = tuple(entries)
    occupied: set[Path] = set()
    named: dict[Path, PlanEntry] = {}
    for entry in ordered:
        if entry.is_sidecar:
            continue
        if entry.status is EntryStatus.LEFT_OUT or entry.wanted is None:
            named[entry.source] = replace(entry, destination=None)
            continue
        final = claim_name(
            entry.wanted, source=entry.source, occupied=occupied, policy=options.name_taken
        )
        status = EntryStatus.READY if final == entry.wanted else EntryStatus.NAME_TAKEN
        named[entry.source] = replace(entry, destination=final, status=status)
    for entry in ordered:
        if not entry.is_sidecar:
            continue
        assert entry.video is not None
        # A Sidecar's ``video`` is its video entry's own ``source``, copied when the
        # Plan was built, so the key is the Plan's record, not a file on disk.
        owner = named[entry.video]
        if owner.destination is None:
            named[entry.source] = replace(entry, destination=None, status=owner.status)
            continue
        desired = owner.destination.with_suffix(entry.source.suffix.lower())
        final = claim_name(
            desired, source=entry.source, occupied=occupied, policy=options.name_taken
        )
        status = EntryStatus.READY if final == desired else EntryStatus.NAME_TAKEN
        named[entry.source] = replace(entry, destination=final, status=status)
    return tuple(named[entry.source] for entry in ordered)


def _plan_of(
    options: PlanOptions, titles: tuple[Title, ...], entries: tuple[PlanEntry, ...]
) -> Plan:
    """The Plan of ``entries`` whose names are claimed: the one place a built or a
    derived Plan is made.

    Stragglers are worked out here (#25), from the entries and the children each
    source folder had when the Plan was first built; the folders are not read again.
    """
    return Plan(options=options, titles=titles, entries=entries)


# --------------------------------------------------------------------------
# Derive a new Plan from a Plan and a change.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LeaveOut:
    """Leave ``video``, a video entry of the Plan, out of it; its Sidecars follow."""

    video: PlanEntry


@dataclass(frozen=True, slots=True)
class PutBack:
    """Put ``video``, a left out video entry of the Plan, back in it, with its Sidecars."""

    video: PlanEntry


@dataclass(frozen=True, slots=True)
class PickMatch:
    """Give ``target`` the Match ``match``, which the person picked.

    ``target`` is a Title of the Plan, or a not recognised Film video of it, which
    then forms a Title of its own or joins the Title that already has ``match``.
    ``found`` is the search the picker showed ``match`` from, in the Provider's order;
    the Title's Candidates become the other Candidates that search found. In TV Mode,
    ``episodes`` holds the episode title the picked show gives each of the Title's
    videos, by the source the Plan recorded, ``None`` where the episode was not found:
    :func:`look_up_episodes` asks the Provider for them before the Plan is derived.
    """

    target: Title | PlanEntry
    match: Candidate
    found: tuple[Candidate, ...] = ()
    episodes: Mapping[Path, str | None] = field(default_factory=dict)


PlanChange = LeaveOut | PutBack | PickMatch
"""A change the person makes to a Plan on the Preview."""


def derive_plan(plan: Plan, change: PlanChange) -> Plan:
    """The new Plan that ``plan`` becomes with ``change``; ``plan`` itself never changes.

    Destinations and Name taken are worked out again across the whole Plan, in
    source-path order, as a fresh build would: each wanted path is tested on disk
    again, a name that only a left out file had claimed is free for the next entry,
    and a video put back gets the status a fresh Plan gives it. No Provider is asked:
    a :class:`PickMatch` carries every answer it needs. The change names its entry or
    Title of ``plan`` itself, and the entries keep the order of ``plan``: the disk is
    read again only to test whether a wanted name is taken.

    Raises:
        ValueError: ``change`` names an entry or Title that is not in ``plan``, a
            Sidecar, a video that cannot be left out (no match, not recognised,
            already left out), for :class:`PutBack` a video that is not left out, or
            for :class:`PickMatch` a target that cannot be given that Match.
        OSError: testing a wanted path on disk failed.
    """
    if isinstance(change, PickMatch):
        titles, entries = _with_picked_match(plan, change)
        return _plan_of(plan.options, titles, _claim_names(entries, plan.options))
    video = change.video
    if video not in plan.entries:
        msg = f"{video.source} is not in the Plan."
        raise ValueError(msg)
    if video.is_sidecar:
        msg = f"{video.source} cannot be left out: it is a Sidecar, which follows its video."
        raise ValueError(msg)
    if isinstance(change, LeaveOut):
        if video.wanted is None or video.status is EntryStatus.LEFT_OUT:
            msg = f"{video.source} cannot be left out: it has the status {video.status.value}."
            raise ValueError(msg)
        status = EntryStatus.LEFT_OUT
    else:
        if video.status is not EntryStatus.LEFT_OUT:
            msg = f"{video.source} is not left out."
            raise ValueError(msg)
        # Worked out again when the names are claimed. A video whose picked show has
        # no such episode comes back with no match.
        status = _named_status(video.wanted)
    entries = tuple(
        replace(entry, status=status) if entry == video else entry for entry in plan.entries
    )
    return _plan_of(plan.options, plan.titles, _claim_names(entries, plan.options))


def _with_picked_match(
    plan: Plan, change: PickMatch
) -> tuple[tuple[Title, ...], tuple[PlanEntry, ...]]:
    """The Titles and entries of ``plan`` once ``change``'s target has its new Match.

    The target's videos take names from the Match; the Title that already had that
    Match, if any, becomes one Title with them. Entries stay in the Plan's order.
    """
    options, match = plan.options, change.match
    target = change.target
    if isinstance(target, Title):
        if target not in plan.titles:
            msg = f"{target.name} is not a Title of the Plan."
            raise ValueError(msg)
        videos = tuple(v for v in plan.videos if v.title == target)
    else:
        if target not in plan.entries or target.is_sidecar:
            msg = f"{target.source} is not a video of the Plan."
            raise ValueError(msg)
        if target.status is not EntryStatus.NOT_RECOGNISED:
            msg = f"{target.source} is not a not recognised file: pick a Match for its Title."
            raise ValueError(msg)
        if options.mode is ScanMode.TV:
            raise ValueError(NO_TV_MATCH_BY_HAND)
        videos = (target,)
    if options.mode is ScanMode.TV:
        missing = [v.source for v in videos if v.source not in change.episodes]
        if missing:
            msg = f"No episode title was looked up for {missing[0]}."
            raise ValueError(msg)
    elif match.year is None:
        msg = f"{match.name} has no year, so it cannot name a film."
        raise ValueError(msg)

    joined = next(
        (t for t in plan.titles if t != target and t.match is not None and t.match.id == match.id),
        None,
    )
    candidates = tuple(c for c in change.found if c.id != match.id)
    if joined is not None:
        joined_videos = tuple(v for v in plan.videos if v.title == joined)
        # The merged Title keeps the Candidates of the group whose title hint sorts
        # first; a not recognised file has no hint, so it joins the Title as it is.
        if not isinstance(target, Title) or _first_hint(joined_videos, options.mode) < _first_hint(
            videos, options.mode
        ):
            candidates = joined.candidates
        members = videos + joined_videos
    else:
        members = videos
    title = Title(
        name=match.name,
        year=match.year,
        seasons=tuple(sorted({v.season for v in members if v.season is not None})),
        match=match,
        candidates=candidates,
    )
    replaced = {t for t in (target, joined) if isinstance(t, Title)}
    moved = {v.source for v in videos}

    entries: list[PlanEntry] = []
    for entry in plan.entries:
        if entry.source in moved and not entry.is_sidecar:
            wanted = _wanted_name(
                entry.source,
                entry.root,
                _recorded_episode(entry),
                match,
                change.episodes.get(entry.source),
                options,
            )
            if entry.status is EntryStatus.LEFT_OUT:
                status = EntryStatus.LEFT_OUT  # the person's choice holds
            else:
                status = _named_status(wanted)
            entries.append(replace(entry, title=title, wanted=wanted, status=status))
        elif entry.title in replaced or (entry.is_sidecar and entry.video in moved):
            # A Sidecar's status follows its video when the names are claimed.
            entries.append(replace(entry, title=title))
        else:
            entries.append(entry)
    titles = [t for t in plan.titles if t not in replaced]
    titles.append(title)
    titles.sort(key=_title_order)
    return tuple(titles), tuple(entries)


def look_up_episodes(
    plan: Plan,
    title: Title,
    show: Candidate,
    provider: TvMetadataProvider,
    *,
    cancel: CancelSignal | None = None,
) -> dict[Path, str | None] | None:
    """The episode title ``show`` gives each video of ``title``, a TV Title of ``plan``.

    The answers are keyed by the source the Plan recorded for each video, ``None``
    where the episode is not found, ready for a :class:`PickMatch`. Each video's
    season and episode are the ones the Plan recorded. ``cancel`` is checked before
    each lookup: once it is set, the lookups stop and ``None`` is returned. A lookup
    failure raises :class:`~termrenamer.util.errors.ProviderError`.
    """
    lookup = _lookup(provider, ScanMode.TV)
    assert isinstance(lookup, TvLookup)
    episodes: dict[Path, str | None] = {}
    for video in plan.videos:
        if video.title != title or video.season is None or video.episode is None:
            continue
        if cancel is not None and cancel.is_set():
            return None
        episodes[video.source] = lookup.episode_title(
            show_id=show.id, season=video.season, episode=video.episode
        )
    return episodes


_TYPED_YEAR = re.compile(r"^(?P<hint>.*?\S)[\s(]+(?P<year>\d{4})\)?$")


def typed_hint(text: str) -> tuple[str, int | None]:
    """The title hint and year hint of a title the person typed.

    A four-digit year at the end of the text, after a space or in parentheses, is the
    year hint; the rest is the title hint. Text that is only a year is a title.
    """
    stripped = text.strip()
    found = _TYPED_YEAR.match(stripped)
    if found is None:
        return stripped, None
    return found["hint"].strip(), int(found["year"])


def search_typed(
    text: str, mode: ScanMode, provider: TvMetadataProvider | FilmMetadataProvider
) -> tuple[Candidate, ...]:
    """Search ``provider`` again for the title the person typed, in the Provider's order.

    It is an ordinary search, so a lookup with a cache stores it under the typed hint.
    A Film search with the year hint that finds nothing is tried once more without it,
    and a film without a year is dropped, as in a build. A TV search asks with the
    title hint alone; with a year hint, only the shows first aired that year are kept,
    or every show when none was. ``()`` is nothing found; a failure raises
    :class:`~termrenamer.util.errors.ProviderError`.
    """
    hint, year = typed_hint(text)
    lookup = _lookup(provider, mode)
    if isinstance(lookup, FilmLookup):
        films = lookup.search_films(hint=hint, year=year)
        return tuple(film for film in films if film.year is not None)
    shows = lookup.search_shows(hint=hint)
    that_year = tuple(show for show in shows if year is not None and show.year == year)
    return that_year or shows


def _first_hint(videos: Sequence[PlanEntry], mode: ScanMode) -> tuple[bool, tuple[str, int]]:
    """The group key that sorts first among ``videos``: their title hints read again
    from the recorded file names, with the year hint for Film, as the build grouped
    them. Only names are read, never the disk. A file the parser cannot read (one
    that was not recognised and was given its Match by hand) has no title hint; a
    group with no hint at all sorts after every group that has one."""
    keys = []
    for video in videos:
        try:
            parsed = _parse(video.source, mode)
        except ParseError:
            continue
        keys.append(_Video(path=video.source, root=video.root, parsed=parsed).group_key)
    return (False, min(keys)) if keys else (True, ("", 0))
