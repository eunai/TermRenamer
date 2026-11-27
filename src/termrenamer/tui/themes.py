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
    return Theme(
        name=name,
        primary=colours["accent"],
        secondary=colours["accent"],
        accent=colours["accent"],
        foreground=colours["foreground"],
        background=colours["background"],
        surface=colours["background"],
        panel=colours["header"],
        success=colours["success"],
        warning=colours["warning"],
        error=colours["error"],
        dark=dark,
        variables={
            "tr-dim": colours["dim"],
            "tr-line": colours["line"],
            "tr-highlight": colours["highlight"],
            "tr-track": colours["track"],
            "tr-button": colours["button"],
            "tr-dialog": colours["dialog"],
            "tr-on-accent": colours["on_accent"],
            "tr-field": colours["field"],
            "tr-footer": colours["footer"],
            "text-muted": colours["dim"],
            "block-cursor-background": colours["highlight"],
            "block-cursor-foreground": colours["foreground"],
            "block-cursor-text-style": "bold",
            "block-cursor-blurred-background": colours["highlight"],
            "block-cursor-blurred-foreground": colours["foreground"],
            "block-cursor-blurred-text-style": "bold",
            "footer-background": colours["header"],
            "input-selection-background": f"{colours['accent']} 35%",
        },
    )


DARK = _theme(
    "termrenamer-dark",
    dark=True,
    colours={
        "background": "#101315",
        "foreground": "#e2e6e9",
        "dim": "#7f8a92",
        "line": "#343c42",
        "accent": "#5fd4c4",
        "success": "#7bd88f",
        "warning": "#f2c35b",
        "error": "#ff7b72",
        "header": "#181c1f",
        "footer": "#15191c",
        "highlight": "#1d3533",
        "track": "#2a3136",
        "button": "#222a2e",
        "dialog": "#1b2125",
        "on_accent": "#06110f",
        "field": "#0a0c0e",
    },
)

LIGHT = _theme(
    "termrenamer-light",
    dark=False,
    colours={
        "background": "#f6f7f5",
        "foreground": "#1d2124",
        "dim": "#5b646b",
        "line": "#b9c0bf",
        "accent": "#00756b",
        "success": "#23733a",
        "warning": "#8a5700",
        "error": "#b72f27",
        "header": "#e4e8e6",
        "footer": "#edefec",
        "highlight": "#cde7e2",
        "track": "#d3d8d6",
        "button": "#dbe1df",
        "dialog": "#ffffff",
        "on_accent": "#ffffff",
        "field": "#e4e8e6",
    },
)

THEMES: dict[ThemeName, Theme] = {ThemeName.DARK: DARK, ThemeName.LIGHT: LIGHT}
"""The Textual theme for each value of the Theme setting."""
