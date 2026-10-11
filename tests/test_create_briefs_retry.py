"""Offline checks for bounded, evidence-aware brief repair."""

from __future__ import annotations

import copy
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "editorial"))
import create_briefs  # noqa: E402


def reference(number: int) -> dict:
    return {
        "item_id": f"item-{number}",
        "version_id": f"version-{number}",
        "locator": {"type": "text", "quote": f"Quote {number}"},
    }


def brief(references: list[dict]) -> dict:
    return {
        "piece_id": "03",
        "claims": [{"claim_id": "03-c1", "evidence": references}],
    }


class BriefRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.items = {
            (f"item-{number}", f"version-{number}"): {"publisher_id": f"publisher-{number}"}
            for number in (1, 2, 3)
        }
        self.accepted = set(self.items)
        self.evidence = [
            {
                "item_id": f"item-{number}",
                "version_id": f"version-{number}",
                "publisher_id": f"publisher-{number}",
            }
            for number in (1, 2, 3)
        ]

    def test_retries_only_failed_piece_and_reuses_saved_response(self) -> None:
        original = brief([reference(1), reference(2)])
        corrected = brief([reference(1), reference(2), reference(3)])
        with tempfile.TemporaryDirectory() as temporary:
            run = pathlib.Path(temporary)
            (run / "prompts").mkdir()
            (run / "model").mkdir()
            (run / "prompts" / "repair_brief.md").write_text("Repair this brief.")
            with (
                patch.object(create_briefs, "align_text_quote", return_value=None),
                patch.object(create_briefs, "resolve_locator", return_value=None),
                patch.object(
                    create_briefs,
                    "request_json",
                    return_value=({"brief": corrected}, {"model": "test-model"}),
                ) as request,
            ):
                result = [copy.deepcopy(original)]
                self.assertTrue(create_briefs.repair_briefs(
                    run, result, self.accepted, self.items, self.evidence, {}, "policy"
                ))
                self.assertEqual(result[0], corrected)
                self.assertEqual(request.call_count, 1)
                self.assertTrue((run / "model/create-briefs-piece-03-retry-01-raw.json").is_file())

            with (
                patch.object(create_briefs, "align_text_quote", return_value=None),
                patch.object(create_briefs, "resolve_locator", return_value=None),
                patch.object(create_briefs, "request_json") as request,
            ):
                result = [copy.deepcopy(original)]
                self.assertTrue(create_briefs.repair_briefs(
                    run, result, self.accepted, self.items, self.evidence, {}, "policy"
                ))
                self.assertEqual(result[0], corrected)
                request.assert_not_called()

    def test_stops_after_two_invalid_repairs(self) -> None:
        original = brief([reference(1), reference(2)])
        with tempfile.TemporaryDirectory() as temporary:
            run = pathlib.Path(temporary)
            (run / "prompts").mkdir()
            (run / "model").mkdir()
            (run / "prompts" / "repair_brief.md").write_text("Repair this brief.")
            with (
                patch.object(create_briefs, "align_text_quote", return_value=None),
                patch.object(create_briefs, "resolve_locator", return_value=None),
                patch.object(
                    create_briefs,
                    "request_json",
                    return_value=({"brief": original}, {"model": "test-model"}),
                ) as request,
            ):
                self.assertFalse(create_briefs.repair_briefs(
                    run, [copy.deepcopy(original)], self.accepted, self.items,
                    self.evidence, {}, "policy",
                ))
                self.assertEqual(request.call_count, 2)
            log = json.loads((run / "model/create-briefs-repair-log.json").read_text())
            self.assertEqual(len(log), 2)
            self.assertTrue(all(entry["validation_error"] for entry in log))

    def test_does_not_call_model_when_three_publishers_are_unavailable(self) -> None:
        original = brief([reference(1), reference(2)])
        with tempfile.TemporaryDirectory() as temporary:
            run = pathlib.Path(temporary)
            with (
                patch.object(create_briefs, "align_text_quote", return_value=None),
                patch.object(create_briefs, "resolve_locator", return_value=None),
                patch.object(create_briefs, "request_json") as request,
            ):
                self.assertFalse(create_briefs.repair_briefs(
                    run, [original], self.accepted, self.items,
                    self.evidence[:2], {}, "policy",
                ))
                request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
