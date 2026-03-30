from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sales_factory.auto_delivery import (
    AutoSendSettings,
    assess_company_sendability,
    execute_auto_send,
    load_verified_recipients,
)


def make_strong_proposal(company_name: str) -> str:
    return f"""# {company_name}
## Greeting
Hello

## Executive Summary
Summary
- risk: clear
- opportunity: clear
- recommended start: relaunch

## What We Found
- proof: outdated flow
- market: competitive
- competitor: visible

## Why This Matters
This matters because the current web presence reduces trust.

## Market And Competitor Snapshot
Market summary.
| competitor_name | website_quality | key_offer | trust_signals | acquisition_motion | strengths | weaknesses |
|---|---|---|---|---|---|---|
| Rival | high | design | reviews | search | proof | price |

## Your Hidden Strengths
- proof: reputation
- opportunity: portfolio

## Recommended Direction
Direction paragraph.

## 30-60-90 Day Execution Plan
| phase | what_we_do | expected_business_effect |
|---|---|---|
| 30 | launch | leads |

## Recommended Packages
| package_name | best_for | what_is_included | price_range | notes |
|---|---|---|---|---|
| Core | growth | website | $5k-$8k | recommended |

## Pricing Guidance
Pricing guidance.

## Why Onecation
Why us.

## Suggested Next Step
1. Reply to schedule.

## Closing
Thank you.
"""


