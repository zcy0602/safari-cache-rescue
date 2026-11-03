import hashlib
import json
import tempfile
import unittest
from io import BytesIO
from datetime import datetime, timedelta, timezone
from pathlib import Path

from safari_cache_rescue.history import HistoryUnavailable
from safari_cache_rescue.recovery import (
    CacheUnavailable,
    CandidateUnavailable,
    ExportFailure,
    RecoveryEngine,
    decode_html,
    read_stable,
)

from helpers import complete_html, create_blob, create_history, safari_paths


class RecoveryEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.history_path, self.cache_root = safari_paths(self.home)
        self.now = datetime.now(timezone.utc).astimezone()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def engine(self) -> RecoveryEngine:
        return RecoveryEngine(self.history_path, [self.cache_root])

    def test_exact_url_and_history_title_produce_high_confidence(self) -> None:
        url = "https://example.test/missing-page"
        title = "Synthetic Recovery Handbook"
        data = complete_html(title, '<a href="{}">source</a>'.format(url))
        create_history(self.history_path, [(url, title, self.now)])
        create_blob(self.cache_root, "A" * 40, data)

        candidates = self.engine().find(url)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].confidence, "high")
        self.assertEqual(candidates[0].domain, "example.test")
        self.assertEqual(candidates[0].sha256, hashlib.sha256(data).hexdigest())
        self.assertNotIn(str(self.home), json.dumps(candidates[0].public_dict()))

    def test_url_query_does_not_match_unrelated_html_with_common_url_terms(self) -> None:
        url = "https://target.example.test/missing-page"
        create_history(self.history_path, [(url, "Target Synthetic Page", self.now)])
        create_blob(
            self.cache_root,
            "00" * 20,
            complete_html("Unrelated Page", "https://other.example.test/common"),
        )
        create_blob(
            self.cache_root,
            "09" * 20,
            complete_html("Target Synthetic Page", "cached without a canonical URL"),
        )

        candidates = self.engine().find(url)

        self.assertEqual([candidate.title for candidate in candidates], ["Target Synthetic Page"])
        self.assertEqual(candidates[0].confidence, "high")

    def test_keyword_title_match_is_medium_without_history(self) -> None:
        data = complete_html("Workshop Recovery Handbook", "synthetic public text")
        create_blob(self.cache_root, "B" * 40, data)
        engine = self.engine()

        candidates = engine.find("Workshop Recovery")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].confidence, "medium")
        self.assertTrue(engine.warnings)

    def test_weak_or_incomplete_match_is_low(self) -> None:
        data = b"<html><head><title>Unfinished cache</title></head><body>needle"
        create_blob(self.cache_root, "C" * 40, data)

        candidates = self.engine().find("needle")

        self.assertEqual(candidates[0].confidence, "low")

    def test_recent_matches_history_window_and_ignores_old_visit(self) -> None:
        recent_url = "https://recent.example.test/page"
        old_url = "https://old.example.test/page"
        create_history(
            self.history_path,
            [
                (recent_url, "Recent Synthetic Page", self.now - timedelta(hours=1)),
                (old_url, "Old Synthetic Page", self.now - timedelta(days=3)),
            ],
        )
        create_blob(self.cache_root, "D" * 40, complete_html("Recent Synthetic Page", "cached"))
        create_blob(self.cache_root, "E" * 40, complete_html("Old Synthetic Page", "cached"))

        candidates = self.engine().recent(self.now - timedelta(hours=12), self.now)

        self.assertEqual([candidate.title for candidate in candidates], ["Recent Synthetic Page"])
        self.assertEqual(candidates[0].confidence, "high")

    def test_recent_does_not_treat_an_outbound_url_as_page_identity(self) -> None:
        create_history(self.history_path, [("https://github.com/", "GitHub", self.now)])
        create_blob(
            self.cache_root,
            "04" * 20,
            complete_html("Unrelated Synthetic Page", '<a href="https://github.com/">GitHub</a>'),
        )

        candidates = self.engine().recent(self.now - timedelta(hours=1), self.now)

        self.assertEqual(candidates, [])

    def test_recent_matches_history_url_to_canonical_url(self) -> None:
        url = "https://canonical.example.test/page"
        data = (
            '<!doctype html><html><head><title>Canonical Synthetic</title>'
            '<link rel="canonical" href="{}"></head><body>cached</body></html>'.format(url)
        ).encode()
        create_history(self.history_path, [(url, "Different History Title", self.now)])
        create_blob(self.cache_root, "05" * 20, data)

        candidates = self.engine().recent(self.now - timedelta(hours=1), self.now)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].confidence, "high")
        self.assertEqual(candidates[0].domain, "canonical.example.test")

    def test_url_find_uses_canonical_and_ignores_same_url_as_an_outbound_link(self) -> None:
        url = "https://target.example.test/page"
        canonical = (
            '<!doctype html><html><head><title>Canonical Target</title>'
            '<link rel="canonical" href="{}"></head><body>cached</body></html>'.format(url)
        ).encode()
        create_blob(self.cache_root, "06" * 20, canonical)
        create_blob(
            self.cache_root,
            "07" * 20,
            complete_html("Unrelated Link Page", '<a href="{}">source</a>'.format(url)),
        )

        candidates = self.engine().find(url)

        self.assertEqual([candidate.title for candidate in candidates], ["Canonical Target"])
        self.assertEqual(candidates[0].confidence, "high")
        self.assertEqual(candidates[0].domain, "target.example.test")

    def test_recent_requires_history(self) -> None:
        create_blob(self.cache_root, "F" * 40, complete_html("Synthetic", "cached"))
        with self.assertRaises(HistoryUnavailable):
            self.engine().recent(self.now - timedelta(hours=12), self.now)

    def test_empty_readable_cache_reports_no_blobs(self) -> None:
        self.cache_root.mkdir(parents=True)
        with self.assertRaisesRegex(CacheUnavailable, "no Safari WebKit cache blobs"):
            self.engine().blob_sources()

    def test_denied_cache_reports_full_disk_access(self) -> None:
        class DeniedRoot:
            def exists(self):
                raise PermissionError("denied")

        engine = RecoveryEngine(self.history_path, [DeniedRoot()])
        with self.assertRaisesRegex(CacheUnavailable, "Full Disk Access"):
            engine.blob_sources()

    def test_find_time_window_requires_matching_history_entry(self) -> None:
        create_history(
            self.history_path,
            [
                (
                    "https://current.example.test/page",
                    "FilterTerm Current Alpha",
                    self.now - timedelta(hours=1),
                ),
                (
                    "https://old.example.test/page",
                    "FilterTerm Ancient Omega",
                    self.now - timedelta(days=3),
                ),
            ],
        )
        create_blob(
            self.cache_root,
            "01" * 20,
            complete_html("FilterTerm Current Alpha", "cached"),
        )
        create_blob(
            self.cache_root,
            "02" * 20,
            complete_html("FilterTerm Ancient Omega", "cached"),
        )

        candidates = self.engine().find(
            "FilterTerm",
            start=self.now - timedelta(hours=12),
            end=self.now,
        )

        self.assertEqual([candidate.title for candidate in candidates], ["FilterTerm Current Alpha"])

    def test_malformed_history_falls_back_for_find_but_not_recent(self) -> None:
        self.history_path.parent.mkdir(parents=True)
        self.history_path.write_text("not sqlite", encoding="utf-8")
        create_blob(self.cache_root, "03" * 20, complete_html("Fallback Synthetic", "fallback term"))
        engine = self.engine()

        self.assertEqual(len(engine.find("fallback term")), 1)
        self.assertTrue(engine.warnings)
        with self.assertRaises(HistoryUnavailable):
            self.engine().recent(self.now - timedelta(hours=12), self.now)

    def test_utf16_html_and_non_html_filtering(self) -> None:
        utf16 = complete_html("UTF16 Synthetic Page", "recovery term", encoding="utf-16")
        create_blob(self.cache_root, "1" * 40, utf16)
        create_blob(self.cache_root, "2" * 40, b"\x00\x01not an html document")

        candidates = self.engine().find("UTF16 Synthetic")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].title, "UTF16 Synthetic Page")
        self.assertIsNotNone(decode_html(utf16))

    def test_canonical_link_with_href_before_rel_is_recognized(self) -> None:
        url = "https://order.example.test/page"
        data = (
            '<!doctype html><html><head><title>Attribute Order Synthetic</title>'
            "<link href='{}' data-x=1 rel=\"alternate canonical\"></head>"
            "<body>cached</body></html>".format(url)
        ).encode()
        create_blob(self.cache_root, "08" * 20, data)

        candidates = self.engine().find(url)

        self.assertEqual([candidate.title for candidate in candidates], ["Attribute Order Synthetic"])
        self.assertEqual(candidates[0].confidence, "high")

    def test_legacy_charset_declared_in_meta_is_decoded(self) -> None:
        for label, encoding, title in (
            ("gb2312", "gb18030", "合成恢复手册"),
            ("Shift_JIS", "cp932", "合成の復旧ハンドブック"),
        ):
            with self.subTest(label=label):
                data = (
                    '<!doctype html><html><head><meta http-equiv="Content-Type" '
                    'content="text/html; charset={}"><title>{}</title></head>'
                    "<body>cached</body></html>".format(label, title)
                ).encode(encoding)
                self.assertIsNone(_try_utf8(data))
                create_blob(self.cache_root, hashlib.sha1(data).hexdigest(), data)

                candidates = self.engine().find(title)

                self.assertEqual([candidate.title for candidate in candidates], [title])
                self.assertEqual(candidates[0].confidence, "medium")

    def test_stray_invalid_byte_does_not_hide_utf8_page(self) -> None:
        data = complete_html("Stray Byte Synthetic", "broken MARK byte").replace(b"MARK", b"\xff")
        self.assertIsNone(_try_utf8(data))
        create_blob(self.cache_root, "0A" * 20, data)

        candidates = self.engine().find("Stray Byte Synthetic")

        self.assertEqual([candidate.title for candidate in candidates], ["Stray Byte Synthetic"])

    def test_duplicate_identical_blobs_are_coalesced(self) -> None:
        data = complete_html("Duplicate Synthetic", "duplicate recovery text")
        create_blob(self.cache_root, "3" * 40, data)
        create_blob(self.cache_root, "4" * 40, data)

        candidates = self.engine().find("duplicate recovery")

        self.assertEqual(len(candidates), 1)

    def test_export_is_byte_identical_and_report_has_no_source_path(self) -> None:
        url = "https://export.example.test/page"
        title = "Export Synthetic Page"
        data = complete_html(title, url)
        create_history(self.history_path, [(url, title, self.now)])
        source = create_blob(self.cache_root, "5" * 40, data)
        source_hash_before = hashlib.sha256(source.read_bytes()).hexdigest()
        candidate = self.engine().find(url)[0]
        output = self.home / "exports" / "recovered.html"

        exported, report_path = self.engine().export(candidate.candidate_id[:16], output)

        self.assertEqual(exported.read_bytes(), data)
        self.assertEqual(hashlib.sha256(exported.read_bytes()).hexdigest(), candidate.sha256)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_hash_before)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["sha256"], candidate.sha256)
        self.assertEqual(report["domain"], "export.example.test")
        self.assertNotIn(str(self.home), report_path.read_text(encoding="utf-8"))

    def test_export_refuses_overwrite_without_force(self) -> None:
        data = complete_html("Overwrite Synthetic", "overwrite recovery")
        create_blob(self.cache_root, "6" * 40, data)
        candidate = self.engine().find("overwrite recovery")[0]
        output = self.home / "recovered.html"
        self.engine().export(candidate.candidate_id, output)

        with self.assertRaises(ExportFailure):
            self.engine().export(candidate.candidate_id, output)
        self.engine().export(candidate.candidate_id, output, force=True)
        self.assertEqual(output.read_bytes(), data)

    def test_export_rejects_short_or_missing_candidate(self) -> None:
        create_blob(self.cache_root, "7" * 40, complete_html("Synthetic", "cached"))
        with self.assertRaises(CandidateUnavailable):
            self.engine().export("abc", self.home / "short.html")
        with self.assertRaises(CandidateUnavailable):
            self.engine().export("0" * 64, self.home / "missing.html")

    def test_read_stable_skips_blob_that_changes_during_read(self) -> None:
        data = complete_html("Changing Synthetic", "cached")

        class Stat:
            st_ino = 1
            st_size = len(data)

            def __init__(self, modified: int):
                self.st_mtime_ns = modified

        class ChangingPath:
            def __init__(self):
                self.stat_calls = 0

            def stat(self):
                self.stat_calls += 1
                return Stat(self.stat_calls)

            def open(self, mode):
                self.assert_mode = mode
                return BytesIO(data)

        self.assertIsNone(read_stable(ChangingPath()))


def _try_utf8(data: bytes):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


if __name__ == "__main__":
    unittest.main()
