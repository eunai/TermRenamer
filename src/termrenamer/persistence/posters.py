"""The poster store: turns a Poster reference into a local image file, kept for 30 days.

A Poster reference comes from a Provider's answer, so it is not trusted: only a TMDB
poster path or an ``https`` address on TheTVDB's image host is accepted. The image is
downloaded from the Provider's image host, never its API host, with no key and no
header of the app's own. Each file is named by a hash of its address and written only
inside the store's folder; a body larger than :data:`MAX_POSTER_BYTES`, or one that is
not a JPEG, PNG or WebP image, is refused. With Pillow installed (the ``posters``
extra), a body is decoded whole before it is stored, so a stored file always draws.

The store keeps no Poster in memory, so several threads may fetch at once. A folder or
file the store cannot reach counts as no file, never as a crash. Before it reads,
writes or deletes a file, the store checks that its folder is a real folder (no link
and no junction) whose real place is inside the per-user cache folder; otherwise it
does nothing, logs one line for the run, and every Poster is "no poster".
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import io
import logging
import os
import re
import stat
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from termrenamer.util.errors import ProviderError, TermRenamerError
from termrenamer.util.http import Abandoned, HttpClient

_LOG = logging.getLogger(__name__)

MAX_AGE_SECONDS = 30 * 24 * 60 * 60.0
"""How long a Poster file is reused; older files are deleted at start."""

MAX_POSTER_BYTES = 5 * 1024 * 1024
"""The largest Poster file the store accepts."""

MAX_POSTER_PIXELS = 25_000_000
"""The most pixels a Poster may have; Provider posters have well under a million."""

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w342"
"""TMDB's documented image base with a fixed poster size (342 pixels wide)."""

TVDB_IMAGE_HOSTS = frozenset({"artworks.thetvdb.com"})
"""The hosts TheTVDB serves its images from."""

_TMDB_PATH = re.compile(r"/[A-Za-z0-9_-]{1,100}\.(?:jpg|jpeg|png|webp)")
_SUFFIX = ".poster"
_PART = ".part"
_STORED_NAME = re.compile(r"[0-9a-f]{64}(?:\.poster|\.[A-Za-z0-9_]{1,16}\.part)")


class PosterError(TermRenamerError):
    """A Poster cannot be shown: its reference was refused, or its download failed."""


class PosterFolderRefused(PosterError):
    """The poster folder is a link, or not inside the per-user cache folder; the store
    has logged it once and touches nothing."""


class PosterAbandoned(PosterError):
    """A download given up before it ended, because nobody wanted the Poster any more;
    it is no failure, and may be tried again."""


@dataclass(frozen=True, slots=True)
class PosterRequest:
    """A Provider's Poster reference, with the id of the Provider that gave it."""

    provider_id: str
    ref: str


def poster_address(request: PosterRequest) -> str:
    """The image address for ``request``, or :class:`PosterError` when it is refused.

    TMDB gives a path, which goes under its image base; TheTVDB gives an address,
    used as given when it is ``https`` on its image host. Other Providers give none.
    """
    ref = request.ref.strip()
    if request.provider_id == "tmdb":
        if _TMDB_PATH.fullmatch(ref) is None:
            raise PosterError("TMDB gave a Poster path the app does not accept")
        return TMDB_IMAGE_BASE + ref
    if request.provider_id == "tvdb":
        try:
            parts = urlsplit(ref)
            port = parts.port
        except ValueError as exc:
            raise PosterError("TheTVDB gave a Poster address the app does not accept") from exc
        if (
            parts.scheme != "https"
            or parts.hostname not in TVDB_IMAGE_HOSTS
            or parts.username is not None
            or parts.password is not None
            or port not in (None, 443)
            or not parts.path.strip("/")
        ):
            raise PosterError("TheTVDB gave a Poster address the app does not accept")
        return ref
    raise PosterError(f"Posters from {request.provider_id!r} are not shown")


def cache_folder() -> Path:
    """The per-user cache folder the poster folder is inside.

    Windows: ``%LOCALAPPDATA%``, or ``AppData\\Local`` in the home folder when
    ``LOCALAPPDATA`` is unset or empty. Every other platform: ``$XDG_CACHE_HOME``, or
    ``.cache`` in the home folder when ``XDG_CACHE_HOME`` is unset, empty or relative.
    """
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        return Path(local) if local else Path.home() / "AppData" / "Local"
    xdg = Path(os.environ.get("XDG_CACHE_HOME", ""))
    return xdg if xdg.is_absolute() else Path.home() / ".cache"


def poster_folder() -> Path:
    """The per-user folder Poster files go in: ``termrenamer/posters`` in
    :func:`cache_folder`. It does not depend on the lookup cache setting."""
    return cache_folder() / "termrenamer" / "posters"


def _folder_refusal(folder: Path, inside: Path) -> str | None:
    """Why the store may not use ``folder``, or ``None``: it must be no link and no
    junction, a folder when it exists, and its real place inside ``inside``'s."""
    try:
        if folder.is_symlink() or folder.is_junction():
            return "is a link"
        if folder.exists() and not folder.is_dir():
            return "is not a folder"
        real, real_inside = folder.resolve(), inside.resolve()
    except (OSError, RuntimeError) as exc:
        return f"cannot be checked ({exc})"
    # Compared as the system's paths compare: letter case counts except on Windows.
    if not real.is_relative_to(real_inside):
        return f"is not inside {inside}"
    return None


