"""Interactive mode: ``safari-rescue`` with no arguments, in a terminal.

Rendering is inline, like a prompt: one redrawable "live" region at the bottom
of the output, and lines that are committed (status, export results, errors)
stay in the scrollback. Everything shown from a cached page goes through
``safe_text`` first.
"""

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from .history import HistoryUnavailable
from .i18n import Strings, detect_language
from .models import Candidate
from .recovery import (
    CacheUnavailable,
    CandidateUnavailable,
    ExportFailure,
    RecoveryEngine,
    decode_html,
    html_to_text,
    read_stable,
)
from .terminal import (
    BOLD,
    CYAN,
    DIM,
    GREEN,
    RED,
    YELLOW,
    Terminal,
    fit,
    pad,
    safe_text,
    strip_ansi,
    text_width,
    wrap,
)


WINDOWS: List[Tuple[str, timedelta]] = [
    ("1h", timedelta(hours=1)),
    ("12h", timedelta(hours=12)),
    ("24h", timedelta(hours=24)),
    ("3d", timedelta(days=3)),
    ("7d", timedelta(days=7)),
]
DEFAULT_WINDOW = 1
_CONFIDENCE_COLORS = {"high": GREEN, "medium": YELLOW, "low": DIM}
_UNSAFE_FILENAME = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]+')


class Live:
    """The redrawable region at the bottom of the output."""

    def __init__(self, terminal: Terminal):
        self.terminal = terminal
        self.height = 0

    def _clear(self) -> str:
        if not self.height:
            return ""
        up = "\x1b[{}A".format(self.height - 1) if self.height > 1 else ""
        return "\r" + up + "\x1b[J"

    def show(self, lines: Sequence[str]) -> None:
        width = self.terminal.size()[0] - 1
        # A line wider than the terminal would wrap and break the redraw arithmetic.
        safe = [line if text_width(line) <= width else fit(strip_ansi(line), width) for line in lines]
        self.terminal.write(self._clear() + "\n".join(safe))
        self.height = len(safe)

    def commit(self, lines: Sequence[str] = ()) -> None:
        """Replace the live region with ``lines`` that stay in the scrollback."""
        if lines:
            self.show(lines)
            self.terminal.write("\n")
        else:
            self.terminal.write(self._clear())
        self.height = 0


def _default_export_dir() -> Path:
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.cwd()


