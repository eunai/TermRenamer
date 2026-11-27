# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Theme** — the screen has a dark and a light theme in teal. `TERMRENAMER_THEME` takes `dark` (the default) or `light`; any other value stops the app at start-up with exit status 2. The Theme row in Settings switches between them for the session, and switching discards nothing.
- **Duplicate Sources are refused** — adding a file or folder whose resolved path is already queued, compared without regard to letter case, is refused with a message. A folder and a file inside it can both be queued: the file is planned once, under the outermost queued folder. When the Plan is built, a queued file or folder that no longer exists, and a queued file that is not a video, are reported in the log and the rest of the queue is planned.
- **Not recognised videos are listed** — a video whose name the app cannot read is now in the Plan, marked "not recognised", with its Sidecars; Apply leaves them where they are. Before, they were left out of the Plan without a word.
- **Contributor tooling: CI** — a GitHub Actions workflow (`.github/workflows/ci.yml`) runs `uv sync --locked`, then `uv run pytest -v --cov`, `uv run ruff check .`, `uv run ruff format --check .` and `uv run mypy src`, each as its own step, on Linux and Windows with Python 3.13 (one job per system, and a failure on one does not stop the other), for each pull request and each push to `main`.

### Changed

- **BREAKING: one screen in four Stages, and new keys** — the screen now walks a batch through the Queue, Plan, Preview and Applied Stages, with a header (Mode, Provider, Destination root), a row of the Stages and a footer that shows a message and the keys that work at the current Stage. The Title list fills in while the Plan is built; the Preview shows one row per Title with its status and its count of videos, and a not recognised video as a row of its own; `Enter` opens the Apply confirm, where `y` or `Enter` applies and `n` or `Esc` goes back. The keys changed: `Ctrl+F` and the folder-or-file picker are replaced by `a` (add a file) and `f` (add a folder), which open the file and folder dialogs directly; `Ctrl+,` is replaced by `s` (Settings); `F1` by `?` (Help, which lists every key); `q` quits from anywhere but a text field (`Ctrl+Q` still quits), so `Esc`, not `q`, now closes Help and Settings; `a`, which switched the Activity and Logs tabs, now adds a file, and `l` opens the Logs. New: `c` clears the queue, `Esc` at the Preview discards the Plan, `n` at the Applied Stage starts a new batch. Sources are added or cleared only at the Queue Stage; `m` and `p` work at the Queue and Preview Stages. Settings is one form: TV Destination root, Film Destination root, Folder rename, Season folder and Theme. Season folder cannot be turned on while Folder rename is off, and turning Folder rename off turns it off.
- **A Provider failure stops the build** — when the Provider cannot be reached, rejects the key or gives an unusable answer, building the Plan stops with the Provider's message, no Plan is made and the queue is kept. Before, the files were planned as unmatched.
- **A changed setting discards the Plan** — changing a Destination root, Folder rename or Season folder in Settings while a Plan is shown discards the Plan, keeps the queue and says so in the log; changing Mode or Provider does the same, now with the message. While a Plan is being built or applied, Settings, Mode and Provider cannot be changed, and the key says so.
- **Sidecars follow their video** — Apply handles each video before its Sidecars, and moves a Sidecar only when its video was renamed or already had its name; otherwise the Sidecar is skipped with "video not applied", or with its video's status ("no match", "not recognised") when the video has no name to take. A file that already has its name is reported as unchanged, and Apply's summary line counts renamed, unchanged, skipped and failed files. A planned name that was taken and got a number is marked "name taken" in the preview.
- **OMDb searches by title** — a Film plan with OMDb now uses OMDb's search and takes the first film it lists that has a year, as TMDB does. When OMDb answers that a search has too many results, the app asks OMDb for the single title instead, as it did before.
- **Any one provider key is enough to start** — the app starts when at least one of `TERMRENAMER_TMDB_API_KEY`, `TERMRENAMER_TVDB_API_KEY` and `TERMRENAMER_OMDB_API_KEY` is set; it no longer requires the TMDB key (#3). With none, it exits with status 2 and a message that names the three settings, says one is enough and says where to set them; a TheTVDB subscriber PIN alone is not a key. At start and on every change of Mode the provider is the first of that Mode with a key (TMDB, then the other), or TMDB when none has one. A provider with no key is marked "no key" and `p` still selects it; building a plan with it, TMDB included, names the setting to add and builds no plan.
- **Contributor tooling: coverage check** — the full test check is now `uv run pytest -v --cov` (was `uv run pytest -v`). Coverage is no longer in pytest's default options, so `uv run pytest` with a single test file runs those tests only and exits 0 when they pass, where it used to fail on the 85% coverage threshold. `--cov` measures `src/termrenamer` and still fails below 85%, from `[tool.coverage]` in `pyproject.toml`.

### Removed

- **The Activity tab** and its match events; the log lines are in the Logs view (`l`).
- **The folder-or-file picker** opened by `Ctrl+F`; `a` and `f` open the file and folder dialogs directly.
- **The gruvbox theme**; the screen uses its own dark and light themes.

### Fixed

- **Apply uses the Plan's Folder rename** — Apply merges Stragglers by the Folder rename value the Plan was built with, not by the current setting.
- **Stragglers leave the Plan's files and target folders alone** — merging Stragglers no longer moves a file of the Plan that Apply did not rename (no match, not recognised, or skipped), nor a folder that is, holds or lies inside a folder the Plan moves files into. Before, a second show's new folder at the top of a queued folder could be moved into the first show's season folder.
- **Numbered names across queued folders** — when files from several queued folders want the same name, the numbers are given once across the whole Plan in source-path order, so a name such as `Title (1) (1).mkv` no longer appears.
- **OMDb lookups are cached** — with `TERMRENAMER_CACHE_DB_PATH` set, OMDb film lookups now go through the SQLite cache like TMDB and TheTVDB lookups, so a second plan of the same films sends no OMDb request ([#5](https://github.com/eunai/TermRenamer/issues/5)).
- **Cache entries kept apart by provider** — every cache entry is now stored under the provider it came from, so a lookup cached from one provider is never used for another, in TV or Film. A search that found nothing is not stored. When a film search with the filename's year finds nothing and the search without the year finds the film, both are stored, so the next plan sends no request for it. Existing cache entries are discarded once: the first plan after this update drops the old entries from the cache file, which fills again as you plan. Deleting the file is still safe.
- **Cache across plans** — a second plan built in the same session now reads what the first one stored. Before, the cache only worked for the first plan of a session, and later plans logged a cache warning and fell back to the network.
- **Broken symbolic links** — a broken symbolic link now counts as a file that is already there. A planned name held by one gets the numbered name, as for any other taken name, and so does a straggler merged into a destination folder. If one appears at a destination after the preview, apply skips that entry with "destination exists at apply time" instead of replacing the link ([#9](https://github.com/eunai/TermRenamer/issues/9)).

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