def _is_image(body: bytes) -> bool:
    """Whether ``body`` starts as a JPEG, PNG or WebP file does."""
    return (
        body.startswith(b"\xff\xd8\xff")
        or body.startswith(b"\x89PNG\r\n\x1a\n")
        or (body[:4] == b"RIFF" and body[8:12] == b"WEBP")
    )


def _decodes(body: bytes) -> bool:
    """Whether Pillow decodes ``body`` whole; ``True`` when Pillow is not installed."""
    try:
        pillow = importlib.import_module("PIL.Image")
    except ImportError:
        return True
    try:
        with pillow.open(io.BytesIO(body)) as image:
            if image.width * image.height > MAX_POSTER_PIXELS:
                return False
            image.load()
    except Exception:  # Pillow raises many kinds of error for a broken file
        return False
    return True


class PosterStore:
    """Poster files in ``folder``, downloaded through ``http``, aged by ``clock``.

    ``clock`` returns the time in seconds since the epoch; a file's age is the clock's
    time less the time the store wrote it.
    """

    def __init__(
        self,
        folder: Path,
        http: HttpClient,
        *,
        clock: Callable[[], float] = time.time,
        inside: Path | None = None,
    ) -> None:
        """``inside`` is the folder ``folder`` must really be in: the per-user cache
        folder for the app's store, and ``folder``'s parent when not given."""
        self._folder = folder
        self._http = http
        self._clock = clock
        self._inside = folder.parent if inside is None else inside
        self._refusal_logged = False
        self._lock = threading.Lock()

    @property
    def folder(self) -> Path:
        return self._folder

    def _refused(self) -> bool:
        """Whether the folder is refused now; the first refusal of the run logs a line."""
        reason = _folder_refusal(self._folder, self._inside)
        if reason is None:
            return False
        with self._lock:
            first, self._refusal_logged = not self._refusal_logged, True
        if first:
            _LOG.warning("Posters are not stored: the poster folder %s %s", self._folder, reason)
        return True

    def _path_for(self, address: str) -> Path:
        return self._folder / (hashlib.sha256(address.encode("utf-8")).hexdigest() + _SUFFIX)

    def _fresh(self, path: Path) -> bool:
        """Whether ``path`` is a file younger than 30 days; ``False`` when unreachable."""
        try:
            status = path.stat()
        except OSError:
            return False
        return stat.S_ISREG(status.st_mode) and self._young(status)

    def _young(self, status: os.stat_result) -> bool:
        return self._clock() - status.st_mtime < MAX_AGE_SECONDS

    def stored(self, request: PosterRequest) -> Path | None:
        """The file for ``request`` when the store has one younger than 30 days.

        Nothing is downloaded; a refused reference has no file.
        """
        try:
            path = self._path_for(poster_address(request))
        except PosterError:
            return None
        if self._refused():
            return None
        return path if self._fresh(path) else None

    def fetch(self, request: PosterRequest, *, go_on: Callable[[], bool] | None = None) -> Path:
        """The file for ``request``: the stored one while young, else downloaded now.

        Blocks while it downloads, so call it off the screen's thread. Before each new
        attempt of the download, ``go_on`` is asked whether the Poster is still wanted.

        Raises:
            PosterAbandoned: ``go_on`` said no before a new attempt.
            PosterError: The reference was refused, the download failed, or the body
                is too large or not an image.
        """
        address = poster_address(request)
        path = self._path_for(address)
        if self._refused():
            raise PosterFolderRefused("the poster folder is refused")
        if self._fresh(path):
            return path
        try:
            download = self._http.download(address, max_bytes=MAX_POSTER_BYTES, go_on=go_on)
        except Abandoned as exc:
            raise PosterAbandoned(str(exc)) from exc
        except (ProviderError, httpx.HTTPError) as exc:
            raise PosterError(f"download failed: {exc}") from exc
        kind = download.content_type.split(";", 1)[0].strip().lower()
        body = download.content
        if (kind and not kind.startswith("image/")) or not _is_image(body) or not _decodes(body):
            raise PosterError("the download is not an image")
        if self._refused():
            raise PosterFolderRefused("the poster folder is refused")
        try:
            self._write(path, body)
        except OSError as exc:
            raise PosterError(f"cannot store the Poster: {exc}") from exc
        return path

    def _write(self, path: Path, body: bytes) -> None:
        """Write ``body`` to ``path`` through a temporary file beside it."""
        self._folder.mkdir(parents=True, exist_ok=True)
        if self._refused():  # made through a link since the last check
            raise OSError("the poster folder is refused")
        handle, temporary = tempfile.mkstemp(dir=self._folder, prefix=path.stem + ".", suffix=_PART)
        try:
            with os.fdopen(handle, "wb") as out:
                out.write(body)
            now = self._clock()
            os.utime(temporary, (now, now))
            os.replace(temporary, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise

    def remove_old(self) -> int:
        """Delete the store's files older than 30 days; return how many were deleted.

        Only files the store names are touched; anything else in the folder stays, and
        so does a file whose age cannot be read.
        """
        if self._refused():
            return 0
        try:
            entries = list(self._folder.iterdir())
        except OSError:
            return 0
        removed = 0
        for entry in entries:
            if _STORED_NAME.fullmatch(entry.name) is None:
                continue
            try:
                status = entry.stat()
            except OSError:
                continue
            if not stat.S_ISREG(status.st_mode) or self._young(status):
                continue
            with contextlib.suppress(OSError):
                entry.unlink()
                removed += 1
        return removed
