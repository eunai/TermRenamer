"""The Queue Stage: the centred prompt when empty, otherwise the Queue tree and its actions."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Center, Horizontal, Vertical
from textual.markup import escape
from textual.widgets import Static, Tree

from termrenamer.tui.stages.base import StageView
from termrenamer.tui.widgets.action_button import ActionButton

_NEEDS_SOURCES = frozenset({"build_plan", "clear_queue", "select_previous", "select_next"})


class QueueTree(Tree[Path], can_focus=False):
    """The queue as the app has always drawn it: "Queue", then one leaf per Source."""

    DEFAULT_CSS = """
    QueueTree {
        height: auto;
        max-height: 1fr;
        background: $background;
        padding: 0;
        overflow-x: hidden;
    }
    """


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


class QueueStage(StageView):
    """The Queue Stage's view of the queued Sources."""

    DEFAULT_CSS = """
    QueueStage #queue-empty {
        align: center middle;
        height: 1fr;
    }
    QueueStage #queue-prompt {
        width: 46;
        height: 11;
        border: round $tr-line;
        padding: 1 1;
    }
    QueueStage #queue-prompt .prompt-title, QueueStage #queue-prompt .prompt-text {
        width: 100%;
        content-align: center middle;
    }
    QueueStage .prompt-title {
        text-style: bold;
    }
    QueueStage .prompt-text {
        color: $tr-dim;
        margin-bottom: 2;
    }
    QueueStage .buttons {
        height: 1;
        width: auto;
        margin: 1 0 0 0;
    }
    QueueStage .buttons ActionButton {
        margin: 0 1;
    }
    QueueStage #queue-list {
        height: 1fr;
        padding: 2 0 0 0;
        align-horizontal: center;
    }
    QueueStage #queue-tree-box {
        width: 72;
        max-width: 100%;
        height: auto;
        max-height: 1fr;
        border-bottom: solid $tr-line;
    }
    QueueStage #queue-note {
        width: 100%;
        content-align: center middle;
        color: $tr-dim;
        margin-top: 2;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._sources: tuple[Path, ...] = ()

    def compose(self) -> ComposeResult:
        with Vertical(id="queue-empty"), Vertical(id="queue-prompt"):
            yield Static("Nothing queued yet", classes="prompt-title")
            yield Static("Add your backup files or folders.", classes="prompt-text")
            with Center(), Horizontal(classes="buttons"):
                yield ActionButton("a", "Add file", press_key="a")
                yield ActionButton("f", "Add folder", press_key="f")
        with Vertical(id="queue-list"):
            with Center(), Vertical(id="queue-tree-box"):
                yield QueueTree("Queue", id="source-tree")
            with Center(), Horizontal(classes="buttons"):
                yield ActionButton("b", "Build the Plan", press_key="b", classes="-strong")
                yield ActionButton("c", "Clear the queue", press_key="c", classes="-plain")
            with Center(), Horizontal(classes="buttons"):
                yield ActionButton("a", "Add file", press_key="a")
                yield ActionButton("f", "Add folder", press_key="f")
            yield Static("Nothing is looked up until you build the Plan.", id="queue-note")

    def on_mount(self) -> None:
        self.show_queue(())

    @property
    def selected_source(self) -> Path | None:
        node = self.query_one(QueueTree).cursor_node
        return node.data if node is not None else None

    def show_queue(self, sources: Sequence[Path]) -> None:
        """Draw the queue: a folder as its bold name and ``/`` then its path dimmed, a file as
        its name then its folder dimmed. The selection stays on the same Source when it can."""
        previous = self.selected_source
        self._sources = tuple(sources)
        self.query_one("#queue-empty").display = not self._sources
        self.query_one("#queue-list").display = bool(self._sources)
        tree = self.query_one(QueueTree)
        tree.clear()
        dim = self.app.theme_variables.get("tr-dim", "")
        for source in self._sources:
            label = Text()
            try:
                is_folder = source.is_dir()
            except OSError:
                is_folder = False
            if is_folder:
                label.append(source.name or str(source), style="bold")
                label.append("/")
                label.append(f"  {source}", style=dim)
            else:
                label.append(source.name)
                label.append(f"  {source.parent}", style=dim)
            tree.root.add_leaf(label, data=source)
        tree.root.expand()
        nodes = list(tree.root.children)
        if nodes:
            target = next((n for n in nodes if n.data == previous), nodes[-1])
            # Line 0 is "Queue"; the Sources follow it, one line each.
            tree.cursor_line = nodes.index(target) + 1
        self.changed()

    def redraw(self) -> None:
        self.show_queue(self._sources)

    def count_text(self) -> str:
        return _plural(len(self._sources), "Source") if self._sources else ""

    def footer_lines(self) -> tuple[str, ...]:
        source = self.selected_source
        if source is None:
            return ()
        try:
            kind = "folder" if source.is_dir() else "file"
        except OSError:
            kind = "file"
        return (
            f"[$tr-dim]path[/]  [$foreground]{escape(str(source))}[/]",
            f"      [$tr-dim]{kind} · queued · nothing looked up yet[/]",
        )

    def key_enabled(self, action: str) -> bool:
        return bool(self._sources) or action not in _NEEDS_SOURCES

    def action_select_previous(self) -> None:
        tree = self.query_one(QueueTree)
        if tree.cursor_line > 1:  # line 0 is "Queue", which is not a Source
            tree.action_cursor_up()
        self.changed()

    def action_select_next(self) -> None:
        self.query_one(QueueTree).action_cursor_down()
        self.changed()

    def on_tree_node_highlighted(self) -> None:
        self.changed()
