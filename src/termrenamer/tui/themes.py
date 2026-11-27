"""The two themes: the dark and the light teal palettes of the approved mockup.

Besides Textual's own colours, each theme sets the mockup's other colours as
variables the stylesheet and the screen's markup use: ``$tr-dim`` (secondary text),
``$tr-line`` (rules and borders), ``$tr-highlight`` (the selected row),
``$tr-track`` (an empty gauge or an off switch), ``$tr-button`` (a key's button),
``$tr-dialog`` (a dialog's ground), ``$tr-on-accent`` (text on the accent) and
``$tr-field`` (an input's ground).
"""

from __future__ import annotations

from textual.theme import Theme

from termrenamer.app_bootstrap import ThemeName


def _theme(name: str, *, dark: bool, colours: dict[str, str]) -> Theme:
    c = colours
    return Theme(
        name=name,
        primary=c["acc"],
        secondary=c["acc"],
        accent=c["acc"],
        foreground=c["fg"],
        background=c["bg"],
        surface=c["bg"],
        panel=c["hd"],
        success=c["ok"],
        warning=c["warn"],
        error=c["err"],
        dark=dark,
        variables={
            "tr-dim": c["dim"],
            "tr-line": c["ln"],
            "tr-highlight": c["hl"],
            "tr-track": c["trk"],
            "tr-button": c["btn"],
            "tr-dialog": c["mod"],
            "tr-on-accent": c["onacc"],
            "tr-field": c["fld"],
            "tr-footer": c["pan"],
            "text-muted": c["dim"],
            "block-cursor-background": c["hl"],
            "block-cursor-foreground": c["fg"],
            "block-cursor-text-style": "bold",
            "block-cursor-blurred-background": c["hl"],
            "block-cursor-blurred-foreground": c["fg"],
            "block-cursor-blurred-text-style": "bold",
            "footer-background": c["hd"],
            "input-selection-background": f"{c['acc']} 35%",
        },
    )


DARK = _theme(
    "termrenamer-dark",
    dark=True,
    colours={
        "bg": "#101315",
        "fg": "#e2e6e9",
        "dim": "#7f8a92",
        "ln": "#343c42",
        "acc": "#5fd4c4",
        "ok": "#7bd88f",
        "warn": "#f2c35b",
        "err": "#ff7b72",
        "hd": "#181c1f",
        "pan": "#15191c",
        "hl": "#1d3533",
        "trk": "#2a3136",
        "btn": "#222a2e",
        "mod": "#1b2125",
        "onacc": "#06110f",
        "fld": "#0a0c0e",
    },
)

LIGHT = _theme(
    "termrenamer-light",
    dark=False,
    colours={
        "bg": "#f6f7f5",
        "fg": "#1d2124",
        "dim": "#5b646b",
        "ln": "#b9c0bf",
        "acc": "#00756b",
        "ok": "#23733a",
        "warn": "#8a5700",
        "err": "#b72f27",
        "hd": "#e4e8e6",
        "pan": "#edefec",
        "hl": "#cde7e2",
        "trk": "#d3d8d6",
        "btn": "#dbe1df",
        "mod": "#ffffff",
        "onacc": "#ffffff",
        "fld": "#e4e8e6",
    },
)

THEMES: dict[ThemeName, Theme] = {ThemeName.DARK: DARK, ThemeName.LIGHT: LIGHT}
"""The Textual theme for each value of the Theme setting."""
