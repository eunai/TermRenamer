"""Whether this run can show Posters: the ``posters`` extra, and a terminal that draws images.

Posters are drawn by the ``textual-image`` package, installed only with the ``posters``
extra (decision record 0001). Importing it asks the terminal, once, whether it draws
Sixel or Kitty images; that question cannot be asked after the screen takes over the
terminal, so :func:`detect_poster_support` runs at start, before the app does. The
package's character-block fallbacks are never used: a terminal that draws neither
protocol has no Posters.
"""

from __future__ import annotations

import importlib
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from textual.widget import Widget

from termrenamer.persistence.posters import (
    PosterAbandoned,
    PosterError,
    PosterFolderRefused,
    PosterRequest,
    PosterStore,
)

_LOG = logging.getLogger(__name__)

NOT_INSTALLED = "the posters extra is not installed"
NO_IMAGES = "this terminal draws neither Sixel nor Kitty images"

ErrorWidget = Callable[[Exception], Widget]
"""Makes the widget shown in place of an image that cannot be read."""

ImageFactory = Callable[[Path, ErrorWidget], Widget]
"""Makes the widget that draws the image file at a path, with what to show on error."""


@dataclass(frozen=True, slots=True)
class PosterSupport:
    """The image widget to draw Posters with, or the reason there are none.

    ``reason`` is meaningful only while ``image`` is ``None``.
    """

    image: ImageFactory | None = None
    reason: str = NOT_INSTALLED

    @property
    def available(self) -> bool:
        return self.image is not None


def _load_textual_image() -> tuple[Any, Any]:
    """Import the image package; the first import asks the terminal what it draws."""
    renderable: ModuleType = importlib.import_module("textual_image.renderable")
    widget: ModuleType = importlib.import_module("textual_image.widget")
    return renderable, widget


def detect_poster_support(
    load: Callable[[], tuple[Any, Any]] = _load_textual_image,
) -> PosterSupport:
    """Check, once at start, whether Posters can be drawn here, and with which widget.

    ``load`` returns the package's ``renderable`` and ``widget`` modules; a test passes
    stand-ins. Sixel is drawn with the package's Sixel widget and the Kitty protocol
    with its TGP widget; anything else the package chose is a fallback, never used.
    """
    try:
        renderable, widget = load()
    except ImportError:
        return PosterSupport(reason=NOT_INSTALLED)
    except Exception as exc:  # the check must never stop the app from starting
        _LOG.warning("The terminal check for Posters failed: %s", exc)
        return PosterSupport(reason=f"the terminal check failed ({exc})")
    chosen = getattr(renderable, "Image", None)
    if chosen is not None and chosen is getattr(renderable, "SixelImage", None):
        image_class = widget.SixelImage
    elif chosen is not None and chosen is getattr(renderable, "TGPImage", None):
        image_class = widget.TGPImage
    else:
        return PosterSupport(reason=NO_IMAGES)

    def make(path: Path, on_error: ErrorWidget) -> Widget:
        made: Widget = image_class(path, on_error=on_error)
        return made

    return PosterSupport(image=make)


_FAILED_EARLIER = "an earlier download of this Poster failed this run"


@dataclass(slots=True)
class _Download:
    """One download in progress: who still wants it, and its error once it failed."""

    wants: list[Callable[[], bool]]
    done: threading.Event = field(default_factory=threading.Event)
    error: str | None = None

    def wanted(self) -> bool:
        return any(want() for want in list(self.wants))


@dataclass(frozen=True, slots=True)
class PosterSource:
    """Where the screen's Posters come from while they are shown: the poster store, the
    image widget that draws a stored file, and the requests that failed this run (a
    failed download or an unreadable file), which every view leaves as "no poster".
    It downloads each Poster once at a time, for every view that asks, and records how
    the download ended itself, whether or not a view is still there to see it."""

    store: PosterStore
    image: ImageFactory
    failed: set[PosterRequest] = field(default_factory=set)
    _downloads: dict[PosterRequest, _Download] = field(
        default_factory=dict, repr=False, compare=False
    )
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def fetch(self, request: PosterRequest, *, name: str, wanted: Callable[[], bool]) -> None:
        """Store the file for ``request``, the Poster of the Title ``name``, downloading
        it when it is not stored. Blocks, so call it off the screen's thread.

        While one download of ``request`` runs, a second call joins it and ends as it
        does, so two views never download one Poster twice. A download that fails (an
        error status, a body that is not an image, a file that cannot be stored) is
        added to :attr:`failed` and logged in one line, here, before a new call can
        start another; a call for a request already in :attr:`failed` sends nothing.
        Before each attempt the download asks ``wanted`` of every call that joined it;
        when none still wants the Poster it is given up, records nothing, and a later
        call tries again.

        Raises:
            PosterError: The download failed or was given up.
        """
        with self._lock:
            if request in self.failed:  # failed since the caller looked: no new try
                raise PosterError(_FAILED_EARLIER)
            running = self._downloads.get(request)
            if running is None:
                download = self._downloads[request] = _Download([wanted])
            else:
                running.wants.append(wanted)
        if running is not None:
            running.done.wait()
            if running.error is not None:
                raise PosterError(running.error)
            return
        error: str | None = None
        logged = False  # the store logs a refused folder itself, once
        try:
            self.store.fetch(request, go_on=download.wanted)
        except PosterAbandoned as exc:
            download.error = str(exc)
            raise
        except Exception as exc:  # a Poster never stops the screen
            error = str(exc) if isinstance(exc, PosterError) else f"{type(exc).__name__}: {exc}"
            logged = isinstance(exc, PosterFolderRefused)
            download.error = error
            raise PosterError(error) from exc
        finally:
            with self._lock:
                if error is not None:
                    self._record_failure(request, name, error, log=not logged)
                del self._downloads[request]
            download.done.set()

    def record_failure(self, request: PosterRequest, name: str, why: str) -> None:
        """Remember that ``request`` failed for the run, and log it once, for the Title
        ``name``: every view then leaves "no poster"."""
        with self._lock:
            self._record_failure(request, name, why, log=True)

    def _record_failure(self, request: PosterRequest, name: str, why: str, *, log: bool) -> None:
        if request in self.failed:
            return
        self.failed.add(request)
        if log:
            _LOG.warning("No Poster for %s: %s", name, why)