class AutoDeliveryTests(unittest.TestCase):
    def test_assess_company_sendability_accepts_matching_corporate_email(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            workspace_dir = temp_path / "workspace"
            workspace_dir.mkdir()
            (workspace_dir / "lead_verification.md").write_text(
                "TOTAL_COMPANIES: 1\n"
                "| company_name | industry | location | contact_email_or_phone | homepage_url_if_any | public_profile_links | source_links | company_size_estimate | revenue_estimate | sub_industry | decision_maker_hint | icp_fit | icp_notes | current_digital_presence | verification_status | verification_notes |\n"
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
                "| Acme Co. | Printing | Orange, CA, USA | sales@acme.com, +1-555-0100 | https://acme.com | - | - | - | - | - | - | yes | - | basic | verified | ok |\n",
                encoding="utf-8",
            )
            proposal_path = workspace_dir / "proposal.md"
            proposal_path.write_text(make_strong_proposal("Acme Co."), encoding="utf-8")
            email_path = workspace_dir / "outreach_emails.md"
            email_path.write_text(
                "# Acme Co.\n"
                "## Primary Outbound Email\n"
                "- subject: Hello\n"
                "- preview_line: Preview\n"
                "- body:\n"
                "    Hello there.\n"
                "- cta: Reply\n",
                encoding="utf-8",
            )
            pdf_path = workspace_dir / "proposal.pdf"
            pdf_path.write_bytes(b"%PDF-1.4")
            docx_path = workspace_dir / "proposal.docx"
            docx_path.write_bytes(b"docx")

            recipients = load_verified_recipients(workspace_dir)
            assessment = assess_company_sendability(
                company_name="Acme Co.",
                asset_rows=[
                    {"asset_type": "proposal", "path": str(proposal_path), "metadata_json": {}},
                    {"asset_type": "email_sequence", "path": str(email_path), "metadata_json": {}},
                    {"asset_type": "proposal_pdf", "path": str(pdf_path), "metadata_json": {}},
                    {"asset_type": "proposal_docx", "path": str(docx_path), "metadata_json": {}},
                ],
                validation_issues=[],
                verified_recipients=recipients,
                settings=AutoSendSettings(mode="shadow", canary_email="", min_proposal_score=85, require_pdf=True, max_items_per_run=3),
                test_mode=False,
            )

            self.assertTrue(assessment.eligible)
            self.assertEqual(assessment.recipient_email, "sales@acme.com")
            self.assertEqual(assessment.expected_domain, "acme.com")

    def test_assess_company_sendability_blocks_public_or_mismatched_email(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            workspace_dir = temp_path / "workspace"
            workspace_dir.mkdir()
            (workspace_dir / "lead_verification.md").write_text(
                "TOTAL_COMPANIES: 1\n"
                "| company_name | industry | location | contact_email_or_phone | homepage_url_if_any | public_profile_links | source_links | company_size_estimate | revenue_estimate | sub_industry | decision_maker_hint | icp_fit | icp_notes | current_digital_presence | verification_status | verification_notes |\n"
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
                "| Acme Co. | Printing | Orange, CA, USA | hello@gmail.com | https://acme.com | - | - | - | - | - | - | yes | - | basic | verified | ok |\n",
                encoding="utf-8",
            )
            proposal_path = workspace_dir / "proposal.md"
            proposal_path.write_text(make_strong_proposal("Acme Co."), encoding="utf-8")
            email_path = workspace_dir / "outreach_emails.md"
            email_path.write_text(
                "# Acme Co.\n"
                "## Primary Outbound Email\n"
                "- subject: Hello\n"
                "- preview_line: Preview\n"
                "- body:\n"
                "    Hello there.\n"
                "- cta: Reply\n",
                encoding="utf-8",
            )
            pdf_path = workspace_dir / "proposal.pdf"
            pdf_path.write_bytes(b"%PDF-1.4")
            docx_path = workspace_dir / "proposal.docx"
            docx_path.write_bytes(b"docx")

            recipients = load_verified_recipients(workspace_dir)
            assessment = assess_company_sendability(
                company_name="Acme Co.",
                asset_rows=[
                    {"asset_type": "proposal", "path": str(proposal_path), "metadata_json": {}},
                    {"asset_type": "email_sequence", "path": str(email_path), "metadata_json": {}},
                    {"asset_type": "proposal_pdf", "path": str(pdf_path), "metadata_json": {}},
                    {"asset_type": "proposal_docx", "path": str(docx_path), "metadata_json": {}},
                ],
                validation_issues=[],
                verified_recipients=recipients,
                settings=AutoSendSettings(mode="live", canary_email="", min_proposal_score=85, require_pdf=True, max_items_per_run=3),
                test_mode=False,
            )

            self.assertFalse(assessment.eligible)
            self.assertTrue(any("public mailbox" in reason for reason in assessment.blocked_reasons))
            self.assertTrue(any("does not match verified domain" in reason for reason in assessment.blocked_reasons))

    def test_execute_auto_send_canary_uses_canary_recipient(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            email_path = temp_path / "outreach_emails.md"
            email_path.write_text(
                "# Acme Co.\n"
                "## Primary Outbound Email\n"
                "- subject: Hello\n"
                "- preview_line: Preview\n"
                "- body:\n"
                "    Hello there.\n"
                "- cta: Reply\n",
                encoding="utf-8",
            )
            pdf_path = temp_path / "proposal.pdf"
            pdf_path.write_bytes(b"%PDF-1.4")

            assessment = type(
                "Assessment",
                (),
                {
                    "recipient_email": "sales@acme.com",
                    "company_name": "Acme Co.",
                    "proposal_score": 96,
                },
            )()

            with patch("sales_factory.auto_delivery.send_email_message") as mocked_send:
                result = execute_auto_send(
                    asset_rows=[
                        {"asset_type": "email_sequence", "path": str(email_path), "metadata_json": {}},
                        {"asset_type": "proposal_pdf", "path": str(pdf_path), "metadata_json": {}},
                    ],
                    assessment=assessment,  # type: ignore[arg-type]
                    settings=AutoSendSettings(mode="canary", canary_email="ops@example.com", min_proposal_score=85, require_pdf=True, max_items_per_run=3),
                )

            self.assertEqual(result["status"], "sent")
            self.assertEqual(result["recipient"], "ops@example.com")
            mocked_send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
