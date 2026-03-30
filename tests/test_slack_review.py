from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sales_factory.slack_review import build_review_ready_slack_blocks, prime_slack_review_handlers


class SlackReviewTests(unittest.TestCase):
    def test_prime_slack_review_handlers_swallows_startup_errors(self) -> None:
        with patch("sales_factory.slack_review.ensure_slack_socket_mode_started", side_effect=RuntimeError("boom")):
            self.assertFalse(prime_slack_review_handlers())

    def test_build_review_ready_slack_blocks_contains_review_actions(self) -> None:
        approval_item = {
            "id": "item-1",
            "run_id": "run-1",
            "company_name": "명인프린팅",
            "title": "명인프린팅 outbound package",
            "priority": 1,
            "created_at": "2026-03-30T12:00:00",
            "asset_bundle_json": "[]",
            "metadata_json": {
                "auto_delivery": {
                    "blocked_reasons": ["verified official homepage or email domain anchor is missing"],
                },
                "validation_issues": [],
            },
        }

        with patch("sales_factory.slack_review.list_approval_items_for_run", return_value=[approval_item]), patch(
            "sales_factory.slack_review.load_approval_assets",
            return_value=[{"asset_type": "proposal"}, {"asset_type": "email_sequence"}],
        ), patch("sales_factory.slack_review.asset_preview_text", return_value="메일 미리보기"), patch(
            "sales_factory.slack_review.slack_public_app_url",
            return_value="https://onecation-sales-factory.onrender.com",
        ):
            blocks = build_review_ready_slack_blocks(
                run_id="run-1",
                target_country="KR",
                inputs={"lead_query": "서울 인쇄 업체", "auto_mode": True},
                approval_count=1,
                total_tokens=1200,
                estimated_cost=0.1234,
            )

        action_ids = []
        for block in blocks:
            if block.get("type") == "actions":
                action_ids.extend(element.get("action_id") for element in block.get("elements", []) if element.get("action_id"))

        self.assertIn("approval_preview", action_ids)
        self.assertIn("approval_approve", action_ids)
        self.assertIn("approval_request_changes", action_ids)
        self.assertIn("approval_send_test", action_ids)


if __name__ == "__main__":
    unittest.main()
