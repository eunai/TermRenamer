# Operator runbook — TermRenamer

This document complements the [README](../README.md) with practical troubleshooting. **Never commit API keys**; use the user settings file, a `.env` or your shell environment (see [`.env.example`](../.env.example)).

Settings come from three sources, highest first: `TERMRENAMER_*` environment variables, a `.env` in the folder you start the app from (that folder only, no parent folders), then the **user settings file**: `%APPDATA%\termrenamer\.env` on Windows (`AppData\Roaming` in your home folder when `APPDATA` is unset or empty), `$XDG_CONFIG_HOME/termrenamer/.env` on macOS and Linux (`~/.config/termrenamer/.env` when `XDG_CONFIG_HOME` is unset, empty or relative). The app starts when at least one Provider key is set; with none, the start-up error names the three key settings, says one is enough and prints the user settings file's full path.

## Common failures

| Symptom | Likely cause | What to check |
|--------|----------------|----------------|
| `No Provider API key is set` on startup (exit status 2) | None of `TERMRENAMER_TMDB_API_KEY`, `TERMRENAMER_TVDB_API_KEY` and `TERMRENAMER_OMDB_API_KEY` is set in any source (a `TERMRENAMER_TVDB_SUBSCRIBER_PIN` alone is not a key) | Copy `.env.example` to the user settings file path the message prints, set any one of the three keys, restart the app; for a clone, a `.env` at the repository root works when you start from that root |
| A key in a clone's `.env` is not found | The app reads a `.env` only from the exact folder it starts in, and no longer searches parent folders or its own source folder | Start from the folder that holds the `.env`, or move the keys to the user settings file |
| `Cannot read settings file` on startup (exit status 2) | The user settings file or a `.env` is unreadable or not UTF-8 | Fix the file's permissions, or save it as UTF-8 |
| `TMDB requires an API key`, then `No Plan was built.` (message line, Queue Stage) | `TERMRENAMER_TMDB_API_KEY` unset when TMDB is the selected Provider (marked "no key") | Set `TERMRENAMER_TMDB_API_KEY` in the user settings file the message names (or `.env`), or press `p` to pick a Provider that has a key |
| `OMDb requires an API key`, then `No Plan was built.` | `TERMRENAMER_OMDB_API_KEY` unset when OMDb is the selected Film Provider | Set `TERMRENAMER_OMDB_API_KEY` in the user settings file the message names (or `.env`), or press `p` to pick TMDB when its key is set |
| `TheTVDB requires an API key`, then `No Plan was built.` | `TERMRENAMER_TVDB_API_KEY` unset when TheTVDB is the selected TV Provider | Set `TERMRENAMER_TVDB_API_KEY` (and `TERMRENAMER_TVDB_SUBSCRIBER_PIN` if your account needs it) in the user settings file the message names (or `.env`) |
| `Invalid numeric value for <NAME>`, `Invalid integer value for <NAME>` or `Invalid boolean value for <NAME> (use true/false)` on startup (exit status 2); `<NAME>` is the setting | Bad value for `TERMRENAMER_HTTP_TIMEOUT_SECONDS`, `TERMRENAMER_HTTP_BACKOFF_BASE_SECONDS`, `TERMRENAMER_HTTP_MAX_ATTEMPTS`, `TERMRENAMER_HTTP_JITTER`, `TERMRENAMER_ENABLE_FOLDER_RENAME`, `TERMRENAMER_ENABLE_SEASON_FOLDERS` or `TERMRENAMER_SHOW_POSTERS` | Use numbers for timeouts/backoff/max attempts; for the on-off settings use `true`/`false`/`1`/`0`/`yes`/`no`/`on`/`off` (see `load_settings()` in `app_bootstrap.py`) |
| `Invalid value for TERMRENAMER_NAME_TAKEN (use suffix or skip)` or `Invalid value for TERMRENAMER_THEME (use dark or light)` on startup (exit status 2) | A value other than the two the setting takes | Set `TERMRENAMER_NAME_TAKEN` to `suffix` or `skip`, and `TERMRENAMER_THEME` to `dark` or `light` |
| `TERMRENAMER_HTTP_MAX_ATTEMPTS must be >= 1` | Max attempts set to 0 or negative | Set to at least `1` |
| HTTP **401** from TMDB | Invalid or revoked API key | Regenerate key in TMDB dashboard; verify no extra quotes/spaces in the user settings file or `.env` |
| HTTP **401** from TheTVDB | Bad API key or expired session | Set `TERMRENAMER_TVDB_API_KEY` (and `TERMRENAMER_TVDB_SUBSCRIBER_PIN` if your account requires it); the adapter re-logins at most once |
| HTTP **404** from TheTVDB during planning | Search results can expose a non-numeric `id` (for example `series-412429`); episode routes require the numeric **tvdb_id** | Use a build where `api/tvdb_v4` resolves `tvdb_id` (and sends `page` on episode list); negotiated-contract keys without a PIN are fine if your dashboard does not require one |
| HTTP **429** / slow planning | Rate limiting | Reduce batch size; wait; avoid sharing one key across many machines. Transport honors `Retry-After` when present and uses bounded backoff with optional jitter (see `util/http.py`) |
| The build stops with the Provider's message and `No Plan was built.` | A lookup failed: the Provider cannot be reached, rejects the key, or gave an answer the app cannot use, after the retries (timeout, connect, or 429/502/503/504). The queue is kept | Increase `TERMRENAMER_HTTP_MAX_ATTEMPTS` or backoff base within reason; check network and Provider status; press `l` for the log lines, then build the Plan again. A request line holds the method, the host and the path the app built, never its query string; a Provider key, TheTVDB login token or subscriber PIN of 8 or more characters shows as `***`; the app writes no log file |
| `HTTP <status> redirect from <host> not followed`, then `No Plan was built.`, when a build meets it (`<status>` is a 3xx status) | A TMDB, TheTVDB or OMDb answer asked the app to go to another address. No Provider request follows a redirect, so a key never goes there | Build the Plan again; if it repeats, check the Provider's status and report the host named |
| `No video was found in the queued Sources.` | The queue holds no video file (`.mkv`, `.mp4`, `.avi`, `.webm` or `.m4v`), or each Source is gone | Press `l` for why each Source was skipped; queue the right folder |
| `Some Sources were skipped: l shows why.` after a build | A queued file or folder no longer exists, a queued file is not a video, or a queued folder has become a link or junction to a folder (the Logs say `it is now a link to a folder, not entered`); the rest of the queue was planned | Press `l`; queue the Source again if it moved |
| `This folder cannot be read: <reason>` or `This path cannot be used: <reason>` on a file or folder dialog's error line | The folder is gone, the disk refuses to list or enter it, or (for a path typed in the file dialog) the disk cannot tell what it is, such as a name that is too long. The dialog stays open, the queue is unchanged, and a folder shows an empty listing; backspace goes up | Pick another folder or fix the path; check its permissions |
| `Already queued: …` | The path, compared without regard to letter case, is already in the queue | Nothing to do; `c` clears the queue at the Queue Stage |
| `Mode cannot change while a Plan is being built or applied.` (`Provider` or `Settings` in place of `Mode`, for `p` and `s`) | A build, an Apply or an Undo is running | Wait, or press `Esc` to cancel a build; an Apply or an Undo cannot be cancelled |
| `Mode cannot change while the new Match's episodes are looked up. esc abandons the change.` (`Provider` or `Settings` in place of `Mode`) | A TV Match picked with `t` is looking its episodes up | Wait, or press `Esc` to abandon the change |
| `Plan discarded: … changed. The queue is kept; build the Plan again.` | Mode, Provider, a Destination root, Folder rename, Season folder or Name taken changed while a Plan was shown | Build the Plan again with `b` |
| **Permission denied** on Apply | Insufficient filesystem permissions | Run from a user-owned test folder first; avoid system-protected directories. The Applied Stage lists the file as failed with the reason; `l` has every result |
| `destination exists at apply time` | Another process wrote a file after the Preview | Rebuild the Plan; Apply skips the file or Straggler with this reason and replaces nothing |
| `the folder … is now a link` or `the folder … is no longer the link the Plan found` as a reason on the Applied Stage | A folder on the way to a file's new name, a source folder or a folder Straggler became a link or junction after the Plan was built; or a link the Plan found now points elsewhere or is gone. Apply goes through a link only while it is that same link, with the same target, and enters no other | Check the folder; build the Plan again, then Apply |
| `stale: source changed since plan` | File modified between the Preview and Apply | Rebuild the Plan; the recorded size and modification time no longer match |
| A file stayed after Undo; the Logs say `Left …: changed since Apply`, `no longer at its new place`, `its old place is taken`, `its old folder no longer exists` or `its old folder is now a link or a file, or lies behind a link` | Undo puts a file back only while it is as Apply left it and its old name is free | Fix what the reason names, then move the file by hand; Undo runs once for each Apply |
| `Posters are unavailable: …` on `i`, or `Unavailable: …` on the Settings screen's Show posters row | The reason follows: `the posters extra is not installed`, `this terminal draws neither Sixel nor Kitty images`, or the check failed | Install the `posters` extra (see the README) or use a terminal that draws Sixel or Kitty images |
| `Posters on. They show when the screen is at least 100 columns by 35 rows.` | The screen is smaller than the panel needs | Make the terminal window at least 100 columns by 35 rows |
| A Title shows its name and `no poster` | The Provider gave no Poster (OMDb never does), the download failed (one line in the Logs), or the stored file cannot be drawn | Nothing to fix; rename is not affected |

