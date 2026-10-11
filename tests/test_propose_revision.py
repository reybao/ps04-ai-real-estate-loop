"""Offline tests for isolated, evidence-constrained API revision proposals."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("propose_revision", ROOT / "review/propose_revision.py")
assert SPEC and SPEC.loader
propose_revision = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(propose_revision)


class ProposalTests(unittest.TestCase):
    def fixture(self, run_dir: Path, mode: str = "api") -> tuple[str, str]:
        (run_dir / "articles").mkdir()
        (run_dir / "video_scripts").mkdir()
        article = "# Article\n\nAs of 2026-10-10, the claim is attributed. [01-c1]\n"
        script = "# Video\n\nAI-generated avatar and cloned voice are disclosed. [01-c1]\n"
        (run_dir / "articles/01.md").write_text(article, encoding="utf-8")
        (run_dir / "video_scripts/01.md").write_text(script, encoding="utf-8")
        (run_dir / "run.json").write_text(json.dumps({"as_of_date": "2026-10-10"}), encoding="utf-8")
        (run_dir / "review.json").write_text(json.dumps({"review_id": "current", "passed": True}), encoding="utf-8")
        (run_dir / "approval.json").write_text(json.dumps({
            "review_id": "current", "decision": "revise",
            "piece_reviews": [{
                "piece_id": "01", "decision": "revise", "revision_mode": mode,
                "reason": "Clarify that this is a company claim.",
            }],
        }), encoding="utf-8")
        (run_dir / "briefs.jsonl").write_text(json.dumps({
            "piece_id": "01", "title": "Article", "claims": [{"claim_id": "01-c1"}],
        }) + "\n", encoding="utf-8")
        (run_dir / "eligible.jsonl").write_text("", encoding="utf-8")
        return article, script

    def test_api_proposal_is_separate_and_cached(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            article, script = self.fixture(run_dir)
            response = {
                "piece_id": "01", "can_revise": True,
                "rationale": "Attribution can be made clearer without adding a new claim.",
                "article_markdown": article.replace("the claim is attributed", "the company makes the claim"),
                "video_script_markdown": script,
                "changes": ["Clarified attribution in the article."],
                "limitations": ["The claim is not independently verified."],
            }
            metadata = {"model": "test-model", "status": "completed", "cost_usd": None}
            with patch.object(propose_revision.sys, "argv", ["propose_revision.py", str(run_dir)]), \
                 patch.object(propose_revision, "current_review", return_value={"review_id": "current", "passed": True}), \
                 patch.object(propose_revision, "brief_evidence_details", return_value=[]), \
                 patch.object(propose_revision, "request_json", return_value=(response, metadata)) as api, \
                 patch.object(propose_revision, "open_proposals_in_vscode"):
                self.assertEqual(propose_revision.main(), 0)
                self.assertEqual(propose_revision.main(), 0)
            api.assert_called_once()
            self.assertEqual((run_dir / "articles/01.md").read_text(encoding="utf-8"), article)
            self.assertEqual((run_dir / "video_scripts/01.md").read_text(encoding="utf-8"), script)
            proposal_dir = next((run_dir / "revisions/01").iterdir())
            self.assertIn("company makes the claim", (proposal_dir / "article-proposed.md").read_text(encoding="utf-8"))
            self.assertTrue((proposal_dir / "article.diff").exists())
            self.assertTrue((proposal_dir / "feedback.md").exists())

    def test_manual_revision_never_calls_api(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            self.fixture(run_dir, mode="manual")
            with patch.object(propose_revision.sys, "argv", ["propose_revision.py", str(run_dir)]), \
                 patch.object(propose_revision, "request_json") as api:
                self.assertEqual(propose_revision.main(), 0)
            api.assert_not_called()
            self.assertFalse((run_dir / "revisions").exists())

    def test_unsupported_change_creates_feedback_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            article, script = self.fixture(run_dir)
            response = {
                "piece_id": "01", "can_revise": False,
                "rationale": "The requested new claim lacks evidence.",
                "article_markdown": article, "video_script_markdown": script,
                "changes": [], "limitations": ["Find a primary source first."],
            }
            with patch.object(propose_revision.sys, "argv", ["propose_revision.py", str(run_dir)]), \
                 patch.object(propose_revision, "current_review", return_value={"review_id": "current", "passed": True}), \
                 patch.object(propose_revision, "brief_evidence_details", return_value=[]), \
                 patch.object(propose_revision, "request_json", return_value=(response, {"status": "completed"})):
                self.assertEqual(propose_revision.main(), 0)
            proposal_dir = next((run_dir / "revisions/01").iterdir())
            self.assertTrue((proposal_dir / "feedback.md").exists())
            self.assertFalse((proposal_dir / "article-proposed.md").exists())

    def test_invalid_api_draft_is_not_cached_as_a_usable_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            _, script = self.fixture(run_dir)
            response = {
                "piece_id": "01", "can_revise": True,
                "rationale": "Changed", "article_markdown": "# Article\nAs of 2026-10-10, no claim marker.",
                "video_script_markdown": script,
                "changes": ["Changed"], "limitations": [],
            }
            with patch.object(propose_revision.sys, "argv", ["propose_revision.py", str(run_dir)]), \
                 patch.object(propose_revision, "current_review", return_value={"review_id": "current", "passed": True}), \
                 patch.object(propose_revision, "brief_evidence_details", return_value=[]), \
                 patch.object(propose_revision, "request_json", return_value=(response, {"status": "completed"})):
                self.assertEqual(propose_revision.main(), 1)
            proposal_dir = next((run_dir / "revisions/01").iterdir())
            self.assertTrue((proposal_dir / "response-invalid.json").exists())
            self.assertFalse((proposal_dir / "response.json").exists())

    def test_missing_claim_marker_rejects_proposal(self) -> None:
        original = {"brief": {"claims": [{"claim_id": "01-c1"}]}}
        response = {
            "piece_id": "01", "can_revise": True,
            "rationale": "Changed", "article_markdown": "# Article\nAs of 2026-10-10, no marker.",
            "video_script_markdown": "# Video\nAI-generated cloned voice [01-c1]",
            "changes": ["Changed"], "limitations": [],
        }
        with self.assertRaisesRegex(ValueError, "omits required claim markers"):
            propose_revision.validate_proposal(response, "01", original, "2026-10-10")

    def test_wrong_as_of_date_rejects_proposal(self) -> None:
        original = {"brief": {"claims": [{"claim_id": "01-c1"}]}}
        response = {
            "piece_id": "01", "can_revise": True,
            "rationale": "Changed", "article_markdown": "# Article\nAs of 2026-10-09, fact [01-c1].",
            "video_script_markdown": "# Video\nAI-generated avatar and cloned voice [01-c1].",
            "changes": ["Changed"], "limitations": [],
        }
        with self.assertRaisesRegex(ValueError, "actual as-of date"):
            propose_revision.validate_proposal(response, "01", original, "2026-10-10")


if __name__ == "__main__":
    unittest.main()
