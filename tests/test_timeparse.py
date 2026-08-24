import unittest
from datetime import datetime, timedelta, timezone

from safari_cache_rescue.timeparse import parse_datetime, parse_duration, resolve_window


class TimeParsingTests(unittest.TestCase):
    def test_duration_units(self) -> None:
        self.assertEqual(parse_duration("30m"), timedelta(minutes=30))
        self.assertEqual(parse_duration("12h"), timedelta(hours=12))
        self.assertEqual(parse_duration("2d"), timedelta(days=2))

    def test_invalid_duration(self) -> None:
        for value in ("", "0h", "3w", "later"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_duration(value)

    def test_naive_iso_time_uses_local_timezone(self) -> None:
        self.assertIsNotNone(parse_datetime("2026-08-23T09:00:00").tzinfo)

    def test_default_recent_window(self) -> None:
        now = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
        start, end = resolve_window(None, None, None, "12h", now=now)
        self.assertEqual(start, now - timedelta(hours=12))
        self.assertEqual(end, now)

    def test_explicit_range_and_validation(self) -> None:
        start, end = resolve_window(
            None,
            "2026-08-23T09:00:00+08:00",
            "2026-08-23T18:00:00+08:00",
            None,
        )
        self.assertLess(start, end)
        with self.assertRaises(ValueError):
            resolve_window("12h", "2026-08-23T09:00:00", None, None)
        with self.assertRaises(ValueError):
            resolve_window(None, None, "2026-08-23T18:00:00", None)


if __name__ == "__main__":
    unittest.main()

