# Versioning

Read this guide before editing the changelog, choosing a version number, or preparing a release.

The repo uses [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html) and one `CHANGELOG.md` that follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/).

## What gets an entry

`CHANGELOG.md` records changes that a user or a dependent can see. A documentation-only change (guides, ADRs, research, the glossary, the README) gets no entry. Tooling that changes what a contributor runs does get one.

Keep the `Unreleased` section at the top, newest entries first, and the six change types in order: Added, Changed, Deprecated, Removed, Fixed, Security.

## Declared public API and conditions for 1.0

SemVer requires a declared public API. This repo's is:

- The `termrenamer` console script and `python -m termrenamer`: how they start (at least one of the TMDB, TheTVDB and OMDb keys set), and the exit status `2` on a settings validation error, which includes no Provider key set.
- The `TERMRENAMER_*` environment variables listed in `.env.example`: their names, accepted values and defaults (API keys, HTTP timeout and retry tuning, Film and TV destination folders, `TERMRENAMER_ENABLE_FOLDER_RENAME`, `TERMRENAMER_ENABLE_SEASON_FOLDERS`, `TERMRENAMER_NAME_TAKEN`, the cache path and the log file path).
- The user settings file's location: `%APPDATA%\termrenamer\.env` on Windows (`AppData\Roaming` in the home folder when `APPDATA` is unset or empty); `$XDG_CONFIG_HOME/termrenamer/.env` everywhere else, macOS included (`~/.config` when `XDG_CONFIG_HOME` is unset, empty or relative).
- The settings precedence, highest first: environment variables, a `.env` in the current working folder (that folder only), then the user settings file. A blank value counts as not set.
- The rename output: the filename and folder layout a plan produces for given metadata and settings, and the Name taken policy (never overwrite; `suffix` adds a number, `skip` leaves the file where it is).
- The TUI workflow contract: plan, then preview, then an explicit confirm before any rename; the documented key bindings (`m`, `p`, `b`, Ctrl+F, Ctrl+,).
- The supported Python version (3.13+) and the supported providers (TMDB, TheTVDB v4, OMDb).

Everything else is internal and changes without a version signal: the Python modules under `src/termrenamer/` (no import API is offered), the SQLite cache schema (the cache is safe to delete), log message text, and the TUI's widget layout and styling.

Versions stay on `0.y.z` until all of these hold:

1. The `TERMRENAMER_*` variable set and the rename layout options have gone one minor release with no breaking change.
2. TMDB, TheTVDB v4 and OMDb planning and apply pass the test suite on Windows, macOS and Linux.
3. The README and `.env.example` document every variable and key binding in the public API above.
4. The version in `pyproject.toml` matches the newest `CHANGELOG.md` heading, and each release has its tag and GitHub Release.

How changes map to change types:

| Change                                                                  | Type            |
| ----------------------------------------------------------------------- | --------------- |
| New env variable, setting, provider or key binding                      | `feat`          |
| Env variable renamed or removed, default changed, rename layout changed | Breaking change |
| Wrong match, rename or collision handling corrected                     | `fix`           |

## Before 1.0

Versions start at `0.1.0`. Apply these bumps until the conditions for 1.0 hold:

| Change          | Bump  | Example           |
| --------------- | ----- | ----------------- |
| `feat`          | Minor | `0.1.0` → `0.2.0` |
| Breaking change | Minor | `0.1.0` → `0.2.0` |
| `fix` or `perf` | Patch | `0.1.0` → `0.1.1` |

Mark a breaking change with `!`, a `BREAKING CHANGE:` footer, or both, and add a `Changed` or `Removed` changelog entry carrying the migration note. Only the field a breaking change bumps differs before and after 1.0.

Start at `0.1.0`, never `0.0.x`: caret ranges on `0.0.x` admit no updates at all.

## After 1.0

Bump MAJOR for a breaking change, MINOR for `feat`, and PATCH for `fix` or `perf`.

## Where the version lives

`CHANGELOG.md` is the version: its newest version heading is what gets tagged and released. Any `version` field elsewhere (`package.json`, a manifest, skill frontmatter) is a copy of that heading. Each version mention in the README, such as a badge, a status line or an install example, is a copy too, and a version check reads each one. Compare the copies with the heading before cutting a release, and stop on a mismatch.

## Cutting a release

A release is a version in the changelog, a Git tag, and a GitHub Release, all three. Cut one only when the user asks.

1. Rename `Unreleased` to the new version with today's date, as `## [0.2.0] - 2026-11-15`, and add a fresh empty `Unreleased` above it. Take the date from `date +%F`, the machine's local date.
2. Set every copy of the version to match.
3. Commit, tag the commit with the version behind a `v` prefix and no emoji (for example `v0.1.0`), and create a GitHub Release:
   - Title: `vX.Y.Z - <creative title> <one emoji>`, for example `v0.1.0 - First Light 🌅`. The creative title is a short, memorable name for the release, followed by exactly one emoji that fits it. The changelog heading carries no title or emoji.
   - Pre-release flag: a `0.y.z` release is published as a normal GitHub Release. The flag is for a release candidate or beta of a version, a SemVer pre-release identifier such as `1.0.0-rc.1`.
   - Body: open with one plain sentence that says what the release delivers, for example "A command that imports bank statements and the rules that sort them into accounts." Then write for users: what the project does, what it needs, and its known limits, with a link to the changelog.
