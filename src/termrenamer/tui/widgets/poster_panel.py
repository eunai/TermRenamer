"""The poster panel: one Poster in a fixed frame, with the Provider's name on its border.

:class:`PosterView` draws one Poster, or in its place the Title's name and a word such
as "no poster". It asks the poster store for the file: a stored file is drawn at once;
otherwise, when downloads are allowed, the store downloads it on a thread of its own,
never on the screen's. A failed download logs one line and leaves "no poster".

While Posters are hidden or unavailable the view is given no :class:`PosterSource`:
it then draws nothing, removes its image and downloads nothing. While it is paused (its
Stage is not shown, or a dialog covers it) it draws the Title's name in place of the
image and downloads nothing; a dialog's backdrop would otherwise tint the image's cells,
which breaks a Kitty image. :class:`PosterPanel` frames one view at the mockup's 24 by
17 cells.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.markup import escape
from textual.widget import Widget
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from termrenamer.persistence.posters import PosterError, PosterRequest
from termrenamer.tui.poster_support import PosterSource

_LOG = logging.getLogger(__name__)

POSTER_WIDTH = 24
POSTER_HEIGHT = 17
"""The Poster's cells inside the panel's frame, as in the mockup."""

NO_POSTER = "no poster"


@dataclass(frozen=True, slots=True)
class _Wanted:
    """What the view was last asked to show."""

    name: str
    request: PosterRequest | None
    label: str
    download: bool


@dataclass(frozen=True, slots=True)
class _Fetched:
    """A download's outcome, handed from its thread to the screen."""

    request: PosterRequest
    error: str | None


def placeholder(
    name: str, label: str, width: int = POSTER_WIDTH, height: int = POSTER_HEIGHT
) -> str:
    """The panel without an image (Textual markup): a faint dot pattern, with the Title's
    name and ``label`` in its middle."""
    rows = []
    for i in range(height):
        rows.append(
            "".join(
                "·" if i % 2 == 1 and (j + (0 if i % 4 == 1 else 2)) % 4 == 1 else " "
                for j in range(width)
            )
        )
    lines = [f"[$tr-line]{row}[/]" for row in rows]
    middle = height // 2 - 1

    def centred(text: str, style: str) -> str:
        cut = text if len(text) <= width - 2 else text[: width - 3] + "…"
        padded = f" {cut} "
        left = (width - len(padded)) // 2
        right = width - left - len(padded)
        row = rows[middle]
        return (
            f"[$tr-line]{row[:left]}[/][{style}]{escape(padded)}[/]"
            f"[$tr-line]{row[left + len(padded) :] if right else ''}[/]"
        )

    if name:
        lines[middle] = centred(name, "b $foreground")
    if label:
        lines[middle + 1] = centred(label, "$tr-dim")
    return "\n".join(lines)


