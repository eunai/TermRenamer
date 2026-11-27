# TermRenamer

Rename TV and movie files from online metadata, with a preview before anything changes.

[![Version](https://img.shields.io/badge/version-0.1.0-blue?style=flat-square)](./pyproject.toml)
[![Status](https://img.shields.io/badge/status-pre--release-orange?style=flat-square)](#status)
[![License](https://img.shields.io/badge/license-GPL--3.0-blue?style=flat-square)](./LICENSE)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue?style=flat-square)](#install)

![TermRenamer showing a TV plan in its preview](docs/assets/preview.svg)

TermRenamer gives backups of your own media library-ready names. It works in
three steps: it builds a plan from online metadata, shows you a preview, and
applies the plan. Nothing is renamed until you confirm.

## Example

By default, only the filename changes. A TV episode and its subtitle file:

| Before                    | After                               |
| ------------------------- | ----------------------------------- |
| `breaking_bad_s01e01.mkv` | `Breaking Bad - S01E01 - Pilot.mkv` |
| `breaking_bad_s01e01.srt` | `Breaking Bad - S01E01 - Pilot.srt` |

A film:

| Before                | After                   |
| --------------------- | ----------------------- |
| `the_matrix_1999.mkv` | `The Matrix (1999).mkv` |

Turn on **folder rename** and the files also move into a folder tree. For TV,
turn on **season folders** as well:

```text
The Matrix (1999)/
  The Matrix (1999).mkv

Breaking Bad/
  Season 01/
    Breaking Bad - S01E01 - Pilot.mkv
```

## Status

Pre-release. Behaviour and settings may change. Work on copies, or keep
backups, until you trust the results.

| Platform | State                                                        |
| -------- | ------------------------------------------------------------ |
| Windows  | Developed and tested here.                                   |
| macOS    | The test suite passes. The app itself is still being tested. |
| Linux    | Unverified.                                                  |

## Install

You need [uv](https://docs.astral.sh/uv/) and an API key from at least one
provider: [TMDB](https://www.themoviedb.org/settings/api) (TV and films),
TheTVDB (TV) or OMDb (films). One is enough. TermRenamer needs Python 3.13 or
newer. uv picks a matching Python and, by default, downloads one
when your machine has none.

```bash
uv tool install git+https://github.com/eunai/TermRenamer
termrenamer
```

Without any provider key, the app exits with status 2 and prints the three key
settings and the full path of the settings file it expects.
See [Configure](#configure).

To upgrade or remove it:

```bash
uv tool upgrade termrenamer
uv tool uninstall termrenamer
```

## Configure

Settings live in the **user settings file**: a file named `.env` in a
`termrenamer` folder under your per-user configuration folder.

| Platform        | Path                                                                                                        |
| --------------- | ----------------------------------------------------------------------------------------------------------- |
| Windows         | `%APPDATA%\termrenamer\.env` (under `AppData\Roaming` in your home folder when `APPDATA` is unset or empty) |
| macOS and Linux | `~/.config/termrenamer/.env` (or under `XDG_CONFIG_HOME` when it holds an absolute path)                    |

A `.env` in the folder you start the app from overrides the user settings
file. `TERMRENAMER_*` environment variables override both. A blank value
(`NAME=`) counts as not set, so a value from a lower source still applies. The
app only reads these files and never writes them.

A minimal file sets one provider key, for example:

```dotenv
TERMRENAMER_TMDB_API_KEY=...
```

The app starts when at least one of `TERMRENAMER_TMDB_API_KEY`,
`TERMRENAMER_TVDB_API_KEY` and `TERMRENAMER_OMDB_API_KEY` is set. A TheTVDB
subscriber PIN alone is not a key. A provider whose key is missing is marked
"no key" in the provider bar; building a plan with it names the setting to add
and builds no plan.

The main settings:

| Setting                             | Default | Purpose                                                             |
| ----------------------------------- | ------- | ------------------------------------------------------------------- |
| `TERMRENAMER_TMDB_API_KEY`          | none    | TMDB key. Needed to build a plan with TMDB.                         |
| `TERMRENAMER_TVDB_API_KEY`          | none    | TheTVDB v4 key. Needed to build a plan with TheTVDB.                |
| `TERMRENAMER_OMDB_API_KEY`          | none    | OMDb key. Needed to build a plan with OMDb.                         |
| `TERMRENAMER_ENABLE_FOLDER_RENAME`  | `false` | Move files into show or film folders, not just rename the filename. |
| `TERMRENAMER_ENABLE_SEASON_FOLDERS` | `false` | Place TV episodes in `Season NN` folders. Needs folder rename.      |
| `TERMRENAMER_FILM_DEST_FOLDER`      | unset   | Root folder for film output. Used only when folder rename is on.    |
| `TERMRENAMER_TV_DEST_FOLDER`        | unset   | Root folder for TV output. Used only when folder rename is on.      |
| `TERMRENAMER_CACHE_DB_PATH`         | unset   | Path of a SQLite metadata cache. The cache is off until you set it. |

[`.env.example`](.env.example) lists every setting, including HTTP timeout and
retry tuning. Changes you make on the **Settings** screen last for the current
session only.

## Use

1. Run `termrenamer`.
2. Queue sources with **+ folder** or **+ file**.
3. Pick **TV** or **Film** and a provider. A provider without a key is marked
   "no key".
4. Build the plan with **plan**.
5. Review the preview: it shows the source and destination folder trees.
6. Choose **apply** to rename, or **cancel** to change nothing.

The **Activity** tab lists each match as it happens. The **Logs** tab shows log
output.

Key bindings:

| Key          | Action                                    |
| ------------ | ----------------------------------------- |
| `m`          | Toggle TV / Film mode                     |
| `p`          | Cycle the provider for the current mode   |
| `b`          | Build plan                                |
| `a`          | Switch the Activity / Logs tab            |
| `Ctrl+F`     | Add a source (folder or file)             |
| `Ctrl+,`     | Open Settings                             |
| `F1`         | Open Help                                 |
| `Ctrl+Q`     | Quit                                      |
| `q` or `Esc` | Close Help, Settings or the Ctrl+F picker |
| `Esc`        | Close a file or folder dialog             |

## Features

- **Plan, preview, then apply.** No rename runs until you confirm.
- **TV and Film modes.** TV uses TMDB or TheTVDB v4. Film uses TMDB or OMDb.
  OMDb is a provider you select, not an automatic fallback.
- **Source queue.** Add folders and files with **+ folder** / **+ file**, or
  **Ctrl+F**.
- **Preview.** Source and destination folder trees, plus an Activity tab with
  readable match events.
- **Collisions.** When a destination name is taken, the plan adds a numbered
  suffix such as ` (1)`. If a file or folder appears at a destination after the
  preview, apply skips that entry.
- **Folder layouts.** With folder rename on, files move into show or film
  folders, with optional `Season NN` folders for TV. Destination roots apply
  only when folder rename is on.
- **Sidecars.** `.srt`, `.nfo`, `.sub` and `.idx` files move with the video in
  the same folder whose filename matches theirs apart from the extension,
  ignoring case.
- **Metadata cache.** Setting `TERMRENAMER_CACHE_DB_PATH` switches on a SQLite
  cache for TMDB, TheTVDB and OMDb lookups. Each provider's entries are kept
  apart, and a search that found nothing is not stored. It is safe to delete.
- **Resilient requests.** Bounded retries, backoff, and `Retry-After`
  handling.

## Known limitations

- `TERMRENAMER_LOG_FILE` has no effect yet
  ([#4](https://github.com/eunai/TermRenamer/issues/4)).
- There is no setting to skip an entry instead of adding a suffix on a
  collision ([#6](https://github.com/eunai/TermRenamer/issues/6)).

## Troubleshooting

See the [runbook](docs/runbook.md) for safe-rerun commands and common provider
problems.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for what changed in each version.

## Contributing

Report bugs and share ideas in
[GitHub Issues](https://github.com/eunai/TermRenamer/issues). A pull request is
welcome once an issue agrees the change.

To set up from a clone, with [uv](https://docs.astral.sh/uv/):

```bash
uv sync
uv run pytest -v --cov
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run termrenamer
```

Start the app from the repository root, so it reads the clone's `.env`.

`--cov` measures coverage of `src/termrenamer` and fails the run below 85%.
Without it, `uv run pytest` runs the tests only, so you can run one test file
on its own. CI runs the same checks on each pull request and each push to `main`.

The project is developed with AI coding assistants. The rules they follow live
in [`AGENTS.md`](AGENTS.md) and [`docs/agents/`](docs/agents/).

## Attribution

When you use **TheTVDB** for TV metadata, data comes from their API. Per [TheTVDB’s licensing terms](https://thetvdb.com/api-information#attribution): [Metadata provided by TheTVDB. Please consider adding missing information or subscribing.](https://thetvdb.com/)

This product uses the TMDB API but is not endorsed or certified by TMDB.

Film metadata can also come from [OMDb](https://www.omdbapi.com/).

## License

TermRenamer is licensed under the **GNU General Public License v3.0**. See
[LICENSE](LICENSE) for the full text.
