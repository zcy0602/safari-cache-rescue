"""Minimal terminal I/O for the interactive mode: key reading, styling, display width.

Standard library only. Rendering is inline (no alternate screen), so whatever
the interactive mode commits stays in the terminal's scrollback.
"""

import os
import re
import select
import shutil
import sys
import unicodedata
from contextlib import contextmanager
from typing import Iterator, TextIO, Tuple


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_ESCAPE_KEYS = {
    "[A": "up",
    "[B": "down",
    "[C": "right",
    "[D": "left",
    "OA": "up",
    "OB": "down",
    "OC": "right",
    "OD": "left",
    "[H": "home",
    "[F": "end",
    "OH": "home",
    "OF": "end",
    "[1~": "home",
    "[4~": "end",
    "[5~": "pageup",
    "[6~": "pagedown",
}
_CONTROL_KEYS = {
    "\r": "enter",
    "\n": "enter",
    "\t": "tab",
    "\x7f": "backspace",
    "\x08": "backspace",
    "\x15": "ctrl-u",
    "\x04": "esc",
}

BOLD = "1"
DIM = "2"
RED = "31"
GREEN = "32"
YELLOW = "33"
CYAN = "36"


# C0/C1 controls (including ESC) and bidi overrides: page text must not drive or spoof the terminal.
_UNSAFE = re.compile("[\x00-\x1f\x7f-\x9f؜‎‏‪-‮⁦-⁩]")


def safe_text(text: str) -> str:
    """Make untrusted text (titles, page text) safe to print to a terminal."""
    return _UNSAFE.sub(" ", text)


def char_width(character: str) -> int:
    if unicodedata.combining(character):
        return 0
    return 2 if unicodedata.east_asian_width(character) in ("W", "F") else 1


def text_width(text: str) -> int:
    return sum(char_width(character) for character in _ANSI.sub("", text))


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def fit(text: str, width: int) -> str:
    """Truncate plain ``text`` to ``width`` display columns, ending with an ellipsis if cut."""
    if width <= 0:
        return ""
    if text_width(text) <= width:
        return text
    result = []
    used = 0
    for character in text:
        size = char_width(character)
        if used + size > width - 1:
            break
        result.append(character)
        used += size
    return "".join(result) + "…"


def pad(text: str, width: int) -> str:
    fitted = fit(text, width)
    return fitted + " " * (width - text_width(fitted))


def wrap(text: str, width: int) -> list:
    """Wrap one paragraph to ``width`` columns, breaking at spaces when possible (CJK-aware)."""
    lines = []
    line = ""
    line_width = 0
    last_space = -1
    for character in text:
        size = char_width(character)
        if line_width + size > width and line:
            if character != " " and last_space > 0:
                lines.append(line[:last_space])
                line = line[last_space + 1 :]
            else:
                lines.append(line)
                line = ""
            line_width = text_width(line)
            last_space = -1
            if character == " " and not line:
                continue
        line += character
        line_width += size
        if character == " ":
            last_space = len(line) - 1
    if line:
        lines.append(line)
    return lines


class Terminal:
    def __init__(self, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout, color: bool = True):
        self.stdin = stdin
        self.stdout = stdout
        self.color = color and "NO_COLOR" not in os.environ

    def style(self, text: str, *codes: str) -> str:
        if not self.color or not codes or not text:
            return text
        return "\x1b[{}m{}\x1b[0m".format(";".join(codes), text)

    def size(self) -> Tuple[int, int]:
        columns, rows = shutil.get_terminal_size((80, 24))
        return max(columns, 20), max(rows, 8)

    def write(self, text: str) -> None:
        self.stdout.write(text)
        self.stdout.flush()

    @contextmanager
    def session(self) -> Iterator[None]:
        import termios
        import tty

        fd = self.stdin.fileno()
        previous = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            self.write("\x1b[?25l")
            yield
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, previous)
            self.write("\x1b[?25h")

    def _read_byte(self, fd: int) -> bytes:
        data = os.read(fd, 1)
        if not data:
            raise EOFError
        return data

    def _pending(self, fd: int, timeout: float = 0.03) -> bool:
        return bool(select.select([fd], [], [], timeout)[0])

    def read_key(self) -> str:
        """Return a key name (``up``, ``enter``, ``esc``…), one typed character, or ``""``."""
        fd = self.stdin.fileno()
        first = self._read_byte(fd)
        if first == b"\x03":
            raise KeyboardInterrupt
        if first == b"\x1b":
            if not self._pending(fd):
                return "esc"
            sequence = self._read_byte(fd).decode("latin-1")
            if sequence in ("[", "O"):
                while self._pending(fd):
                    character = self._read_byte(fd).decode("latin-1")
                    sequence += character
                    if "@" <= character <= "~" and len(sequence) > 1:
                        break
            return _ESCAPE_KEYS.get(sequence, "")
        lead = first[0]
        if lead < 0x80:
            character = first.decode("ascii")
            if character in _CONTROL_KEYS:
                return _CONTROL_KEYS[character]
            return character if character.isprintable() else ""
        length = 2 if lead >= 0xC0 else 1
        if lead >= 0xE0:
            length = 3
        if lead >= 0xF0:
            length = 4
        data = first
        while len(data) < length and self._pending(fd, 0.1):
            data += self._read_byte(fd)
        character = data.decode("utf-8", errors="replace")
        return character if character.isprintable() else ""