class PosterView(Vertical):
    """One Poster, or the Title's name and a word in its place."""

    DEFAULT_CSS = f"""
    PosterView {{
        width: {POSTER_WIDTH};
        height: {POSTER_HEIGHT};
        align-horizontal: center;
    }}
    PosterView > .poster-text {{
        width: {POSTER_WIDTH};
        height: {POSTER_HEIGHT};
    }}
    PosterView > .poster-image {{
        width: auto;
        height: {POSTER_HEIGHT};
    }}
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._source: PosterSource | None = None
        self._wanted: _Wanted | None = None
        self._image: Widget | None = None
        self._image_request: PosterRequest | None = None
        self._paused = False
        self._fetches: dict[Worker[_Fetched], PosterRequest] = {}
        self._failed: set[PosterRequest] = set()

    def compose(self) -> ComposeResult:
        yield Static("", classes="poster-text")

    @property
    def text(self) -> Static:
        return self.query_one(".poster-text", Static)

    @property
    def image(self) -> Widget | None:
        """The image widget on screen now, or ``None``."""
        return self._image

    def use(self, source: PosterSource | None) -> None:
        """Show Posters from ``source``, or, for ``None``, nothing: no image, no download."""
        self._source = source
        if source is None:
            self._drop_image()
            self.text.update("")
            return
        self._draw()

    def show(
        self, name: str, request: PosterRequest | None, *, label: str = "", download: bool
    ) -> None:
        """Show the Poster of ``request`` for the Title ``name``.

        Without a request, the name and ``label`` (or "no poster") are drawn. A stored
        file is drawn at once. Otherwise, with ``download``, the file is downloaded off
        the screen's thread while the name is drawn; without it, the name and ``label``.
        """
        self._wanted = _Wanted(name, request, label, download)
        self._draw()

    def clear(self) -> None:
        """Show nothing until the next :meth:`show`."""
        self._wanted = None
        self._draw()

    def pause(self, paused: bool) -> None:
        """While ``paused``, draw the name in place of the image and download nothing."""
        if paused != self._paused:
            self._paused = paused
            self._draw()

    # ------------------------------------------------------------------ drawing

    def _draw(self) -> None:
        source, wanted = self._source, self._wanted
        if source is None:
            return
        if wanted is None:
            self._drop_image()
            self.text.update("")
            return
        request = wanted.request
        if request is None or request in self._failed:
            self._words(
                wanted.name, wanted.label if request is None and wanted.label else NO_POSTER
            )
            return
        if self._paused:
            self._words(wanted.name, wanted.label)
            return
        if request == self._image_request and self._image is not None:
            return
        path = source.store.stored(request)
        if path is not None:
            self._drop_image()
            self.text.display = False
            image = source.image(path, lambda exc: self._unreadable(request, wanted.name, exc))
            image.add_class("poster-image")
            self._image, self._image_request = image, request
            self.mount(image)
            return
        if not wanted.download:
            self._words(wanted.name, wanted.label)
            return
        self._words(wanted.name, "")
        if request not in self._fetches.values():
            store = source.store

            def fetch() -> _Fetched:
                try:
                    store.fetch(request)
                except PosterError as exc:
                    return _Fetched(request, str(exc))
                except Exception as exc:  # a Poster never stops the screen
                    return _Fetched(request, f"{type(exc).__name__}: {exc}")
                return _Fetched(request, None)

            worker = self.run_worker(fetch, thread=True, group="poster", exit_on_error=False)
            self._fetches[worker] = request

    def _words(self, name: str, label: str) -> None:
        self._drop_image()
        self.text.display = True
        self.text.update(placeholder(name, label))

    def _drop_image(self) -> None:
        image, self._image, self._image_request = self._image, None, None
        if image is None:
            return
        # Clearing the image first lets the package take its picture off the terminal.
        with contextlib.suppress(Exception):
            image.image = None  # type: ignore[attr-defined]
        image.remove()

    def _unreadable(self, request: PosterRequest, name: str, exc: Exception) -> Widget:
        """The image widget cannot read the stored file: the panel says "no poster"."""
        _LOG.warning("No Poster for %s: the file cannot be read (%s)", name, exc)
        self._failed.add(request)
        # Called while the image widget draws, so the panel changes once that is done.
        self.call_later(self._draw)
        return Static("")

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group != "poster":
            return
        event.stop()
        if event.state not in (WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED):
            return
        request = self._fetches.pop(event.worker, None)
        if request is None:
            return
        wanted = self._wanted
        is_wanted = wanted is not None and wanted.request == request
        fetched = event.worker.result if event.state is WorkerState.SUCCESS else None
        if event.state is WorkerState.ERROR:
            fetched = _Fetched(request, str(event.worker.error))
        if isinstance(fetched, _Fetched) and fetched.error is not None:
            self._failed.add(request)
            name = wanted.name if wanted is not None and is_wanted else request.ref
            _LOG.warning("No Poster for %s: %s", name, fetched.error)
        if is_wanted:
            self._draw()


class PosterPanel(Vertical):
    """The framed panel: one :class:`PosterView`, the Provider's name on the border."""

    DEFAULT_CSS = f"""
    PosterPanel {{
        width: {POSTER_WIDTH + 2};
        height: {POSTER_HEIGHT + 2};
        border: solid $tr-line;
        border-title-color: $tr-dim;
        border-title-align: left;
    }}
    """

    def compose(self) -> ComposeResult:
        yield PosterView()

    @property
    def view(self) -> PosterView:
        return self.query_one(PosterView)

    def show(
        self,
        name: str,
        request: PosterRequest | None,
        *,
        provider: str,
        label: str = "",
        download: bool,
    ) -> None:
        """Show ``request``'s Poster for ``name``, with ``provider`` on the border."""
        self.border_title = escape(provider)
        self.view.show(name, request, label=label, download=download)
