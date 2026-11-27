"""What the Plan and Preview Stages share: a "Titles" heading with its count over a Title
list, and the poster panel on the left while Posters are shown."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from termrenamer.tui.poster_support import PosterSource
from termrenamer.tui.stages.base import StageView
from termrenamer.tui.widgets.poster_panel import PosterPanel
from termrenamer.tui.widgets.title_list import TitleList


class TitleListStage(StageView):
    """A Stage whose body is the Title list; ``↑`` ``↓`` select a row."""

    DEFAULT_CSS = """
    TitleListStage .stage-body {
        height: 1fr;
        padding: 1 2 0 2;
    }
    TitleListStage .list-heading {
        height: 2;
        border-bottom: solid $tr-line;
    }
    TitleListStage .list-heading Static {
        width: 1fr;
        text-style: bold;
        padding: 0 2;
    }
    TitleListStage .list-heading .list-count {
        width: auto;
        color: $tr-dim;
        text-style: none;
    }
    TitleListStage PosterPanel {
        display: none;
        margin: 0 0 0 3;
    }
    TitleListStage.-posters PosterPanel {
        display: block;
    }
    """

    @property
    def posters_shown(self) -> bool:
        """Whether the poster panel is on screen (the Stage has the class ``-posters``)."""
        return self.has_class("-posters")

    def show_posters(self, source: PosterSource | None) -> None:
        """Show the poster panel with Posters from ``source``, or hide it for ``None``.

        Hidden, the panel holds no image and downloads nothing; the details move up.
        """
        self.set_class(source is not None, "-posters")
        for panel in self.query(PosterPanel):
            panel.view.use(source)
        self.posters_changed()

    def posters_changed(self) -> None:
        """The panel was shown or hidden: a Stage draws again what moves with it."""

    def compose_heading(self) -> ComposeResult:
        with Horizontal(classes="list-heading"):
            yield Static("Titles")
            yield Static("", classes="list-count")

    @property
    def title_list(self) -> TitleList:
        return self.query_one(TitleList)

    def show_heading_count(self, count: int) -> None:
        self.query_one(".list-count", Static).update(str(count))

    def redraw(self) -> None:
        self.title_list.redraw()

    def action_select_previous(self) -> None:
        self.title_list.select_previous()
        self.changed()

    def action_select_next(self) -> None:
        self.title_list.select_next()
        self.changed()