## Logging

- **Bootstrap:** **INFO** to **stderr** via stdlib `logging` (`setup_logging()` in `app_bootstrap`).
- **TUI running:** On mount, `TermRenamerApp` removes the stderr `StreamHandler` and attaches a handler that writes to the **Logs** view (`l`), so the app's log lines and those of the libraries it uses appear in the UI instead of corrupting the terminal. Early errors before the UI mounts still go to stderr.
- **The Logs view:** `l` opens it from any Stage or view (not from a dialog or a text field) and `Esc` closes it. It holds the last 5000 log lines of the session, the messages the screen's message line gave, and the outcome of each file Apply and Undo handled, so after a failure or a skip it is where the reason is. There is no Activity tab; its lines are in the Logs.
- **`Left to you` and copy lines:** If Apply made a copy of a file at its new name (another drive, exFAT, a network share) and could not remove it after the move failed, the Logs say `A copy Apply made could not be removed after its move failed: <path>`; the original is still at its old name. After an Undo, a line `Left to you: <path>, a copy Apply made and could not remove; its source is still at its old place` names that copy again, and `Left to you: <path>, a copy Undo made and could not remove; the file is still at its new place` names a copy Undo made. Both are copies, not the only copy of a file: check that the original is where the line says, then delete the copy by hand. Nothing removes these automatically.
- **A leftover `.termrenamer-<hex>.part` file (Windows):** When a file goes to another drive, Apply writes the copy under the name `.termrenamer-<16 hex characters>.part` in the new folder and renames it to its new name when it is complete, and the original is removed only after that. A `.part` file is left only if the app or the machine stopped during a copy, or if Apply could not remove it (the Logs then name it as above). The original is still at its old place, so it is safe to delete the `.part` file; then build the Plan again.
- **`TERMRENAMER_LOG_FILE`:** Read into settings but **file logging is not yet wired** in `setup_logging()`. To capture **raw** stderr (e.g. startup failures), redirect stderr (PowerShell: `python -m termrenamer 2> termrenamer.log`; bash: `python -m termrenamer 2> termrenamer.log`). Both the Logs and stderr show a Provider key, TheTVDB login token or subscriber PIN of 8 or more characters as `***` (a secret a server echoes back in an error, or another library logs on its own, is masked only when it is one of these, and the PIN is also kept out by never being written to a log line), but a log line names your folders and files, so read it before you paste it into a public bug report.
- **Operation id:** the TUI and logs do not show a short correlation id; include the **timestamp** and **repro steps** in bug reports instead.

