import io
import os
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from safari_cache_rescue.cli import EXIT_USAGE, main
from safari_cache_rescue.i18n import EN, ZH, Strings, detect_language
from safari_cache_rescue.interactive import InteractiveApp
from safari_cache_rescue.recovery import RecoveryEngine, html_to_text
from safari_cache_rescue.terminal import Terminal, fit, pad, safe_text, strip_ansi, text_width, wrap

from helpers import complete_html, create_blob, create_history, create_record, safari_paths


class FakeTerminal(Terminal):
    """Feeds scripted keys and records output; raises KeyboardInterrupt when keys run out."""

    def __init__(self, keys: List[str], columns: int = 100, rows: int = 30):
        super().__init__(stdin=io.StringIO(), stdout=io.StringIO(), color=False)
        self.keys = list(keys)
        self.columns = columns
        self.rows = rows

    def size(self):
        return self.columns, self.rows

    @contextmanager
    def session(self):
        yield

    def read_key(self) -> str:
        if not self.keys:
            raise KeyboardInterrupt
        return self.keys.pop(0)

    @property
    def output(self) -> str:
        return strip_ansi(self.stdout.getvalue())


def typed(text: str) -> List[str]:
    return list(text)


class InteractiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.history, self.cache = safari_paths(self.home)
        self.now = datetime.now(timezone.utc).astimezone()
        self.exports = self.home / "exports"
        self.exports.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def app(self, keys: List[str], language: str = "en", columns: int = 100) -> FakeTerminal:
        terminal = FakeTerminal(keys, columns=columns)
        result = InteractiveApp(
            terminal,
            Strings(language),
            engine_factory=lambda: RecoveryEngine(self.history, [self.cache]),
            export_dir=self.exports,
            now=lambda: self.now,
        ).run()
        self.assertEqual(result, 0)
        return terminal

    def add_page(self, url: str, title: str, age: timedelta, body: str = "cached body") -> bytes:
        data = complete_html(title, "<p>{}</p><script>secret()</script>".format(body))
        create_record(self.cache, url, body=data)
        return data

    def test_recent_open_and_export_with_default_name(self) -> None:
        url = "https://recent.example.test/page"
        create_history(self.history, [(url, "Recent Synthetic", self.now - timedelta(hours=1))])
        data = self.add_page(url, "Recent Synthetic", timedelta(hours=1))

        terminal = self.app(["enter", "enter", "down", "enter", "enter"])

        self.assertIn("Cache: 1 entries", terminal.output)
        self.assertIn("Recent Synthetic", terminal.output)
        self.assertIn("cache record URL matches Safari history", terminal.output)
        exported = self.exports / "Recent Synthetic.html"
        self.assertEqual(exported.read_bytes(), data)
        self.assertTrue(Path(str(exported) + ".recovery.json").exists())
        self.assertIn("Exported", terminal.output)

    def test_default_export_name_avoids_existing_files(self) -> None:
        url = "https://recent.example.test/page"
        create_history(self.history, [(url, "Same: Name/Page", self.now)])
        data = self.add_page(url, "Same: Name/Page", timedelta(0))
        (self.exports / "Same- Name-Page.html").write_bytes(b"keep me")

        self.app(["enter", "enter", "down", "enter", "enter"])

        self.assertEqual((self.exports / "Same- Name-Page.html").read_bytes(), b"keep me")
        self.assertEqual((self.exports / "Same- Name-Page (2).html").read_bytes(), data)

    def test_typed_existing_path_requires_confirmation(self) -> None:
        url = "https://recent.example.test/page"
        create_history(self.history, [(url, "Overwrite Synthetic", self.now)])
        data = self.add_page(url, "Overwrite Synthetic", timedelta(0))
        target = self.exports / "target.html"
        target.write_bytes(b"old")
        keys = ["enter", "enter", "down", "enter", "ctrl-u"] + typed(str(target)) + ["enter"]

        self.app(keys + ["enter"])  # default answer is "No"
        self.assertEqual(target.read_bytes(), b"old")

        self.app(keys + ["down", "enter"])
        self.assertEqual(target.read_bytes(), data)

    def test_preview_shows_text_without_scripts(self) -> None:
        url = "https://preview.example.test/page"
        create_history(self.history, [(url, "Preview Synthetic", self.now)])
        self.add_page(url, "Preview Synthetic", timedelta(0), body="Readable paragraph")

        terminal = self.app(["enter", "enter", "enter"])

        self.assertIn("Readable paragraph", terminal.output)
        self.assertNotIn("secret()", terminal.output)

    def test_time_window_switch_reloads_recent(self) -> None:
        url = "https://old.example.test/page"
        create_history(self.history, [(url, "Two Days Old", self.now - timedelta(days=2))])
        self.add_page(url, "Two Days Old", timedelta(days=2))

        terminal = self.app(["enter", "right", "right"])

        before, _, after = terminal.output.partition("last 3 days")
        self.assertIn("No recoverable HTML found.", before)
        self.assertIn("Two Days Old", after)

    def test_search_filter_and_low_confidence_toggle(self) -> None:
        create_blob(self.cache, "A1" * 20, complete_html("Alpha Needle Page", "needle"))
        create_blob(self.cache, "A2" * 20, complete_html("Beta Needle Page", "needle"))
        create_blob(self.cache, "A3" * 20, b"<html><title>Weak Needle</title><body>needle")

        terminal = self.app(["down", "enter"] + typed("needle") + ["enter"] + typed("beta"))
        output = terminal.output
        self.assertIn("1 low-confidence hidden", output)
        self.assertIn("filter: beta", output)
        self.assertNotIn("Weak Needle", output)

        terminal = self.app(["down", "enter"] + typed("needle") + ["enter", "tab"])
        self.assertIn("Weak Needle", terminal.output)

    def test_only_low_confidence_results_explain_tab(self) -> None:
        create_blob(self.cache, "B1" * 20, b"<html><title>Weak</title><body>lonely")

        terminal = self.app(["down", "enter"] + typed("lonely") + ["enter"])

        self.assertIn("Press tab", terminal.output)

    def test_missing_sources_show_access_help(self) -> None:
        terminal = self.app(["enter"])

        self.assertIn("Safari History unavailable", terminal.output)
        self.assertIn("Full Disk Access", terminal.output)
        self.assertIn("Cannot read Safari data", terminal.output)

    def test_chinese_strings(self) -> None:
        url = "https://zh.example.test/page"
        create_history(self.history, [(url, "中文标题页面", self.now)])
        self.add_page(url, "中文标题页面", timedelta(0))

        terminal = self.app(["enter"], language="zh")

        self.assertIn("最近浏览", terminal.output)
        self.assertIn("缓存记录的网址与历史记录一致", terminal.output)

    def test_untrusted_title_cannot_emit_escape_sequences(self) -> None:
        create_blob(
            self.cache,
            "C1" * 20,
            complete_html("Evil\x1b]0;pwned\x07\x1b[2J Title", "evil body"),
        )

        terminal = self.app(["down", "enter"] + typed("evil") + ["enter", "enter", "enter"])

        raw = terminal.stdout.getvalue()
        self.assertIn("Evil", raw)
        self.assertIn("Preview · Evil", terminal.output)
        self.assertNotIn("\x1b]", raw)
        self.assertNotIn("\x1b[2J", raw)
        self.assertNotIn("\x07", raw)

    def test_rendered_lines_fit_narrow_terminal(self) -> None:
        url = "https://a-very-long-domain-name.example.test/page"
        title = "非常长的中文标题" * 6
        create_history(self.history, [(url, title, self.now)])
        self.add_page(url, title, timedelta(0))

        terminal = self.app(["enter"], columns=50)

        for line in terminal.output.replace("\r", "\n").split("\n"):
            self.assertLessEqual(text_width(line), 49, line)

    def test_every_english_string_has_a_chinese_translation(self) -> None:
        self.assertLessEqual(set(EN), set(ZH))


