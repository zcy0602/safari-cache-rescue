import argparse
import json
import platform
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from .history import HistoryUnavailable
from .models import Candidate
from .recovery import (
    CacheUnavailable,
    CandidateUnavailable,
    ExportFailure,
    RecoveryEngine,
    default_cache_roots,
)
from .timeparse import resolve_window


EXIT_OK = 0
EXIT_NO_CANDIDATES = 1
EXIT_USAGE = 2
EXIT_SOURCE_UNAVAILABLE = 3
EXIT_CANDIDATE_UNAVAILABLE = 4
EXIT_EXPORT_FAILED = 5


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        raise ValueError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(prog="safari-rescue", description="Recover HTML from Safari's local cache")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="check Safari data access without changing anything")

    find_parser = subparsers.add_parser("find", help="find cached HTML by URL or keyword")
    find_parser.add_argument("query")
    _add_search_options(find_parser)

    recent_parser = subparsers.add_parser("recent", help="list recent recoverable HTML")
    _add_search_options(recent_parser)

    export_parser = subparsers.add_parser("export", help="export one candidate byte-for-byte")
    export_parser.add_argument("candidate_id")
    export_parser.add_argument("--output", required=True, type=Path)
    export_parser.add_argument("--force", action="store_true")
    export_parser.add_argument("--json", action="store_true", dest="json_output")
    return parser


def _add_search_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--since")
    parser.add_argument("--from", dest="start_value")
    parser.add_argument("--to", dest="end_value")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--all-candidates", action="store_true")


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        arguments = build_parser().parse_args(argv)
        if arguments.command == "doctor":
            return _doctor()
        engine = RecoveryEngine()
        if arguments.command == "export":
            return _export(engine, arguments)
        if arguments.limit <= 0:
            raise ValueError("--limit must be greater than zero")
        default_since = "12h" if arguments.command == "recent" else None
        start, end = resolve_window(
            arguments.since,
            arguments.start_value,
            arguments.end_value,
            default_since,
        )
        if arguments.command == "find":
            candidates = engine.find(arguments.query, start=start, end=end)
        else:
            assert start is not None and end is not None
            candidates = engine.recent(start, end)
        return _show_candidates(engine, candidates, arguments)
    except ValueError as error:
        print("error: {}".format(error), file=sys.stderr)
        return EXIT_USAGE
    except (HistoryUnavailable, CacheUnavailable) as error:
        print("error: {}".format(error), file=sys.stderr)
        return EXIT_SOURCE_UNAVAILABLE
    except CandidateUnavailable as error:
        print("error: {}".format(error), file=sys.stderr)
        return EXIT_CANDIDATE_UNAVAILABLE
    except ExportFailure as error:
        print("error: {}".format(error), file=sys.stderr)
        return EXIT_EXPORT_FAILED


def _doctor() -> int:
    print("safari-cache-rescue doctor")
    print("macOS: {} {}".format(platform.system(), platform.mac_ver()[0] or "unknown"))
    print("Python: {}.{}.{}".format(*sys.version_info[:3]))
    healthy = platform.system() == "Darwin" and sys.version_info >= (3, 9)

    try:
        history_reader = RecoveryEngine().history
        history_reader.probe()
        print("Safari History: readable")
    except HistoryUnavailable as error:
        healthy = False
        print("Safari History: unavailable ({})".format(error))

    try:
        sources = RecoveryEngine().blob_sources()
        print("Safari cache: readable ({} blobs across {} roots)".format(len(sources), len(default_cache_roots())))
    except CacheUnavailable as error:
        healthy = False
        print("Safari cache: unavailable ({})".format(error))

    if not healthy:
        print(
            "Grant Full Disk Access to Terminal/iTerm/Codex in System Settings > "
            "Privacy & Security > Full Disk Access, then restart that app."
        )
        return EXIT_SOURCE_UNAVAILABLE
    print("Safety: read-only scan; cookies, passwords, AutoFill, and SafariTabs are not accessed.")
    return EXIT_OK


def _show_candidates(engine: RecoveryEngine, candidates: List[Candidate], arguments: argparse.Namespace) -> int:
    for warning in engine.warnings:
        print("warning: {}".format(warning), file=sys.stderr)
    if not arguments.all_candidates:
        candidates = [candidate for candidate in candidates if candidate.confidence != "low"]
    candidates = candidates[: arguments.limit]
    if arguments.json_output:
        print(json.dumps([candidate.public_dict() for candidate in candidates], ensure_ascii=False, indent=2))
    elif candidates:
        print("ID               CONF    VISITED                   DOMAIN                  TITLE")
        for candidate in candidates:
            visited = candidate.visit_time.isoformat(timespec="seconds") if candidate.visit_time else "-"
            print(
                "{:<16} {:<7} {:<25} {:<23} {}".format(
                    candidate.candidate_id[:16],
                    candidate.confidence,
                    visited[:25],
                    candidate.domain[:23] or "-",
                    candidate.title[:80] or "(untitled)",
                )
            )
    else:
        print("No recoverable HTML candidates found.")
    return EXIT_OK if candidates else EXIT_NO_CANDIDATES


def _export(engine: RecoveryEngine, arguments: argparse.Namespace) -> int:
    output, report = engine.export(arguments.candidate_id, arguments.output, force=arguments.force)
    result = {"output": str(output), "report": str(report)}
    if arguments.json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("Exported: {}".format(output))
        print("Recovery report: {}".format(report))
        print("The HTML was not opened. Review it before opening because cached scripts may still run.")
    return EXIT_OK


def entrypoint() -> None:
    raise SystemExit(main())
