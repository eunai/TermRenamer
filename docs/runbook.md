# Operator runbook — TermRenamer

This document complements the [README](../README.md) with practical troubleshooting. **Never commit API keys**; use the user settings file, a `.env` or your shell environment (see [`.env.example`](../.env.example)).

Settings come from three sources, highest first: `TERMRENAMER_*` environment variables, a `.env` in the folder you start the app from (that folder only, no parent folders), then the **user settings file**: `%APPDATA%\termrenamer\.env` on Windows (`AppData\Roaming` in your home folder when `APPDATA` is unset or empty), `$XDG_CONFIG_HOME/termrenamer/.env` on macOS and Linux (`~/.config/termrenamer/.env` when `XDG_CONFIG_HOME` is unset, empty or relative). The app starts when at least one Provider key is set; with none, the start-up error names the three key settings and prints the user settings file's full path.

## Common failures

| Symptom | Likely cause | What to check |
|--------|----------------|----------------|
| `No Provider API key is set` on startup (exit status 2) | None of `TERMRENAMER_TMDB_API_KEY`, `TERMRENAMER_TVDB_API_KEY` and `TERMRENAMER_OMDB_API_KEY` is set in any source (a `TERMRENAMER_TVDB_SUBSCRIBER_PIN` alone is not a key) | Copy `.env.example` to the user settings file path the message prints, set any one of the three keys, restart the app; for a clone, a `.env` at the repository root works when you start from that root |
| A key in a clone's `.env` is not found | The app reads a `.env` only from the exact folder it starts in, and no longer searches parent folders or its own source folder | Start from the folder that holds the `.env`, or move the keys to the user settings file |
| `Cannot read settings file` on startup (exit status 2) | The user settings file or a `.env` is unreadable or not UTF-8 | Fix the file's permissions, or save it as UTF-8 |
| `TMDB requires an API key` | `TERMRENAMER_TMDB_API_KEY` unset when TMDB is the selected provider (marked "no key") | Set `TERMRENAMER_TMDB_API_KEY` in the user settings file the message names (or `.env`), or press `p` to pick a provider that has a key |
| `OMDb requires an API key` | `TERMRENAMER_OMDB_API_KEY` unset when OMDb selected as film provider | Set `TERMRENAMER_OMDB_API_KEY` in the user settings file the message names (or `.env`), or press `p` to pick TMDB when its key is set |
| `TheTVDB requires an API key` | `TERMRENAMER_TVDB_API_KEY` unset when TheTVDB selected as TV provider | Set `TERMRENAMER_TVDB_API_KEY` (and `TERMRENAMER_TVDB_SUBSCRIBER_PIN` if your account needs it) in the user settings file the message names (or `.env`) |
| `ValidationError` for invalid numeric/boolean env | Bad value for `TERMRENAMER_HTTP_TIMEOUT_SECONDS`, `TERMRENAMER_HTTP_BACKOFF_BASE_SECONDS`, `TERMRENAMER_HTTP_MAX_ATTEMPTS`, or `TERMRENAMER_HTTP_JITTER` | Use numbers for timeouts/backoff/max attempts; for jitter use `true`/`false`/`1`/`0`/`yes`/`no`/`on`/`off` (see `load_settings()` in `app_bootstrap.py`) |
| `TERMRENAMER_HTTP_MAX_ATTEMPTS must be >= 1` | Max attempts set to 0 or negative | Set to at least `1` |
| HTTP **401** from TMDB | Invalid or revoked API key | Regenerate key in TMDB dashboard; verify no extra quotes/spaces in the user settings file or `.env` |
| HTTP **401** from TheTVDB | Bad API key or expired session | Set `TERMRENAMER_TVDB_API_KEY` (and `TERMRENAMER_TVDB_SUBSCRIBER_PIN` if your account requires it); the adapter re-logins at most once |
| HTTP **404** from TheTVDB during planning | Search results can expose a non-numeric `id` (for example `series-412429`); episode routes require the numeric **tvdb_id** | Use a build where `api/tvdb_v4` resolves `tvdb_id` (and sends `page` on episode list); negotiated-contract keys without a PIN are fine if your dashboard does not require one |
| HTTP **429** / slow planning | Rate limiting | Reduce batch size; wait; avoid sharing one key across many machines. Transport honors `Retry-After` when present and uses bounded backoff with optional jitter (see `util/http.py`) |
| **`ProviderError` after repeated HTTP failures** | Transient errors exhausted retries (timeout, connect, or 429/502/503/504) | Increase `TERMRENAMER_HTTP_MAX_ATTEMPTS` or backoff base within reason; check network and provider status; see logs for attempt counts (no secrets logged) |
| **Permission denied** on apply | Insufficient filesystem permissions | Run from a user-owned test folder first; avoid system-protected directories |
| **Destination exists at apply time** | Another process wrote a file after preview | Re-scan and rebuild the plan; the apply step skips conflicting items with a reason |
| **Stale: source changed since plan** | File modified between preview and apply | Re-run planning; fingerprints include size and mtime |

## Logging

- **Bootstrap:** **INFO** to **stderr** via stdlib `logging` (`setup_logging()` in `app_bootstrap`).
- **TUI running:** On mount, `TermRenamerApp` removes the stderr `StreamHandler` and attaches a handler that writes to the **Logs** view (`l`), so `httpx` and other library logs appear in the UI instead of corrupting the terminal. Early errors before the UI mounts still go to stderr.
- **`TERMRENAMER_LOG_FILE`:** Read into settings but **file logging is not yet wired** in `setup_logging()`. To capture **raw** stderr (e.g. startup failures), redirect stderr (PowerShell: `python -m termrenamer 2> termrenamer.log`; bash: `python -m termrenamer 2> termrenamer.log`). **Do not** paste log lines containing tokens into public bug reports.
- **Operation id:** the TUI and logs do not show a short correlation id; include the **timestamp** and **repro steps** in bug reports instead.

## Safe rerun

- **Planning / preview**: safe to rerun; no renames occur until **confirmed apply**.
- **After partial apply**: inspect per-operation results; fix underlying errors; re-plan remaining sources.
- **Deleting the SQLite cache** (`TERMRENAMER_CACHE_DB_PATH`): safe; the app falls back to network-only behavior. Remove the file or unset the env var to disable on-disk cache.

## Quality verification (developers)

From the repository root after `uv sync`:

```bash
uv run pytest -v --cov
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

`--cov` turns on **`pytest-cov`**: it measures line coverage of `src/termrenamer/`, prints the missing lines, and fails the run below **85%** (`[tool.coverage]` in `pyproject.toml`). Without `--cov`, pytest runs the tests only and prints no coverage report, so `uv run pytest tests/unit/<file>.py` checks one file. CI (`.github/workflows/ci.yml`) installs the dependencies with `uv sync --locked`, then runs these four checks on Linux and Windows, on each pull request and each push to `main`.

Run the TUI: `uv run python -m termrenamer`.

**Current TUI:** there is no embedded directory tree — `a` (file) and `f` (folder) queue sources via **textual-fspicker** modals; optional **Film** / **TV** Destination roots are set under **Settings** (`s`) or via `TERMRENAMER_*_DEST_FOLDER` at bootstrap.

## Links

- Overview and usage: [README](../README.md)
- Release-by-release changes: [CHANGELOG](../CHANGELOG.md)
- Supported environment variables: [`.env.example`](../.env.example)
