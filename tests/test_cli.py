import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from safari_cache_rescue.cli import (
    EXIT_CANDIDATE_UNAVAILABLE,
    EXIT_EXPORT_FAILED,
    EXIT_NO_CANDIDATES,
    EXIT_OK,
    EXIT_SOURCE_UNAVAILABLE,
    EXIT_USAGE,
    main,
)

from helpers import complete_html, create_blob, create_history, safari_paths


class CLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.history, self.cache = safari_paths(self.home)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, arguments):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(os.environ, {"HOME": str(self.home)}), patch(
            "pathlib.Path.home", return_value=self.home
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(arguments)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_json_output_has_stable_fields_and_full_hash(self) -> None:
        now = datetime.now(timezone.utc).astimezone()
        url = "https://json.example.test/page"
        data = complete_html("JSON Synthetic Page", url)
        create_history(self.history, [(url, "JSON Synthetic Page", now)])
        create_blob(self.cache, "8" * 40, data)

        result, output, error = self.run_cli(["find", url, "--json"])

        self.assertEqual(result, EXIT_OK, error)
        payload = json.loads(output)
        self.assertEqual(payload[0]["candidate_id"], hashlib.sha256(data).hexdigest())
        self.assertEqual(
            set(payload[0]),
            {
                "candidate_id",
                "sha256",
                "confidence",
                "title",
                "domain",
                "visit_time",
                "byte_length",
                "cache_version",
                "match_reasons",
            },
        )

    def test_low_confidence_hidden_unless_requested(self) -> None:
        create_blob(self.cache, "9" * 40, b"<html><title>Weak</title><body>needle")
        result, output, _ = self.run_cli(["find", "needle"])
        self.assertEqual(result, EXIT_NO_CANDIDATES)
        self.assertIn("No recoverable", output)

        result, output, _ = self.run_cli(["find", "needle", "--all-candidates"])
        self.assertEqual(result, EXIT_OK)
        self.assertIn("low", output)

    def test_recent_defaults_to_twelve_hours(self) -> None:
        now = datetime.now(timezone.utc).astimezone()
        create_history(self.history, [("https://recent.test", "Recent Test", now)])
        create_blob(self.cache, "A1" * 20, complete_html("Recent Test", "cached"))
        result, output, error = self.run_cli(["recent"])
        self.assertEqual(result, EXIT_OK, error)
        self.assertIn("Recent Test", output)

    def test_invalid_time_and_limit_return_usage_exit(self) -> None:
        result, _, error = self.run_cli(["recent", "--since", "forever"])
        self.assertEqual(result, EXIT_USAGE)
        self.assertIn("duration", error)
        result, _, error = self.run_cli(["recent", "--limit", "0"])
        self.assertEqual(result, EXIT_USAGE)
        self.assertIn("limit", error)

    def test_recent_without_sources_returns_source_unavailable(self) -> None:
        result, _, error = self.run_cli(["recent"])
        self.assertEqual(result, EXIT_SOURCE_UNAVAILABLE)
        self.assertIn("History", error)

    def test_export_exit_codes_and_overwrite_protection(self) -> None:
        data = complete_html("CLI Export Synthetic", "cached")
        create_blob(self.cache, "FF" * 20, data)
        digest = hashlib.sha256(data).hexdigest()
        output = self.home / "recovered.html"

        result, _, error = self.run_cli(["export", digest[:16], "--output", str(output)])
        self.assertEqual(result, EXIT_OK, error)
        self.assertEqual(output.read_bytes(), data)

        result, _, error = self.run_cli(["export", digest[:16], "--output", str(output)])
        self.assertEqual(result, EXIT_EXPORT_FAILED)
        self.assertIn("already exists", error)

        result, _, error = self.run_cli(["export", "0" * 64, "--output", str(self.home / "none.html")])
        self.assertEqual(result, EXIT_CANDIDATE_UNAVAILABLE)
        self.assertIn("no longer present", error)


if __name__ == "__main__":
    unittest.main()
