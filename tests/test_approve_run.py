"""Tests for explicit, recoverable terminal approval records."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("approve_run", ROOT / "review/approve_run.py")
assert SPEC and SPEC.loader
approve_run = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(approve_run)


class ApproveRunTests(unittest.TestCase):
    def test_record_preserves_existing_notes_for_same_approved_review(self) -> None:
        previous = {
            "review_id": "review-a", "decision": "approve",
            "notes": "Checked the six drafts and documented a limitation.",
        }
        record = approve_run.approval_record(
            "review-a", "student", "approve", "2026-10-10T18:18:54Z", previous,
        )
        self.assertEqual(record["notes"], previous["notes"])
        self.assertEqual(record["reviewed_at"], "2026-10-10T18:18:54Z")
        self.assertEqual(record["reviewer"], "student")

    def test_write_preserves_previous_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "approval.json"
            old = {"review_id": "old", "decision": "approve"}
            path.write_text(json.dumps(old), encoding="utf-8")
            new = approve_run.approval_record("new", "student", "revise", "2026-10-10T18:18:54Z")
            backup = approve_run.write_approval(path, new)
            self.assertIsNotNone(backup)
            self.assertEqual(json.loads(backup.read_text(encoding="utf-8")), old)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), new)

    def test_stale_saved_review_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "review.json").write_text(
                json.dumps({"passed": True, "review_id": "old"}), encoding="utf-8",
            )
            current = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=json.dumps({"passed": True, "review_id": "new"}), stderr="",
            )
            with patch.object(approve_run.subprocess, "run", return_value=current):
                with self.assertRaisesRegex(ValueError, "stale"):
                    approve_run.current_review(run_dir)

    def test_noninteractive_invocation_cannot_approve(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            result = subprocess.run(
                [sys.executable, str(ROOT / "review/approve_run.py"), str(run_dir)],
                input="1\n", text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("interactive terminal", result.stderr)
            self.assertFalse((run_dir / "approval.json").exists())

    def test_vscode_opens_script_then_article(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "articles").mkdir()
            (run_dir / "video_scripts").mkdir()
            (run_dir / "articles/01.md").write_text("# Article title\nArticle body", encoding="utf-8")
            (run_dir / "video_scripts/01.md").write_text("# Video title\nScript body", encoding="utf-8")
            viewer_result = subprocess.CompletedProcess(args=["code"], returncode=0)
            with patch.object(approve_run.shutil, "which", return_value="/usr/local/bin/code"), \
                 patch.object(approve_run.subprocess, "run", return_value=viewer_result) as viewer:
                approve_run.show_piece(run_dir, "01")
            self.assertEqual(viewer.call_count, 2)
            self.assertEqual(viewer.call_args_list[0].args[0][-1], str(run_dir / "video_scripts/01.md"))
            self.assertEqual(viewer.call_args_list[1].args[0][-1], str(run_dir / "articles/01.md"))
            self.assertTrue(all("--reuse-window" in call.args[0] for call in viewer.call_args_list))

    def test_interactive_approve_records_current_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            for folder in ("articles", "video_scripts"):
                (run_dir / folder).mkdir()
                for piece_id in ("01", "02", "03"):
                    (run_dir / folder / f"{piece_id}.md").write_text("Draft", encoding="utf-8")
            review = {"passed": True, "review_id": "current", "issues": []}
            with patch.object(approve_run.sys, "argv", ["approve_run.py", str(run_dir)]), \
                 patch.object(approve_run.sys.stdin, "isatty", return_value=True), \
                 patch.object(approve_run, "current_review", return_value=review), \
                 patch.object(approve_run, "reviewer_name", return_value="student"), \
                 patch.object(approve_run, "show_piece") as viewer, \
                 patch("builtins.input", side_effect=["1", "1", "1"]):
                self.assertEqual(approve_run.main(), 0)
            self.assertEqual([call.args[1] for call in viewer.call_args_list], ["01", "02", "03"])
            record = json.loads((run_dir / "approval.json").read_text(encoding="utf-8"))
            self.assertEqual(record["decision"], "approve")
            self.assertEqual(record["review_id"], "current")
            self.assertEqual(record["reviewer"], "student")
            self.assertTrue(record["reviewed_at"].endswith("Z"))
            self.assertEqual(
                [(row["piece_id"], row["decision"]) for row in record["piece_reviews"]],
                [("01", "approve"), ("02", "approve"), ("03", "approve")],
            )

    def test_second_piece_revise_stops_before_third(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            for folder in ("articles", "video_scripts"):
                (run_dir / folder).mkdir()
                for piece_id in ("01", "02", "03"):
                    (run_dir / folder / f"{piece_id}.md").write_text("Draft", encoding="utf-8")
            review = {"passed": True, "review_id": "current", "issues": []}
            with patch.object(approve_run.sys, "argv", ["approve_run.py", str(run_dir)]), \
                 patch.object(approve_run.sys.stdin, "isatty", return_value=True), \
                 patch.object(approve_run, "current_review", return_value=review), \
                 patch.object(approve_run, "reviewer_name", return_value="student"), \
                 patch.object(approve_run, "show_piece") as viewer, \
                 patch("builtins.input", side_effect=["1", "2", "Check source attribution", "n"]):
                self.assertEqual(approve_run.main(), 3)
            self.assertEqual([call.args[1] for call in viewer.call_args_list], ["01", "02"])
            record = json.loads((run_dir / "approval.json").read_text(encoding="utf-8"))
            self.assertEqual(record["decision"], "revise")
            self.assertIn("piece 02", record["notes"])
            self.assertIn("Check source attribution", record["notes"])
            self.assertEqual(len(record["piece_reviews"]), 2)
            self.assertEqual(record["piece_reviews"][-1]["revision_mode"], "manual")

    def test_api_revision_choice_requires_a_specific_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            for folder in ("articles", "video_scripts"):
                (run_dir / folder).mkdir()
                for piece_id in ("01", "02", "03"):
                    (run_dir / folder / f"{piece_id}.md").write_text("Draft", encoding="utf-8")
            review = {"passed": True, "review_id": "current", "issues": []}
            with patch.object(approve_run.sys, "argv", ["approve_run.py", str(run_dir)]), \
                 patch.object(approve_run.sys.stdin, "isatty", return_value=True), \
                 patch.object(approve_run, "current_review", return_value=review), \
                 patch.object(approve_run, "reviewer_name", return_value="student"), \
                 patch.object(approve_run, "show_piece"), \
                 patch("builtins.input", side_effect=["2", "", "y", "Clarify source attribution"]):
                self.assertEqual(approve_run.main(), 3)
            record = json.loads((run_dir / "approval.json").read_text(encoding="utf-8"))
            self.assertEqual(record["decision"], "revise")
            self.assertEqual(record["piece_reviews"][0]["revision_mode"], "api")
            self.assertEqual(record["piece_reviews"][0]["reason"], "Clarify source attribution")

    def test_cancel_preserves_existing_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            for folder in ("articles", "video_scripts"):
                (run_dir / folder).mkdir()
                for piece_id in ("01", "02", "03"):
                    (run_dir / folder / f"{piece_id}.md").write_text("Draft", encoding="utf-8")
            previous = '{"review_id":"current","decision":"revise"}\n'
            (run_dir / "approval.json").write_text(previous, encoding="utf-8")
            review = {"passed": True, "review_id": "current", "issues": []}
            with patch.object(approve_run.sys, "argv", ["approve_run.py", str(run_dir)]), \
                 patch.object(approve_run.sys.stdin, "isatty", return_value=True), \
                 patch.object(approve_run, "current_review", return_value=review), \
                 patch.object(approve_run, "reviewer_name", return_value="student"), \
                 patch.object(approve_run, "show_piece"), \
                 patch("builtins.input", side_effect=["0"]):
                self.assertEqual(approve_run.main(), 4)
            self.assertEqual((run_dir / "approval.json").read_text(encoding="utf-8"), previous)


if __name__ == "__main__":
    unittest.main()
