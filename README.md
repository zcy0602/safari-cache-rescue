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

From a local checkout, run it without installing or configuring `PYTHONPATH`:

```bash
./safari-rescue doctor
```

To install the `safari-rescue` command instead:

```bash
python3 -m pip install -e .
safari-rescue doctor
```

## Usage

### Interactive mode

Run the command without arguments in a terminal:

```bash
./safari-rescue
```

It checks access, then lets you browse recent pages or search, using the arrow
keys. In a result list, `←`/`→` change the time window (1 hour to 7 days),
`tab` shows low-confidence matches, typing filters by title or domain, and
`⏎` opens a candidate to preview its text or export it (by default to
`~/Downloads`, named after the page title). `esc` goes back, `ctrl-c` quits.

The interface follows `LANG` (Chinese or English); set `SAFARI_RESCUE_LANG=en`
or `zh` to override it, and `NO_COLOR=1` to disable colors. The subcommands
below are unchanged, always print English, and are what scripts should use.

### Commands

Search by an exact URL or keywords:

```bash
./safari-rescue find "https://example.com/missing-page"
./safari-rescue find "workshop handbook" --since 2d
```

Search recent Safari history. With no time option, `recent` uses the last 12 hours:

```bash
./safari-rescue recent
./safari-rescue recent --since 30m
./safari-rescue recent --from 2026-08-23T09:00:00+08:00 --to 2026-08-23T18:00:00+08:00
```

Human-readable `recent` output reports the current number of cache blobs and
the oldest and newest surviving blob modification times. This is an observation,
not a retention guarantee: Safari may evict entries at any time. JSON output is
unchanged and contains candidates only.

Low-confidence HTML is hidden by default. Use `--all-candidates` to include it.
Search commands also support `--limit 20` and `--json`.

Export only after reviewing the candidate list:

```bash
./safari-rescue export 525191d5f7f8f87 --output recovered.html
```

The tool copies the cache bytes unchanged and writes
`recovered.html.recovery.json`. It refuses to overwrite either file unless
`--force` is supplied.

## Confidence levels

- **high**: complete HTML whose cache-record URL or canonical URL matches, or whose title exactly matches a Safari-history title.
- **medium**: complete HTML with a title overlap or multiple query terms.
- **low**: related HTML with only weak evidence or signs of truncation.

Safari's cache is an internal, versioned implementation detail. This tool
discovers `Version *` directories instead of hard-coding one version. It reads
large bodies from `Blobs` and, on a best-effort basis, parses `Records` to learn
each cached page's request URL and to find small pages that WebKit stores inside
the record itself. Future Safari releases may still require updates; records
the tool cannot parse are skipped.

## Development

The test suite uses synthetic History databases and cache blobs only:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Do not add real browser history, cache data, cookies, or recovered copyrighted
pages to fixtures or bug reports.

## License

MIT
