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
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from textual.widget import Widget

from termrenamer.persistence.posters import PosterRequest, PosterStore

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


@dataclass(frozen=True, slots=True)
class PosterSource:
    """Where the screen's Posters come from while they are shown: the poster store, the
    image widget that draws a stored file, and the requests that failed this session
    (a failed download or an unreadable file), which every view leaves as "no poster"."""

    store: PosterStore
    image: ImageFactory
    failed: set[PosterRequest] = field(default_factory=set)
