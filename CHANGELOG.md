# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-26

### Added

- **Contributor tooling: README screenshot** — `uv run python scripts/render_preview.py` regenerates `docs/assets/preview.svg`, the README's picture of a TV plan in the preview. It runs headless with stand-in metadata, so it needs no network, API key or settings file. The version check now also fails when the README's Version badge differs from the newest changelog version.
- **User settings file** — the app reads its settings from a per-user dotenv file named `.env` in a `termrenamer` folder: `%APPDATA%\termrenamer\.env` on Windows, `$XDG_CONFIG_HOME/termrenamer/.env` (or `~/.config/termrenamer/.env`) on macOS and Linux. An installed copy finds your keys whichever folder you start it from. A `.env` in the current folder overrides it, and `TERMRENAMER_*` environment variables override both; a blank value counts as not set. The app only reads this file. A missing TMDB, TheTVDB or OMDb key now prints the file's full path. See `.env.example`.
- **Layout controls** — **Settings** (**Ctrl+,**) includes a **Layout** tab: **Enable folder rename** and **Enable season folders (TV)** (season option is disabled when folder rename is off). Same options are available as `TERMRENAMER_ENABLE_FOLDER_RENAME` and `TERMRENAMER_ENABLE_SEASON_FOLDERS` (both default **false**). When folder rename is **off**, only the media **filename** changes in its current folder; TV/film **destination root** env fields are **not** used for path layout. When folder rename is **on**, roots apply as before; TV can use flat show folder or `Season NN` trees. Apply can **merge stragglers** (extra files left in the old folder) into the destination tree with the same collision rules. See README and `.env.example`.
- Initial release.

### Changed

- **Breaking: `.env` lookup** — the app reads a `.env` only from the exact folder you start it in; it no longer searches parent folders or its own source folder. Migration: start a clone from the folder that holds its `.env`, or move your keys to the user settings file.
- **Contributor tooling: uv** — development now uses [uv](https://docs.astral.sh/uv/): `uv sync` installs the app and the `dev` dependency group (moved from the `[dev]` extra, so `pip install -e ".[dev]"` no longer installs dev tools), pinned by the committed `uv.lock` and `.python-version` (3.13). Run checks with `uv run pytest -v`, `uv run ruff check .`, `uv run ruff format --check .` and `uv run mypy src`. Installing the app with `pip install .` still works without uv.
- **Default rename layout** — bootstrap defaults are **filename-only** (both layout toggles off), which differs from earlier releases that always built show/season (TV) or title (film) folder trees. Enable **folder rename** in Settings or via env to restore library-style folder output.
- **TUI — responsive planning and apply** — **Build plan** and **Confirm apply** run network and filesystem work in Textual **thread workers** (exclusive group) so the UI event loop is not blocked during metadata lookups or renames. While a worker is running, **+ file**, **+ folder**, **Plan**, **Apply**, **Clear**, and **Cancel** are disabled; the preview and the explicit confirm before any rename are unchanged.

### Removed

- **Unused dependency** — `tomli_w` is no longer installed with the app.

### Fixed

- **Installed copy starts** — the built package now includes the terminal UI's stylesheet, so `termrenamer` installed with `uv tool install` or `pip install` opens the terminal UI instead of failing at start-up.
- **Activity tab** — Activity feed lines triggered while planning runs on a worker thread are applied on the main UI thread (thread-safe for Textual `RichLog`).
- **SQLite cache** — `SqliteMetadataCache` now closes the DB handle on destruction as a backstop; explicit `close()` remains the preferred lifetime boundary.

[Unreleased]: https://github.com/eunai/TermRenamer/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/eunai/TermRenamer/releases/tag/v0.1.0
