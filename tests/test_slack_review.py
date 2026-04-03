from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import sales_factory.slack_review as slack_review
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
        self.assertIn("approval_confirm_send", action_ids)
        self.assertIn("approval_request_changes", action_ids)
        self.assertIn("approval_send_test", action_ids)

    def test_try_add_message_reaction_uses_channel_and_message_ts(self) -> None:
        client = Mock()

        slack_review._try_add_message_reaction(
            client,
            channel_id="C123",
            message_ts="1712345678.000100",
            name="white_check_mark",
        )

        client.reactions_add.assert_called_once_with(
            channel="C123",
            timestamp="1712345678.000100",
            name="white_check_mark",
        )

    @patch("sales_factory.slack_review.reject_approval_item", return_value=(True, "재작업을 다시 시작했습니다."))
    def test_handle_request_changes_async_posts_feedback_and_reaction(self, mock_reject_approval_item) -> None:
        client = Mock()

        slack_review._handle_request_changes_async(
            client,
            item={"id": "item-1", "title": "Acme outbound"},
            reason="이메일을 더 공손하게 작성해줘",
            reviewer_identity="tester",
            channel_id="C123",
            user_id="U123",
            message_ts="1712345678.000100",
        )

        mock_reject_approval_item.assert_called_once()
        client.reactions_add.assert_called_once_with(
            channel="C123",
            timestamp="1712345678.000100",
            name="memo",
        )
        client.chat_postEphemeral.assert_called_once()

    @patch("sales_factory.slack_review.build_primary_email_payload")
    @patch("sales_factory.slack_review.load_approval_assets")
    @patch("sales_factory.slack_review.asset_preview_text")
    def test_preview_modal_contains_email_and_attachment_actions(
        self,
        mock_asset_preview_text,
        mock_load_approval_assets,
        mock_build_primary_email_payload,
    ) -> None:
        mock_load_approval_assets.return_value = [
            {"asset_type": "proposal", "path": "proposal.md", "metadata_json": {}},
            {"asset_type": "email_sequence", "path": "email.md", "metadata_json": {}},
        ]
        mock_asset_preview_text.return_value = "Proposal preview"
        mock_build_primary_email_payload.return_value = (
            "Outbound subject",
            "Outbound body",
            [Path("proposal.pdf"), Path("proposal.docx")],
        )

        modal = slack_review._build_preview_modal(
            {
                "id": "item-1",
                "company_name": "Acme",
                "title": "Acme outbound package",
                "metadata_json": {"auto_delivery": {"blocked_reasons": []}},
            }
        )

        self.assertEqual(modal["type"], "modal")
        block_text = "\n".join(
            block.get("text", {}).get("text", "")
            for block in modal["blocks"]
            if isinstance(block.get("text"), dict)
        )
        self.assertIn("Outbound subject", block_text)
        self.assertIn("Outbound body", block_text)
        self.assertIn("proposal.pdf", block_text)

        action_ids = []
        for block in modal["blocks"]:
            if block.get("type") == "actions":
                action_ids.extend(element.get("action_id") for element in block.get("elements", []) if element.get("action_id"))
        self.assertIn("approval_approve", action_ids)
        self.assertIn("approval_confirm_send", action_ids)
        self.assertIn("approval_request_changes", action_ids)
        self.assertIn("approval_send_test", action_ids)
        self.assertIn("approval_send_pdf", action_ids)
        self.assertIn("approval_send_docx", action_ids)

    @patch("sales_factory.slack_review.build_live_send_preview")
    def test_confirm_send_modal_contains_live_send_summary(self, mock_build_live_send_preview) -> None:
        mock_build_live_send_preview.return_value = {
            "company_name": "Acme",
            "recipient": "hello@example.com",
            "subject": "Acme proposal",
            "attachment_names": ["proposal.pdf", "proposal.docx"],
            "blocked_reasons": ["verified official homepage or email domain anchor is missing"],
            "test_mode": True,
        }

        modal = slack_review._build_confirm_send_modal({"id": "item-1"})
        self.assertEqual(modal["callback_id"], "approval_confirm_send_modal")
        self.assertEqual(modal["submit"]["text"], "실제 발송")
        block_text = "\n".join(
            block.get("text", {}).get("text", "")
            for block in modal["blocks"]
            if isinstance(block.get("text"), dict)
        )
        self.assertIn("hello@example.com", block_text)
        self.assertIn("proposal.pdf", block_text)
        self.assertIn("Acme proposal", block_text)

    @patch("sales_factory.slack_review.approve_and_send_approval_item", return_value=(True, "sent"))
    def test_handle_approve_and_send_async_posts_feedback_and_reaction(self, mock_approve_and_send) -> None:
        client = Mock()

        slack_review._handle_approve_and_send_async(
            client,
            item={"id": "item-1", "title": "Acme outbound"},
            reviewer_identity="tester",
            channel_id="C123",
            user_id="U123",
            message_ts="1712345678.000100",
        )

        mock_approve_and_send.assert_called_once()
        client.reactions_add.assert_called_once_with(
            channel="C123",
            timestamp="1712345678.000100",
            name="outbox_tray",
        )
        client.chat_postEphemeral.assert_called_once()


if __name__ == "__main__":
    unittest.main()
