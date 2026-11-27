"""The poster panel: one Poster in a fixed frame, with the Provider's name on its border.

:class:`PosterView` draws one Poster, or in its place the Title's name and a word such
as "no poster". It asks the poster store for the file: a stored file is drawn at once;
otherwise, when downloads are allowed, it is downloaded on a thread of its own, never
on the screen's, and a view that asks for a Poster already on its way joins it. How a
download ends is recorded by the :class:`PosterSource`, not the view: a failure logs one
line and is remembered for the run, for every view, even when the view that asked has
gone; each view only redraws. A stored file the image widget cannot read is remembered
and logged the same way, and every view leaves "no poster" for either.

While Posters are hidden or unavailable the view is given no :class:`PosterSource`:
it then draws nothing, removes its image and starts no download. While it is paused
(its Stage is not shown, or a dialog covers it) it draws the Title's name in place of
the image and starts no download; a dialog's backdrop would otherwise tint the image's
cells, which breaks a Kitty image. A download already running makes no new attempt
once no view may still fetch it (shown, not paused, still asking); an answer already
on its way may finish and be stored.
:class:`PosterPanel` frames one view at the mockup's 24 by 17 cells, and
:func:`keep_clear_of_posters` keeps a dialog to its right.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.content import Content
from textual.widget import Widget
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from termrenamer.persistence.posters import PosterError, PosterRequest
from termrenamer.tui.poster_support import PosterSource
from termrenamer.tui.words import provider_name

_LOG = logging.getLogger(__name__)

POSTER_WIDTH = 24
POSTER_HEIGHT = 17
"""The Poster's cells inside the panel's frame, as in the mockup."""

PANEL_WIDTH = POSTER_WIDTH + 2
PANEL_HEIGHT = POSTER_HEIGHT + 2
"""The panel's columns and rows, its frame included."""

PANEL_LEFT = 3
"""The columns left of the panel."""

PANEL_RIGHT = PANEL_LEFT + PANEL_WIDTH
"""The first column right of the panel."""

_NARROWEST_DIALOG = 20

NO_POSTER = "no poster"


@dataclass(frozen=True, slots=True)
class _Wanted:
    """What the view was last asked to show."""

    name: str
    request: PosterRequest | None
    label: str
    download: bool


def placeholder(
    name: str, label: str, width: int = POSTER_WIDTH, height: int = POSTER_HEIGHT
) -> Content:
    """The panel without an image: a faint dot pattern, with the Title's name and
    ``label`` in its middle, each as written."""
    rows = []
    for i in range(height):
        rows.append(
            "".join(
                "·" if i % 2 == 1 and (j + (0 if i % 4 == 1 else 2)) % 4 == 1 else " "
                for j in range(width)
            )
        )
    lines = [Content.from_markup("[$tr-line]$row[/]", row=row) for row in rows]
    middle = height // 2 - 1

    def centred(text: str, style: str) -> Content:
        cut = text if len(text) <= width - 2 else text[: width - 3] + "…"
        padded = f" {cut} "
        left = (width - len(padded)) // 2
        right = width - left - len(padded)
        row = rows[middle]
        return Content.from_markup(
            f"[$tr-line]$before[/][{style}]$text[/][$tr-line]$after[/]",
            before=row[:left],
            text=padded,
            after=row[left + len(padded) :] if right else "",
        )

    if name:
        lines[middle] = centred(name, "b $foreground")
    if label:
        lines[middle + 1] = centred(label, "$tr-dim")
    return Content("\n").join(lines)


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

    def __init__(
        self, *, cells: tuple[int, int] = (POSTER_WIDTH, POSTER_HEIGHT), **kwargs: object
    ) -> None:
        """``cells`` is the Poster's width and height in cells."""
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._cells = cells
        if cells != (POSTER_WIDTH, POSTER_HEIGHT):
            self.styles.width, self.styles.height = cells
        self._source: PosterSource | None = None
        self._wanted: _Wanted | None = None
        self._image: Widget | None = None
        self._image_request: PosterRequest | None = None
        self._paused = False
        self._fetches: dict[Worker[None], PosterRequest] = {}

    def compose(self) -> ComposeResult:
        text = Static("", classes="poster-text")
        text.styles.width, text.styles.height = self._cells
        yield text

    @property
    def text(self) -> Static:
        return self.query_one(".poster-text", Static)

    @property
    def image(self) -> Widget | None:
        """The image widget on screen now, or ``None``."""
        return self._image

    def use(self, source: PosterSource | None) -> None:
        """Show Posters from ``source``, or, for ``None``, nothing: no image, and no
        download starts."""
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
        """While ``paused``, draw the name in place of the image and start no download."""
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
        if request is None or request in source.failed:
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
            image = source.image(path, lambda exc: self._unreadable(source, request, wanted, exc))
            image.add_class("poster-image")
            image.styles.height = self._cells[1]
            self._image, self._image_request = image, request
            self.mount(image)
            return
        if not wanted.download:
            self._words(wanted.name, wanted.label)
            return
        self._words(wanted.name, "")
        if request not in self._fetches.values():
            name = wanted.name

            def fetch() -> None:
                with contextlib.suppress(PosterError):
                    source.fetch(request, name=name, wanted=lambda: self._wants(source, request))

            worker = self.run_worker(fetch, thread=True, group="poster", exit_on_error=False)
            self._fetches[worker] = request

    def _wants(self, source: PosterSource, request: PosterRequest) -> bool:
        """Whether the view may still download ``request``: attached, shown with
        ``source``, not paused, and still asked for it. Asked from the download's
        thread, before each new attempt."""
        wanted = self._wanted
        return (
            self.is_attached
            and self._source is source
            and not self._paused
            and wanted is not None
            and wanted.download
            and wanted.request == request
        )

    def _words(self, name: str, label: str) -> None:
        self._drop_image()
        self.text.display = True
        self.text.update(placeholder(name, label, *self._cells))

    def _drop_image(self) -> None:
        image, self._image, self._image_request = self._image, None, None
        if image is None:
            return
        # Clearing the image first lets the package take its picture off the terminal.
        with contextlib.suppress(Exception):
            image.image = None  # type: ignore[attr-defined]
        image.remove()

    def _unreadable(
        self, source: PosterSource, request: PosterRequest, wanted: _Wanted, exc: Exception
    ) -> Widget:
        """The image widget cannot read the stored file: the panel says "no poster"."""
        if request not in source.failed:
            source.failed.add(request)
            _LOG.warning("No Poster for %s: the file cannot be read (%s)", wanted.name, exc)
        # Called while the image widget draws, so the panel changes once that is done.
        self.call_later(self._draw)
        return Static("")

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """A download ended: its outcome is recorded by the source, so the view only
        redraws when it still wants that Poster."""
        if event.worker.group != "poster":
            return
        event.stop()
        if event.state not in (WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED):
            return
        request = self._fetches.pop(event.worker, None)
        wanted = self._wanted
        if request is not None and wanted is not None and wanted.request == request:
            self._draw()


