# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A local-only, read-only macOS CLI (`safari-rescue`) that finds HTML documents still present in Safari's WebKit disk cache and exports them byte-for-byte. Pure Python 3.9+ stdlib, no third-party dependencies (keep it that way, and keep code 3.9-compatible: `typing.List`/`Optional`, no `match`, no `X | Y` types). `README.zh-Hans.md` is a Chinese translation of `README.md`; update both when user-facing behavior changes.

## Commands

```bash
# Run all tests (src/ must be importable; tests/ is on sys.path via -s so `from helpers import ...` works)
PYTHONPATH=src python3 -m unittest discover -s tests -v
# (or `python3 -m pip install -e .` once, then drop PYTHONPATH)

# Single test
PYTHONPATH=src:tests python3 -m unittest test_recovery.RecoveryEngineTests.test_export_refuses_overwrite_without_force -v

# Run the CLI from a checkout (the launcher sets PYTHONPATH itself)
./safari-rescue doctor | find <url-or-keywords> | recent | export <id-prefix> --output out.html
```

There is no linter or formatter configured. Tests run fine on Linux; they never touch real Safari data.

## Architecture

All code is in `src/safari_cache_rescue/`. Flow: `cli.py` → `RecoveryEngine` (`recovery.py`) → `HistoryReader` (`history.py`) + cache blob scan.

- **Two data sources.** `History.db` (SQLite, opened `mode=ro` + `PRAGMA query_only`; timestamps are seconds since the Apple epoch 2001-01-01 UTC) and WebKitCache blobs discovered via `Version */Blobs` under two roots (`~/Library/Caches/...` and the sandboxed `~/Library/Containers/com.apple.Safari/...`). Cache version is discovered, never hard-coded.
- **Matching (`RecoveryEngine._scan`).** Every blob is read with `read_stable` (skips files that change during read, >64 MiB, or non-HTML prefixes), decoded by `decode_html` (BOM → strict UTF-8 → `<meta charset>` mapped through WHATWG-style aliases such as gb2312→gb18030 → lenient `errors="replace"` fallback; decoded text is only for matching, export copies raw bytes), then scored against the query and history entries:
  - URL identity comes **only** from `<link rel="canonical">` (normalized via `normalize_url_identity`). A URL merely appearing as a link in the body is deliberately *not* a match — regressions here are covered by tests.
  - URL queries skip keyword/token matching entirely.
  - `recent` (and `find` with a time window) require a history match (canonical URL, exact title, or title overlap); plain `find` also accepts body/keyword hits.
  - Confidence: `high` = complete HTML + canonical URL or exact history title; `medium` = complete + title overlap / literal-in-title / ≥2 query tokens; else `low` (hidden by CLI unless `--all-candidates`).
  - Results are deduplicated by content SHA-256 and sorted by confidence, visit time, size.
- **History is optional for `find`, required for `recent`.** `find` falls back to cache-only matching and appends to `engine.warnings` (printed to stderr by the CLI); `recent` raises `HistoryUnavailable`.
- **Candidate IDs are the full content SHA-256.** `export` re-scans the cache, accepts a hex prefix ≥12 chars, rejects ambiguous prefixes, writes via temp file + SHA-256 verification + `os.replace`, and writes a `<output>.recovery.json` sidecar. Refuses to overwrite either file without `--force`.
- **CLI contract (`cli.py`).** Errors are exceptions mapped to exit codes in `main()`: 0 ok, 1 no candidates, 2 usage (`ValueError`; the custom `Parser.error` raises instead of exiting), 3 source unavailable, 4 candidate unavailable, 5 export failed. `--json` output for `find`/`recent` is a plain array of `Candidate.public_dict()` with a fixed key set (asserted in tests); human `recent` output additionally prints a cache-observation line, JSON does not.
- **Time windows (`timeparse.py`).** `--since` (`Nm`/`Nh`/`Nd`) is mutually exclusive with `--from`/`--to`; `--to` requires `--from`; naive ISO times get the local timezone. `recent` defaults to `12h`.

## Invariants to preserve

- Never write to Safari data, make network requests, open exported HTML, or read anything beyond `History.db` and WebKitCache (no cookies, passwords, AutoFill, SafariTabs, private browsing).
- Public output and recovery reports must not contain local filesystem paths of cache blobs (tests assert the home dir is absent).
- Tests use only synthetic fixtures built by `tests/helpers.py` (`create_history`, `create_blob`, `complete_html`) in a temp `HOME`; CLI tests patch `HOME`/`Path.home`. Never add real history, cache data, or recovered pages to fixtures.
