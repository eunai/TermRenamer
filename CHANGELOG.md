# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Layout controls** — **Settings** (**Ctrl+,**) includes a **Layout** tab: **Enable folder rename** and **Enable season folders (TV)** (season option is disabled when folder rename is off). Same options are available as `TERMRENAMER_ENABLE_FOLDER_RENAME` and `TERMRENAMER_ENABLE_SEASON_FOLDERS` (both default **false**). When folder rename is **off**, only the media **filename** changes in its current folder; TV/film **destination root** env fields are **not** used for path layout. When folder rename is **on**, roots apply as before; TV can use flat show folder or `Season NN` trees. Apply can **merge stragglers** (extra files left in the old folder) into the destination tree with the same collision rules. See README and `.env.example`.

### Changed

- **Default rename layout** — bootstrap defaults are **filename-only** (both layout toggles off), which differs from earlier releases that always built show/season (TV) or title (film) folder trees. Enable **folder rename** in Settings or via env to restore library-style folder output.
- **TUI — responsive planning and apply** — **Build plan** and **Confirm apply** run network and filesystem work in Textual **thread workers** (exclusive group) so the UI event loop is not blocked during metadata lookups or renames. While a worker is running, **+ file**, **+ folder**, **Plan**, **Apply**, **Clear**, and **Cancel** are disabled; **FR-007** (preview then explicit **Confirm apply**) is unchanged. See `termrenamer.tui.app.TermRenamerApp` and project spec (module registry `tui/`).

- **Changelog (public only)** — Prior `[Unreleased]` notes that referenced private documentation trees or tooling were removed from this file per the project’s public changelog contract. Detailed maintainer-facing notes for earlier iterations are kept outside the public changelog (per repository policy).

### Fixed

- **Activity tab** — Activity feed lines triggered while planning runs on a worker thread are applied on the main UI thread (thread-safe for Textual `RichLog`).
- **SQLite cache** — `SqliteMetadataCache` now closes the DB handle on destruction as a backstop; explicit `close()` remains the preferred lifetime boundary.

## [0.1.0] - 2026-04-14

### Added

- Initial release.

[Unreleased]: https://github.com/eunai/TermRenamer/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/eunai/TermRenamer/releases/tag/v0.1.0