## Safe rerun

- **Planning / Preview**: safe to rerun; no renames occur until **confirmed Apply**.
- **After a partial Apply**: read the Applied Stage's "Not renamed" list, or `l` for every result; fix underlying errors; build the Plan again for what remains. `u` undoes the whole last Apply while the Applied Stage is shown: it puts files back only while they are as Apply left them, and never replaces anything. Undo is gone once you start a new batch or quit.
- **Deleting the SQLite cache** (the file `TERMRENAMER_CACHE_DB_PATH` names): safe, and it clears the cache; a session that starts with the setting still set makes a new file at its first lookup. To stop caching on disk, remove `TERMRENAMER_CACHE_DB_PATH` from the environment and from each settings file that sets it.

## Quality verification (developers)

From the repository root after `uv sync`:

```bash
uv run pytest -v --cov
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

`--cov` turns on **`pytest-cov`**: it measures line coverage of `src/termrenamer/`, prints the missing lines, and fails the run below **85%** (`[tool.coverage]` in `pyproject.toml`). Without `--cov`, pytest runs the tests only and prints no coverage report, so `uv run pytest tests/unit/<file>.py` checks one file. CI (`.github/workflows/ci.yml`) installs the dependencies with `uv sync --locked`, then runs these four checks on Linux and Windows, on each pull request and each push to `main`; it runs them once without the `posters` extra and once with it (`uv sync --locked --extra posters`). Locally, `uv sync --extra posters` adds the image package and `uv sync` removes it again.

Run the TUI: `uv run python -m termrenamer`.

**Current TUI:** there is no embedded directory tree — `a` (file) and `f` (folder) queue sources via **textual-fspicker** modals; optional **Film** / **TV** Destination roots are set under **Settings** (`s`) or via `TERMRENAMER_*_DEST_FOLDER` at bootstrap.

## Links

- Overview and usage: [README](../README.md)
- Release-by-release changes: [CHANGELOG](../CHANGELOG.md)
- Supported environment variables: [`.env.example`](../.env.example)
