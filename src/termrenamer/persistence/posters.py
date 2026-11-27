"""The poster store: turns a Poster reference into a local image file, kept for 30 days.

A Poster reference comes from a Provider's answer, so it is not trusted: only a TMDB
poster path or an ``https`` address on TheTVDB's image host is accepted. The image is
downloaded from the Provider's image host, never its API host, with no key and no
header of the app's own. Each file is named by a hash of its address and written only
inside the store's folder; a body larger than :data:`MAX_POSTER_BYTES`, or one that is
not a JPEG, PNG or WebP image, is refused.

The store keeps no state in memory, so several threads may fetch at once.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from termrenamer.util.errors import ProviderError, TermRenamerError
from termrenamer.util.http import HttpClient

MAX_AGE_SECONDS = 30 * 24 * 60 * 60.0
"""How long a Poster file is reused; older files are deleted at start."""

MAX_POSTER_BYTES = 5 * 1024 * 1024
"""The largest Poster file the store accepts."""

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


def poster_folder() -> Path:
    """The per-user folder Poster files go in.

    Windows: ``%LOCALAPPDATA%\\termrenamer\\posters``, or ``AppData\\Local`` in the home
    folder when ``LOCALAPPDATA`` is unset or empty. Every other platform:
    ``$XDG_CACHE_HOME/termrenamer/posters``, or ``.cache`` in the home folder when
    ``XDG_CACHE_HOME`` is unset, empty or relative. It does not depend on the lookup
    cache setting.
    """
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
    else:
        xdg = Path(os.environ.get("XDG_CACHE_HOME", ""))
        base = xdg if xdg.is_absolute() else Path.home() / ".cache"
    return base / "termrenamer" / "posters"


def _is_image(body: bytes) -> bool:
    """Whether ``body`` starts as a JPEG, PNG or WebP file does."""
    return (
        body.startswith(b"\xff\xd8\xff")
        or body.startswith(b"\x89PNG\r\n\x1a\n")
        or (body[:4] == b"RIFF" and body[8:12] == b"WEBP")
    )


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
    ) -> None:
        self._folder = folder
        self._http = http
        self._clock = clock

    @property
    def folder(self) -> Path:
        return self._folder

    def _path_for(self, address: str) -> Path:
        return self._folder / (hashlib.sha256(address.encode("utf-8")).hexdigest() + _SUFFIX)

    def _young(self, path: Path) -> bool:
        try:
            written = path.stat().st_mtime
        except OSError:
            return False
        return self._clock() - written < MAX_AGE_SECONDS

    def stored(self, request: PosterRequest) -> Path | None:
        """The file for ``request`` when the store has one younger than 30 days.

        Nothing is downloaded; a refused reference has no file.
        """
        try:
            path = self._path_for(poster_address(request))
        except PosterError:
            return None
        return path if path.is_file() and self._young(path) else None

    def fetch(self, request: PosterRequest) -> Path:
        """The file for ``request``: the stored one while young, else downloaded now.

        Blocks while it downloads, so call it off the screen's thread.

        Raises:
            PosterError: The reference was refused, the download failed, or the body
                is too large or not an image.
        """
        address = poster_address(request)
        path = self._path_for(address)
        if path.is_file() and self._young(path):
            return path
        try:
            download = self._http.download(address, max_bytes=MAX_POSTER_BYTES)
        except (ProviderError, httpx.HTTPError) as exc:
            raise PosterError(f"download failed: {exc}") from exc
        kind = download.content_type.split(";", 1)[0].strip().lower()
        if (kind and not kind.startswith("image/")) or not _is_image(download.content):
            raise PosterError("the download is not an image")
        try:
            self._write(path, download.content)
        except OSError as exc:
            raise PosterError(f"cannot store the Poster: {exc}") from exc
        return path

    def _write(self, path: Path, body: bytes) -> None:
        """Write ``body`` to ``path`` through a temporary file beside it."""
        self._folder.mkdir(parents=True, exist_ok=True)
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

        Only files the store names are touched; anything else in the folder stays.
        """
        try:
            entries = list(self._folder.iterdir())
        except OSError:
            return 0
        removed = 0
        for entry in entries:
            if _STORED_NAME.fullmatch(entry.name) is None or not entry.is_file():
                continue
            if self._young(entry):
                continue
            with contextlib.suppress(OSError):
                entry.unlink()
                removed += 1
        return removed
