# safari-cache-rescue

`safari-cache-rescue` is a small, local-only macOS command-line tool that looks
for HTML documents still present in Safari's WebKit disk cache. It was built for
the narrow emergency case where a recently visited page has disappeared from
the web but Safari may not have evicted its cached response yet.

It does **not** promise to recover every page. Dynamic applications, signed-in
content, streaming media, DRM, CSS, images, scripts, and API responses are out
of scope for the first release.

## Privacy and safety

- Reads Safari `History.db` and `WebKitCache` only.
- Never reads cookies, passwords, AutoFill, forms, SafariTabs, or private browsing data.
- Never uploads data or makes network requests.
- Never changes Safari data and never opens recovered HTML automatically.
- Does not create a browsing-history index. Candidate IDs are content SHA-256 hashes.
- Exported HTML may contain scripts or remote links. Review it before opening.

Safari data is protected by macOS. Grant **Full Disk Access** to the app that
runs the command (Terminal, iTerm, or Codex), then quit and reopen that app:

`System Settings > Privacy & Security > Full Disk Access`

## Requirements and installation

- macOS 14 or later
- Python 3.9 or later

From a local checkout:

```bash
python3 -m pip install -e .
safari-rescue doctor
```

You can also run it without installing:

```bash
PYTHONPATH=src python3 -m safari_cache_rescue doctor
```

## Usage

Search by an exact URL or keywords:

```bash
safari-rescue find "https://example.com/missing-page"
safari-rescue find "workshop handbook" --since 2d
```

Search recent Safari history. With no time option, `recent` uses the last 12 hours:

```bash
safari-rescue recent
safari-rescue recent --since 30m
safari-rescue recent --from 2026-08-23T09:00:00+08:00 --to 2026-08-23T18:00:00+08:00
```

Low-confidence HTML is hidden by default. Use `--all-candidates` to include it.
Search commands also support `--limit 20` and `--json`.

Export only after reviewing the candidate list:

```bash
safari-rescue export 525191d5f7f8f87 --output recovered.html
```

The tool copies the cache bytes unchanged and writes
`recovered.html.recovery.json`. It refuses to overwrite either file unless
`--force` is supplied.

## Confidence levels

- **high**: complete HTML with an exact URL hit or exact Safari-history title match.
- **medium**: complete HTML with a title overlap or multiple query terms.
- **low**: related HTML with only weak evidence or signs of truncation.

Safari's cache is an internal, versioned implementation detail. This tool
discovers `Version */Blobs` directories instead of hard-coding one version, but
future Safari releases may still require updates.

## Development

The test suite uses synthetic History databases and cache blobs only:

```bash
python3 -m unittest discover -s tests -v
```

Do not add real browser history, cache data, cookies, or recovered copyrighted
pages to fixtures or bug reports.

## License

MIT
