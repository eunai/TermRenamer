# TermRenamer

**TermRenamer** is an open-source Python desktop app (terminal UI) that helps
you rename TV and movie files using online metadata from providers such as
**The Movie Database (TMDB)** and **TheTVDB**. It is aimed at anyone who wants
to clean up release-style filenames in bulk. The app is built around a
**plan -> preview -> apply** flow: you always see the proposed changes and
confirm before anything is renamed.

## Status

**Early development / pre-release.** Behavior, supported providers, and
configuration may change between commits. Use copies of your media or backups
until you are comfortable with the results.

## Attribution

When you use **TheTVDB** for TV metadata, data comes from their API. Per [TheTVDB’s licensing terms](https://thetvdb.com/api-information#attribution): [Metadata provided by TheTVDB. Please consider adding missing information or subscribing.](https://thetvdb.com/)

## Features

- **Plan, preview, then apply** - no renames until you explicitly confirm.
- **TV and Film** modes with **TMDB** (TV + movies), **TheTVDB v4** (TV), and
  optional **OMDb** (film fallback).
- **Source queue** - add folders or files with **+ folder** / **+ file**
  (or **Ctrl+F** for a quick picker).
- **Optional destination folders** for Film and TV output.
- **Plan preview** - folder trees for Source and Destination; an Activity tab
  shows human-readable match events.
- **Optional SQLite metadata cache** to reduce repeat API calls.
- **Sidecar files** (for example `.srt`, `.nfo`) can move together with their
  associated video.
- **Collision-safe renames** - never silently overwrites; deterministic
  OS-native suffixing or skip per policy.
- **HTTP resilience** - bounded retries, backoff, and `Retry-After` handling.

## AI-assisted development

This project is developed with AI coding assistants. The detailed agent
tooling and rules are maintained in a private working repository and are not
included in this public release.

## Requirements

- **Python 3.13+**
- **Windows, macOS, and Linux** - any desktop where Python 3.13+ runs.

## Install

```bash
git clone https://github.com/eunai/TermRenamer
cd TermRenamer

python -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows:
# .venv\Scripts\activate

pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and fill in values locally. Never commit `.env`
or real API keys.

## Configuration

Secrets and environment-specific values belong in `.env` (gitignored) or in
your process environment - not in the source tree. See `.env.example` for the
full list of supported variables including TMDB / TVDB / OMDb API keys, HTTP
client tuning, optional destination folders, and optional SQLite cache path.

## Usage

```bash
python -m termrenamer
```

Typical flow: queue sources with **+ folder** / **+ file** (or **Ctrl+F**),
optionally open **Settings** (**Ctrl+,**), pick **TV or Film** (`m`) and a
provider (`p`), then press **Build plan** (`b`). Review the preview, then
**Confirm apply** or **Cancel**. No renames run until you confirm.

## Troubleshooting

See the operator [runbook](docs/runbook.md) for safe-rerun commands and common provider issues.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for release-by-release code changes.

## Development

```bash
pytest -v
ruff check .
ruff format --check .
mypy src
python -m termrenamer
```

## License

This project is licensed under the **GNU General Public License v3.0** - see
[LICENSE](LICENSE) for the full text.
