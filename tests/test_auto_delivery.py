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
    build_primary_email_payload,
    execute_auto_send,
    get_auto_send_settings,
    load_verified_recipients,
    render_primary_email_html,
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
    def test_get_auto_send_settings_defaults_to_shadow_on_render(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "RENDER": "true",
                "SALES_FACTORY_AUTO_SEND_MODE": "",
            },
            clear=True,
        ):
            with patch("sales_factory.runtime_supabase.load_project_env", return_value=None):
                settings = get_auto_send_settings()

        self.assertEqual(settings.mode, "shadow")

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

    def test_execute_auto_send_live_passes_branded_html_body(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            email_path = temp_path / "outreach_emails.md"
            email_path.write_text(
                "# 서울대학교\n"
                "## Primary Outbound Email\n"
                "- subject: 서울대학교 글로벌 디지털 브랜드 위상 강화 제안\n"
                "- preview_line: Preview\n"
                "- body:\n"
                "    안녕하세요, Onecation의 대표입니다.\n"
                "    \n"
                "    서울대학교의 글로벌 연구 서사를 더 선명하게 보여줄 기회가 있습니다.\n"
                "- cta: 다음 주 30분 정도 논의 가능하실까요?\n",
                encoding="utf-8",
            )
            pdf_path = temp_path / "proposal.pdf"
            pdf_path.write_bytes(b"%PDF-1.4")

            assessment = type(
                "Assessment",
                (),
                {
                    "recipient_email": "team@snu.ac.kr",
                    "company_name": "서울대학교",
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
                    settings=AutoSendSettings(mode="live", canary_email="", min_proposal_score=85, require_pdf=True, max_items_per_run=3),
                )

            self.assertEqual(result["status"], "sent")
            mocked_send.assert_called_once()
            kwargs = mocked_send.call_args.kwargs
            self.assertIn("cid:onecation-logo", kwargs["body_html"])
            self.assertIn("cid:onecation-signature", kwargs["body_html"])
            self.assertEqual(sorted(kwargs["inline_image_paths"].keys()), ["onecation-logo", "onecation-signature"])

    def test_render_primary_email_html_switches_banner_by_language(self) -> None:
        korean_html = render_primary_email_html("안녕하세요, 주식회사 98점7도 염정원입니다.\n\n서울대학교 제안 메일입니다.")
        english_html = render_primary_email_html("Hello, this is Yeom Jungwon from 98.7 Co., Ltd.\n\nThis is a proposal email.")

        self.assertIn("cid:onecation-logo", korean_html)
        self.assertIn("cid:onecation-signature", korean_html)
        self.assertIn("cid:onecation-logo", english_html)
        self.assertIn("cid:onecation-signature", english_html)

    def test_build_primary_email_payload_adds_offer_cta_signature_and_pdf_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            email_path = temp_path / "outreach_emails.md"
            email_path.write_text(
                "# Acme Co.\n"
                "## Primary Outbound Email\n"
                "- subject: Hello\n"
                "- preview_line: Preview\n"
                "- body:\n"
                "    We reviewed Acme's current web presence.\n"
                "- cta: Could we schedule a 30-minute review next week?\n",
                encoding="utf-8",
            )
            proposal_path = temp_path / "proposal.md"
            proposal_path.write_text(
                "# Acme Co.\n"
                "## Recommended Direction\n"
                "We recommend a website relaunch with ongoing maintenance support.\n",
                encoding="utf-8",
            )
            pdf_path = temp_path / "proposal.pdf"
            pdf_path.write_bytes(b"%PDF-1.4")

            with patch.dict("os.environ", {"SMTP_USER": "ops@onecation.co.kr"}, clear=False):
                subject, body, attachments = build_primary_email_payload(
                    [
                        {"asset_type": "email_sequence", "path": str(email_path), "metadata_json": {}},
                        {"asset_type": "proposal", "path": str(proposal_path), "metadata_json": {}},
                        {"asset_type": "proposal_pdf", "path": str(pdf_path), "metadata_json": {}},
                    ]
                )

            self.assertEqual(subject, "Hello")
            self.assertIn("Onecation", body)
            self.assertIn("website relaunch with ongoing maintenance support", body)
            self.assertIn("Could we schedule a 30-minute review next week?", body)
            self.assertIn("ops@onecation.co.kr", body)
            self.assertEqual(attachments, [pdf_path])

    def test_build_primary_email_payload_does_not_duplicate_existing_offer_or_closing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            email_path = temp_path / "outreach_emails.md"
            email_path.write_text(
                "# Acme Co.\n"
                "## Primary Outbound Email\n"
                "- subject: Hello\n"
                "- preview_line: Preview\n"
                "- body:\n"
                "    Hello, this is Minjun Kim from Onecation.\n"
                "    \n"
                "    Acme has built a strong reputation with local manufacturing customers.\n"
                "    \n"
                "    The offer is a website relaunch focused on portfolio visibility and quote capture.\n"
                "    \n"
                "    Thank you for reviewing this.\n"
                "- cta: Could we schedule a 20-minute call next week?\n",
                encoding="utf-8",
            )
            proposal_path = temp_path / "proposal.md"
            proposal_path.write_text(
                "# Acme Co.\n"
                "## Recommended Direction\n"
                "The offer is a website relaunch focused on portfolio visibility and quote capture.\n",
                encoding="utf-8",
            )
            pdf_path = temp_path / "proposal.pdf"
            pdf_path.write_bytes(b"%PDF-1.4")

            with patch.dict(
                "os.environ",
                {
                    "SMTP_USER": "ops@onecation.co.kr",
                    "SALES_FACTORY_SENDER_NAME": "Minjun Kim",
                },
                clear=False,
            ):
                _subject, body, _attachments = build_primary_email_payload(
                    [
                        {"asset_type": "email_sequence", "path": str(email_path), "metadata_json": {}},
                        {"asset_type": "proposal", "path": str(proposal_path), "metadata_json": {}},
                        {"asset_type": "proposal_pdf", "path": str(pdf_path), "metadata_json": {}},
                    ]
                )

            self.assertEqual(body.count("website relaunch focused on portfolio visibility and quote capture"), 1)
            self.assertEqual(body.count("Thank you for reviewing this."), 1)
            self.assertNotIn("The core offer we are proposing is:", body)
            self.assertIn("Minjun Kim | Onecation", body)

    def test_build_primary_email_payload_adds_affiliation_intro_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            email_path = temp_path / "outreach_emails.md"
            email_path.write_text(
                "# Acme Co.\n"
                "## Primary Outbound Email\n"
                "- subject: Hello\n"
                "- preview_line: Preview\n"
                "- body:\n"
                "    We reviewed Acme's current website and quote flow.\n"
                "- cta: Could we schedule a 20-minute call next week?\n",
                encoding="utf-8",
            )
            proposal_path = temp_path / "proposal.md"
            proposal_path.write_text(
                "# Acme Co.\n"
                "## Recommended Direction\n"
                "We recommend a website relaunch that better shows recent work.\n",
                encoding="utf-8",
            )
            pdf_path = temp_path / "proposal.pdf"
            pdf_path.write_bytes(b"%PDF-1.4")

            with patch.dict(
                "os.environ",
                {
                    "SMTP_USER": "ops@onecation.co.kr",
                    "SALES_FACTORY_SENDER_NAME": "Minjun Kim",
                },
                clear=False,
            ):
                _subject, body, _attachments = build_primary_email_payload(
                    [
                        {"asset_type": "email_sequence", "path": str(email_path), "metadata_json": {}},
                        {"asset_type": "proposal", "path": str(proposal_path), "metadata_json": {}},
                        {"asset_type": "proposal_pdf", "path": str(pdf_path), "metadata_json": {}},
                    ]
                )

            self.assertIn("Hello, this is Minjun Kim from Onecation.", body)
            self.assertIn("Minjun Kim | Onecation", body)

    def test_build_primary_email_payload_formats_title_only_sender_naturally(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            email_path = temp_path / "outreach_emails.md"
            email_path.write_text(
                "# Acme Co.\n"
                "## Primary Outbound Email\n"
                "- subject: Hello\n"
                "- preview_line: Preview\n"
                "- body:\n"
                "    We reviewed Acme's current website and quote flow.\n"
                "- cta: Could we schedule a 20-minute call next week?\n",
                encoding="utf-8",
            )
            proposal_path = temp_path / "proposal.md"
            proposal_path.write_text(
                "# Acme Co.\n"
                "## Recommended Direction\n"
                "We recommend a website relaunch that better shows recent work.\n",
                encoding="utf-8",
            )
            pdf_path = temp_path / "proposal.pdf"
            pdf_path.write_bytes(b"%PDF-1.4")

            with patch.dict(
                "os.environ",
                {
                    "SMTP_USER": "ops@onecation.co.kr",
                    "SALES_FACTORY_SENDER_NAME": "대표",
                },
                clear=False,
            ):
                _subject, body, _attachments = build_primary_email_payload(
                    [
                        {"asset_type": "email_sequence", "path": str(email_path), "metadata_json": {}},
                        {"asset_type": "proposal", "path": str(proposal_path), "metadata_json": {}},
                        {"asset_type": "proposal_pdf", "path": str(pdf_path), "metadata_json": {}},
                    ]
                )

            self.assertIn("Hello, this is the 대표 at Onecation.", body)
            self.assertIn("Onecation 대표", body)

    def test_build_primary_email_payload_falls_back_to_docx_attachment(self) -> None:
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
            proposal_path = temp_path / "proposal.md"
            proposal_path.write_text(
                "# Acme Co.\n"
                "## Recommended Direction\n"
                "We recommend a website maintenance recovery package.\n",
                encoding="utf-8",
            )
            docx_path = temp_path / "proposal.docx"
            docx_path.write_bytes(b"docx")

            subject, body, attachments = build_primary_email_payload(
                [
                    {"asset_type": "email_sequence", "path": str(email_path), "metadata_json": {}},
                    {"asset_type": "proposal", "path": str(proposal_path), "metadata_json": {}},
                    {"asset_type": "proposal_docx", "path": str(docx_path), "metadata_json": {}},
                ]
            )

            self.assertEqual(subject, "Hello")
            self.assertIn("website maintenance recovery package", body)
            self.assertEqual(attachments, [docx_path])

    def test_build_primary_email_payload_enforces_fixed_korean_intro_and_subject(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            email_path = temp_path / "outreach_emails.md"
            email_path.write_text(
                "# 서울대학교\n"
                "## Primary Outbound Email\n"
                "- subject: 서울대학교 글로벌 디지털 브랜드 위상 강화 제안\n"
                "- preview_line: Preview\n"
                "- body:\n"
                "    안녕하십니까, Onecation의 대표입니다.\n"
                "    \n"
                "    서울대학교의 연구 성과와 국제 협력 내러티브를 더 선명하게 보여줄 기회가 있습니다.\n"
                "- cta: 다음 주 30분 정도 논의 가능하실까요?\n",
                encoding="utf-8",
            )
            proposal_path = temp_path / "proposal.md"
            proposal_path.write_text(
                "# 서울대학교\n"
                "## Recommended Direction\n"
                "글로벌 브랜드 콘텐츠 증폭 프로그램을 제안합니다.\n",
                encoding="utf-8",
            )
            pdf_path = temp_path / "proposal.pdf"
            pdf_path.write_bytes(b"%PDF-1.4")

            with patch.dict(
                "os.environ",
                {
                    "SMTP_USER": "ops@onecation.co.kr",
                    "SALES_FACTORY_SENDER_NAME": "대표",
                },
                clear=False,
            ):
                subject, body, _attachments = build_primary_email_payload(
                    [
                        {"asset_type": "email_sequence", "path": str(email_path), "metadata_json": {}},
                        {"asset_type": "proposal", "path": str(proposal_path), "metadata_json": {}},
                        {"asset_type": "proposal_pdf", "path": str(pdf_path), "metadata_json": {}},
                    ]
                )

            self.assertEqual(subject, "[주식회사 98점7도] 서울대학교 글로벌 디지털 브랜드 위상 강화 제안의 건")
            self.assertTrue(body.startswith("안녕하세요, 주식회사 98점7도 염정원입니다."))
            self.assertEqual(body.count("안녕하세요, 주식회사 98점7도 염정원입니다."), 1)
            self.assertIn("염정원 | 주식회사 98점7도", body)


if __name__ == "__main__":
    unittest.main()
