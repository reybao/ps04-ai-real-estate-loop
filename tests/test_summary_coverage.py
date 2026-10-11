"""Regression check: unavailable candidates are not evidence coverage."""

from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class SummaryCoverageTests(unittest.TestCase):
    def test_unavailable_youtube_candidate_is_not_a_substantive_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run = pathlib.Path(temporary)
            (run / "run.json").write_text(json.dumps({
                "run_id": "fixture", "started_at": "2026-10-10T12:00:00Z",
                "as_of_date": "2026-10-10", "mode": "example", "previous_run_id": None,
            }))
            candidates = [
                {"item_id": "feed:1", "publisher_id": "publisher-a", "kind": "feed", "url": "https://example.org/a"},
                {"item_id": "youtube:live", "publisher_id": "publisher-b", "kind": "youtube", "url": "https://example.org/live"},
            ]
            (run / "candidates.jsonl").write_text("".join(json.dumps(row) + "\n" for row in candidates))
            (run / "eligible.jsonl").write_text(json.dumps(candidates[0]) + "\n")
            completed = subprocess.run(
                ["bash", str(ROOT / "reporting/summarize_run.sh"), str(run)],
                cwd=ROOT, text=True, capture_output=True, check=True,
            )
            summary = json.loads(completed.stdout)
            self.assertEqual(summary["counts"]["discovered"], 2)
            self.assertEqual(summary["source_coverage"]["basis"], "eligible_items")
            self.assertEqual(summary["source_coverage"]["kinds"], {"feed": 1})
            self.assertEqual(summary["source_coverage"]["independent_publishers"], ["publisher-a"])


if __name__ == "__main__":
    unittest.main()