class PosterPanel(Vertical):
    """The framed panel: one :class:`PosterView`, the Provider's name on the border."""

    DEFAULT_CSS = f"""
    PosterPanel {{
        width: {PANEL_WIDTH};
        height: {PANEL_HEIGHT};
        margin: 0 0 0 {PANEL_LEFT};
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

    def use(self, source: PosterSource | None) -> None:
        """See :meth:`PosterView.use`."""
        self.view.use(source)

    def pause(self, paused: bool) -> None:
        """See :meth:`PosterView.pause`."""
        self.view.pause(paused)

    def clear(self) -> None:
        """See :meth:`PosterView.clear`."""
        self.view.clear()

    def show(
        self,
        name: str,
        *,
        provider_id: str,
        ref: str | None,
        label: str = "",
        download: bool,
    ) -> None:
        """Show the Poster the Provider ``provider_id`` gave as ``ref`` (or none) for the
        Title ``name``, with the Provider's name on the border."""
        self.border_title = Content(provider_name(provider_id))
        request = PosterRequest(provider_id, ref) if ref else None
        self.view.show(name, request, label=label, download=download)


def _panel_shows(app: App[object]) -> bool:
    """Whether a poster panel shows on the main screen, on the Stage shown there."""
    panels = app.screen_stack[0].query(PosterPanel)
    return any(all(node.display for node in panel.ancestors_with_self) for panel in panels)


def room_beside_posters(app: App[object]) -> int:
    """The columns a dialog has: those right of the poster panel while it shows on the
    main screen, else the whole screen's width."""
    width = app.size.width
    return width - PANEL_RIGHT if _panel_shows(app) else width


def keep_clear_of_posters(dialog: Widget) -> None:
    """Keep ``dialog`` right of the poster panel while the panel shows on the main screen
    below it (on the Stage shown there), or let it take its stylesheet's place while it
    does not. A dialog calls this when it mounts and on every resize; its stylesheet
    gives it no left margin."""
    app = dialog.app
    dialog.styles.clear_rule("margin")
    if _panel_shows(app):
        margin = dialog.styles.margin
        dialog.styles.margin = (margin.top, margin.right, margin.bottom, PANEL_RIGHT)
        room = app.size.width - PANEL_RIGHT - margin.right
        dialog.styles.max_width = max(room, _NARROWEST_DIALOG)
    else:
        dialog.styles.max_width = None  # back to the stylesheet's