class InteractiveApp:
    def __init__(
        self,
        terminal: Terminal,
        strings: Strings,
        engine_factory: Callable[[], RecoveryEngine] = RecoveryEngine,
        export_dir: Optional[Path] = None,
        now: Optional[Callable[[], datetime]] = None,
    ):
        self.terminal = terminal
        self.s = strings
        self.engine_factory = engine_factory
        self.export_dir = export_dir
        self.now = now or (lambda: datetime.now().astimezone())
        self.live = Live(terminal)
        self.engine: Optional[RecoveryEngine] = None

    # Entry point -------------------------------------------------------

    def run(self) -> int:
        try:
            with self.terminal.session():
                try:
                    self._main_menu()
                finally:
                    self.live.commit()
        except (KeyboardInterrupt, EOFError):
            pass
        return 0

    def _main_menu(self) -> None:
        self._status()
        index = 0
        while True:
            labels = [
                self.s("menu_recent"),
                self.s("menu_search"),
                self.s("menu_check"),
                self.s("menu_quit"),
            ]
            choice = self._select(self.s("menu_title"), labels, index)
            if choice is None or choice == 3:
                return
            index = choice
            if choice == 0:
                self._browse(query=None)
            elif choice == 1:
                query = self._input(self.s("search_prompt"))
                if query:
                    self._browse(query=query)
            else:
                self._status()

    # Building blocks ---------------------------------------------------

    def _style(self, text: str, *codes: str) -> str:
        return self.terminal.style(text, *codes)

    def _width(self) -> int:
        return self.terminal.size()[0] - 1

    def _question(self, text: str, suffix: str = "") -> str:
        room = self._width() - 2 - text_width(suffix)
        return self._style("? ", CYAN) + self._style(fit(text, room), BOLD) + suffix

    def _hint(self, key: str) -> str:
        return self._style(fit(self.s(key), self._width()), DIM)

    def _select(self, title: str, options: Sequence[str], index: int = 0) -> Optional[int]:
        while True:
            lines = [self._question(title)]
            for position, option in enumerate(options):
                label = fit(option, self._width() - 2)
                if position == index:
                    lines.append(self._style("❯ ", CYAN) + self._style(label, BOLD))
                else:
                    lines.append("  " + label)
            lines.append(self._hint("hint_select"))
            self.live.show(lines)
            key = self.terminal.read_key()
            if key == "up":
                index = (index - 1) % len(options)
            elif key == "down":
                index = (index + 1) % len(options)
            elif key == "enter":
                return index
            elif key == "esc":
                return None
            elif key.isdigit() and 1 <= int(key) <= len(options):
                return int(key) - 1

    def _input(self, prompt: str, default: str = "") -> Optional[str]:
        value = default
        while True:
            label = prompt + ": "
            room = self._width() - 3 - text_width(label)
            shown = value
            while text_width(shown) > room and shown:
                shown = shown[1:]
            if shown != value:
                shown = "…" + shown[1:]
            cursor = self._style(" ", "7") if self.terminal.color else "_"
            line = self._style("? ", CYAN) + self._style(label, BOLD) + shown + cursor
            self.live.show([line, self._hint("hint_input")])
            key = self.terminal.read_key()
            if key == "enter":
                return value.strip()
            if key == "esc":
                return None
            if key == "backspace":
                value = value[:-1]
            elif key == "ctrl-u":
                value = ""
            elif len(key) == 1:
                value += key

    def _confirm(self, question: str) -> bool:
        return self._select(question, [self.s("no"), self.s("yes")]) == 1

    def _mark(self, ok: bool) -> str:
        return self._style("✓", GREEN) if ok else self._style("✗", RED)

    def _commit_wrapped(self, text: str, *codes: str) -> None:
        self.live.commit([self._style(line, *codes) for line in wrap(text, self._width())])

    # Screens -----------------------------------------------------------

    def _status(self) -> None:
        engine = self.engine_factory()
        try:
            engine.history.probe()
            history = "{} {}".format(self._mark(True), self.s("history_ok"))
            history_ok = True
        except HistoryUnavailable:
            history = "{} {}".format(self._mark(False), self.s("history_bad"))
            history_ok = False
        try:
            count = len(engine.blob_sources())
            cache = "{} {}".format(self._mark(True), self.s("cache_ok", count="{:,}".format(count)))
            cache_ok = True
        except CacheUnavailable:
            cache = "{} {}".format(self._mark(False), self.s("cache_bad"))
            cache_ok = False
        self.live.commit([history + "   " + cache])
        if not (history_ok and cache_ok):
            self._commit_wrapped(self.s("access_help"), YELLOW)
        self.live.commit([""])

    def _load(self, query: Optional[str], window: int) -> Optional[List[Candidate]]:
        self.live.show([self._style(self.s("scanning"), DIM)])
        self.engine = self.engine_factory()
        try:
            if query is None:
                end = self.now()
                candidates = self.engine.recent(end - WINDOWS[window][1], end)
            else:
                candidates = self.engine.find(query)
        except (HistoryUnavailable, CacheUnavailable) as error:
            self.live.commit(["{} {}".format(self._mark(False), self.s("source_error", error=error))])
            return None
        for warning in dict.fromkeys(self.engine.warnings):
            self.live.commit([self._style("! " + warning, YELLOW)])
        return candidates

    def _browse(self, query: Optional[str]) -> None:
        recent = query is None
        window = DEFAULT_WINDOW
        candidates = self._load(query, window)
        if candidates is None:
            return
        show_low = False
        text_filter = ""
        cursor = 0
        offset = 0
        while True:
            needle = text_filter.casefold()
            confident = [item for item in candidates if show_low or item.confidence != "low"]
            visible = [
                item
                for item in confident
                if not needle or needle in item.title.casefold() or needle in item.domain.casefold()
            ]
            cursor = min(cursor, max(len(visible) - 1, 0))
            _, rows = self.terminal.size()
            page = max(3, min(12, rows - 7))
            offset = min(max(offset, cursor - page + 1), cursor)

            if recent:
                title = self.s("recent_title", window=self.s("window_" + WINDOWS[window][0]))
            else:
                title = self.s("search_title", query=safe_text(query or ""))
            facts = [self.s("found", count=len(visible))]
            if not show_low and len(confident) < len(candidates):
                facts.append(self.s("low_hidden", count=len(candidates) - len(confident)))
            if text_filter:
                facts.append(self.s("filter", text=text_filter))
            lines = [self._question(title, self._style("  " + " · ".join(facts), DIM))]
            if visible:
                lines.extend(self._rows(visible, cursor, offset, page))
                lines.append(self._style("─" * min(self._width(), 60), DIM))
                lines.append(self._detail(visible[cursor]))
            else:
                if text_filter:
                    message = "no_match"
                elif candidates:
                    message = "only_low"
                else:
                    message = "no_results"
                lines.append("  " + self.s(message))
            lines.append(self._hint("hint_list_recent" if recent else "hint_list"))
            self.live.show(lines)

            key = self.terminal.read_key()
            if key == "up":
                cursor = max(cursor - 1, 0)
            elif key == "down":
                cursor = min(cursor + 1, max(len(visible) - 1, 0))
            elif key == "pageup":
                cursor = max(cursor - page, 0)
            elif key == "pagedown":
                cursor = min(cursor + page, max(len(visible) - 1, 0))
            elif key == "home":
                cursor = 0
            elif key == "end":
                cursor = max(len(visible) - 1, 0)
            elif key == "enter":
                if visible:
                    self._candidate_menu(visible[cursor])
            elif key in ("left", "right") and recent:
                step = -1 if key == "left" else 1
                new_window = min(max(window + step, 0), len(WINDOWS) - 1)
                if new_window != window:
                    window = new_window
                    reloaded = self._load(None, window)
                    if reloaded is None:
                        return
                    candidates, cursor, offset = reloaded, 0, 0
            elif key == "tab":
                show_low = not show_low
                cursor = offset = 0
            elif key == "backspace":
                text_filter = text_filter[:-1]
            elif key == "ctrl-u":
                text_filter = ""
            elif key == "esc":
                if not text_filter:
                    return
                text_filter = ""
            elif len(key) == 1:
                text_filter += key
                cursor = offset = 0

    def _rows(self, visible: Sequence[Candidate], cursor: int, offset: int, page: int) -> List[str]:
        width = self._width()
        domain_width = 22 if width >= 79 else 14
        title_width = max(width - (2 + 4 + 2 + 11 + 2 + domain_width + 2), 8)
        now = self.now()
        lines = []
        for position in range(offset, min(offset + page, len(visible))):
            item = visible[position]
            selected = position == cursor
            confidence = self._style(pad(self.s(item.confidence), 4), _CONFIDENCE_COLORS.get(item.confidence, ""))
            when = pad(_format_time(item.visit_time, now), 11)
            domain = pad(safe_text(item.domain) or "-", domain_width)
            title = fit(safe_text(item.title) or self.s("untitled"), title_width)
            marker = self._style("❯", CYAN) if selected else " "
            if selected:
                title = self._style(title, BOLD)
            lines.append("{} {}  {}  {}  {}".format(marker, confidence, when, domain, title))
        hidden_below = len(visible) - offset - page
        if hidden_below > 0:
            lines.append(self._style("  ↓ {}".format(hidden_below), DIM))
        return lines

    def _detail(self, item: Candidate) -> str:
        reasons = self.s("reason_separator").join(self.s.reason(reason) for reason in item.match_reasons)
        text = "  {} · {}".format(reasons or "-", _format_size(item.byte_length))
        return self._style(fit(text, self._width()), DIM)

    def _candidate_menu(self, candidate: Candidate) -> None:
        index = 0
        title = safe_text(candidate.title) or self.s("untitled")
        while True:
            options = [self.s("action_preview"), self.s("action_export"), self.s("action_back")]
            choice = self._select(title, options, index)
            if choice is None or choice == 2:
                return
            index = choice
            if choice == 0:
                self._preview(candidate)
            else:
                self._export(candidate)

    def _preview(self, candidate: Candidate) -> None:
        data = read_stable(candidate.source.path, candidate.source.offset)
        text = decode_html(data) if data is not None else None
        if text is None:
            self.live.commit(["{} {}".format(self._mark(False), self.s("preview_gone"))])
            return
        body_width = self._width() - 2
        lines: List[str] = []
        for paragraph in html_to_text(text):
            lines.extend(wrap(safe_text(paragraph), body_width))
        if not lines:
            lines = [self.s("preview_empty")]
        title = self.s("preview_title", title=safe_text(candidate.title) or self.s("untitled"))
        top = 0
        while True:
            height = max(3, self.terminal.size()[1] - 4)
            top = min(max(top, 0), max(len(lines) - height, 0))
            end = min(top + height, len(lines))
            position = self._style("  {}-{}/{}".format(top + 1, end, len(lines)), DIM)
            view = ["  " + line for line in lines[top:end]]
            self.live.show([self._question(title, position)] + view + [self._hint("hint_preview")])
            key = self.terminal.read_key()
            if key == "up":
                top -= 1
            elif key == "down":
                top += 1
            elif key in ("pageup",):
                top -= height
            elif key in ("pagedown", " "):
                top += height
            elif key == "home":
                top = 0
            elif key == "end":
                top = len(lines)
            elif key in ("esc", "enter", "q"):
                return

    def _export(self, candidate: Candidate) -> None:
        assert self.engine is not None
        value = self._input(self.s("export_prompt"), _display_path(self._default_export_path(candidate)))
        if not value:
            return
        output = Path(value).expanduser()
        report = Path(str(output) + ".recovery.json")
        force = False
        if output.exists() or report.exists():
            if not self._confirm(self.s("overwrite", path=_display_path(output))):
                return
            force = True
        try:
            exported, report_path = self.engine.export(candidate.candidate_id, output, force=force)
        except (CandidateUnavailable, CacheUnavailable, ExportFailure) as error:
            self.live.commit(["{} {}".format(self._mark(False), self.s("export_failed", error=error))])
            return
        self.live.commit(["{} {}".format(self._mark(True), self.s("exported", path=_display_path(exported)))])
        self.live.commit([self._style("  " + self.s("report", path=_display_path(report_path)), DIM)])
        self._commit_wrapped("  " + self.s("export_warning"), YELLOW)

    def _default_export_path(self, candidate: Candidate) -> Path:
        directory = self.export_dir or _default_export_dir()
        stem = _UNSAFE_FILENAME.sub("-", safe_text(candidate.title)).strip(" .-")[:80] or "recovered"
        path = directory / (stem + ".html")
        number = 2
        while path.exists() or Path(str(path) + ".recovery.json").exists():
            path = directory / "{} ({}).html".format(stem, number)
            number += 1
        return path


def _format_time(value: Optional[datetime], now: datetime) -> str:
    if value is None:
        return "-"
    local = value.astimezone(now.tzinfo)
    return local.strftime("%H:%M") if local.date() == now.date() else local.strftime("%m-%d %H:%M")


def _format_size(size: int) -> str:
    if size < 1024:
        return "{} B".format(size)
    if size < 1024 * 1024:
        return "{:.0f} KB".format(size / 1024)
    return "{:.1f} MB".format(size / 1024 / 1024)


def _display_path(path: Path) -> str:
    home = str(Path.home())
    text = str(path)
    if text == home or text.startswith(home + "/"):
        return "~" + text[len(home) :]
    return text


def run_interactive() -> int:
    return InteractiveApp(Terminal(), Strings(detect_language())).run()