class TerminalHelperTests(unittest.TestCase):
    def test_width_aware_fit_pad_and_wrap(self) -> None:
        self.assertEqual(text_width("中文ab"), 6)
        self.assertEqual(fit("中文中文", 5), "中文…")
        self.assertEqual(text_width(pad("中", 4)), 4)
        self.assertEqual(wrap("alpha beta gamma", 11), ["alpha beta", "gamma"])
        self.assertTrue(all(text_width(line) <= 4 for line in wrap("一二三四五六", 4)))

    def test_safe_text_removes_controls_and_bidi_overrides(self) -> None:
        self.assertEqual(safe_text("a\x1b[31mb‮c\td"), "a [31mb c d")

    def test_read_key_parses_escape_sequences_and_utf8(self) -> None:
        read_fd, write_fd = os.pipe()
        try:
            with os.fdopen(read_fd, "rb", buffering=0) as reader:
                terminal = Terminal(stdin=reader, stdout=io.StringIO())
                for raw, expected in (
                    (b"\x1b[A", "up"),
                    (b"\x1b[6~", "pagedown"),
                    (b"\x1b", "esc"),
                    (b"\r", "enter"),
                    ("中".encode(), "中"),
                    (b"x", "x"),
                ):
                    os.write(write_fd, raw)
                    self.assertEqual(terminal.read_key(), expected)
                os.write(write_fd, b"\x03")
                with self.assertRaises(KeyboardInterrupt):
                    terminal.read_key()
        finally:
            os.close(write_fd)

    def test_html_to_text_drops_invisible_content(self) -> None:
        text = "<html><head><title>T</title><style>p{}</style></head><body><p>One</p><!-- c --><p>Two &amp; three</p></body></html>"
        self.assertEqual(html_to_text(text), ["One", "Two & three"])


class LanguageAndEntryTests(unittest.TestCase):
    def test_detect_language(self) -> None:
        self.assertEqual(detect_language({"LANG": "zh_CN.UTF-8"}), "zh")
        self.assertEqual(detect_language({"LANG": "en_US.UTF-8"}), "en")
        self.assertEqual(detect_language({"LC_ALL": "en_US.UTF-8", "LANG": "zh_CN.UTF-8"}), "en")
        self.assertEqual(detect_language({"SAFARI_RESCUE_LANG": "zh", "LC_ALL": "C"}), "zh")
        self.assertEqual(detect_language({}), "en")

    def test_no_arguments_without_a_terminal_is_a_usage_error(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(main([]), EXIT_USAGE)


if __name__ == "__main__":
    unittest.main()
