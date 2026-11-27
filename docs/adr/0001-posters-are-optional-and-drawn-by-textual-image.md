---
status: accepted
date: 2026-11-26
---

# Posters are optional and drawn by `textual-image`

The new screen shows one Poster for the selected Title. Textual has no built-in image support, so Posters come from the third-party package `textual-image`, installed only through an optional install extra named `posters`. A plain install has no Posters and looks like the poster-hidden view.

## Context

- `textual-image` draws images through Sixel or the Kitty protocol. iTerm2, WezTerm and Windows Terminal 1.22 or later work; the plain Windows Console and GNOME Terminal draw none.
- Its own notes warn that an image flickers when it scrolls or is restyled, and that Sixel in Textual is slow.
- It brings in Pillow.
- Provider terms cover the image files. TMDB allows keeping them for at most six months and asks for a visible credit. TheTVDB asks for a credit with a link.

## Decision

1. Posters come from `textual-image`, installed only through the `posters` extra.
2. Where the terminal cannot draw images, the poster panel is hidden and the Show posters setting shows as unavailable.
3. One Poster is on screen at a time, in a fixed panel, outside any scrolling area and with nothing drawn over it.
4. Poster files are kept on disk in the app's cache folder for 30 days.
5. The Provider credits go on the Help screen and in the README.

## Considered options

- **Required dependency.** Rejected: every install would carry Pillow and a package with known flicker, for a feature most runs can do without.
- **Rough picture in coloured character blocks where images are unsupported.** Deferred to a follow-up ticket, as a setting. Still open.
- **Posters in memory only.** Rejected: a Title seen before would not draw at once.
- **Another toolkit with stronger image support.** Rejected: the owner compared mockups for other toolkits and chose to stay on Textual.

## Consequences

- Posters depend on a third-party package's terminal support.
- The layout must work with the poster panel hidden.
- Stored Poster files must expire, so the app removes those older than 30 days.
