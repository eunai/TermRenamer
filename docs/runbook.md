# Operator runbook — TermRenamer

This document complements [`project_spec.md`](../internal/project_spec.md) with practical troubleshooting. **Never commit API keys**; use `.env` or your shell environment (see [`.env.example`](../../.env.example)).

## Common failures

| Symptom | Likely cause | What to check |
|--------|----------------|----------------|
| `ValidationError` about TMDB API key on startup | `TERMRENAMER_TMDB_API_KEY` unset | Copy `.env.example` → `.env`, set the key, restart the app |
| Must set TMDB key even when only using TheTVDB | `python -m termrenamer` loads settings with TMDB required by default | Set `TERMRENAMER_TMDB_API_KEY` in `.env` anyway; background in [`testing/20260414_02/validation_summary.md`](../internal/testing/20260414_02/validation_summary.md) (non-blocking residual risk) |
| `ValidationError` about OMDb API key | `TERMRENAMER_OMDB_API_KEY` unset when OMDb selected as film provider | Set `TERMRENAMER_OMDB_API_KEY` in `.env` or use TMDB for film mode instead |
| `ValidationError` for invalid numeric/boolean env | Bad value for `TERMRENAMER_HTTP_TIMEOUT_SECONDS`, `TERMRENAMER_HTTP_BACKOFF_BASE_SECONDS`, `TERMRENAMER_HTTP_MAX_ATTEMPTS`, or `TERMRENAMER_HTTP_JITTER` | Use numbers for timeouts/backoff/max attempts; for jitter use `true`/`false`/`1`/`0`/`yes`/`no`/`on`/`off` (see `load_settings()` in `app_bootstrap.py`) |
| `TERMRENAMER_HTTP_MAX_ATTEMPTS must be >= 1` | Max attempts set to 0 or negative | Set to at least `1` |
| HTTP **401** from TMDB | Invalid or revoked API key | Regenerate key in TMDB dashboard; verify no extra quotes/spaces in `.env` |
| HTTP **401** from TheTVDB | Bad API key or expired session | Set `TERMRENAMER_TVDB_API_KEY` (and `TERMRENAMER_TVDB_SUBSCRIBER_PIN` if your account requires it); the adapter re-logins at most once per §5.5 |
| HTTP **404** from TheTVDB during planning | Search results can expose a non-numeric `id` (for example `series-412429`); episode routes require the numeric **tvdb_id** | Use a build where `api/tvdb_v4` resolves `tvdb_id` (and sends `page` on episode list); negotiated-contract keys without a PIN are fine if your dashboard does not require one |
| HTTP **429** / slow planning | Rate limiting | Reduce batch size; wait; avoid sharing one key across many machines. Transport honors `Retry-After` when present and uses bounded backoff with optional jitter (see §12.4, `util/http.py`) |
| **`ProviderError` after repeated HTTP failures** | Transient errors exhausted retries (timeout, connect, or 429/502/503/504) | Increase `TERMRENAMER_HTTP_MAX_ATTEMPTS` or backoff base within reason; check network and provider status; see logs for attempt counts (no secrets logged) |
| **Permission denied** on apply | Insufficient filesystem permissions | Run from a user-owned test folder first; avoid system-protected directories |
| **Destination exists at apply time** | Another process wrote a file after preview | Re-scan and rebuild the plan; the apply step skips conflicting items with a reason |
| **Stale: source changed since plan** | File modified between preview and apply | Re-run planning; fingerprints include size and mtime |

## Logging

- **Bootstrap:** **INFO** to **stderr** via stdlib `logging` (`setup_logging()` in `app_bootstrap`).
- **TUI running:** On mount, `TermRenamerApp` removes the stderr `StreamHandler` and attaches a handler that writes to the **Logs** tab’s `RichLog`, so `httpx` and other library logs appear in the UI instead of corrupting the terminal. Early errors before the UI mounts still go to stderr.
- **`TERMRENAMER_LOG_FILE`:** Read into settings but **file logging is not yet wired** in `setup_logging()`. To capture **raw** stderr (e.g. startup failures), redirect stderr (PowerShell: `python -m termrenamer 2> termrenamer.log`; bash: `python -m termrenamer 2> termrenamer.log`). **Do not** paste log lines containing tokens into public bug reports.
- **Operation id:** Spec §12.7 calls for a short correlation id in the TUI/logs; if your build does not show it yet, include **timestamp** and **repro steps** instead.

## Safe rerun

- **Planning / preview**: safe to rerun; no renames occur until **confirmed apply**.
- **After partial apply**: inspect per-operation results; fix underlying errors; re-plan remaining sources.
- **Deleting the SQLite cache** (`TERMRENAMER_CACHE_DB_PATH`): safe; the app falls back to network-only behavior. Remove the file or unset the env var to disable on-disk cache.

## Quality verification (developers)

From the repository root after `pip install -e ".[dev]"`:

```bash
pytest -v
ruff check .
ruff format --check .
mypy src
```

`pytest -v` runs **`pytest-cov`** with a **≥ 85%** line-coverage minimum on `src/termrenamer/` (see `pyproject.toml`).

Run the TUI: `python -m termrenamer` (see spec §6).

**Current TUI (0.10+):** there is no embedded directory tree — **+ folder** / **+ file** (or **Ctrl+F**) queue sources via **textual-fspicker** modals; optional **Film** / **TV** output roots are set under **Settings** (**Ctrl+,**) or via `TERMRENAMER_*_DEST_FOLDER` at bootstrap.

## Links

- Specification: [`project_spec.md`](../internal/project_spec.md)
- PH-3 TUI polish campaign (PH-1 preview, FR-009, P0-07 confirm, OMDb, error UX — **PASSED**): [`testing/20260415_01/validation_summary.md`](../internal/testing/20260415_01/validation_summary.md) · [`testing_plan.md`](../internal/testing/20260415_01/testing_plan.md)
- Latest validation campaign (P1 / PH-2 scope): [`testing/20260414_02/validation_summary.md`](../internal/testing/20260414_02/validation_summary.md) · [`testing_plan.md`](../internal/testing/20260414_02/testing_plan.md)
- Prior campaign (P0): [`testing/20260414_01/testing_plan.md`](../internal/testing/20260414_01/testing_plan.md)
