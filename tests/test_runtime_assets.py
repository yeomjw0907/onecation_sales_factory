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

from sales_factory.runtime_assets import build_company_assets, route_rejection


class RuntimeAssetsTests(unittest.TestCase):
    def test_route_rejection_routes_same_name_identity_issues_to_disambiguation(self) -> None:
        rerun_tasks = route_rejection("proposal_package", "동명이회사라서 주소와 이메일 도메인이 다릅니다.")
        self.assertEqual(rerun_tasks[:2], ["identity_disambiguation_task", "lead_verification_task"])

    def test_build_company_assets_copies_binary_outputs_into_runtime_assets(self) -> None:
        recorded_assets: list[dict[str, object]] = []

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            workspace_dir = temp_path / "workspace"
            output_dir = temp_path / "output"
            asset_root = temp_path / "assets"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)
            asset_root.mkdir(parents=True, exist_ok=True)

            (workspace_dir / "lead_verification.md").write_text(
                "TOTAL_COMPANIES: 1\n"
                "| company_name | industry | location | contact_email_or_phone | homepage_url_if_any | public_profile_links | source_links | company_size_estimate | revenue_estimate | sub_industry | decision_maker_hint | icp_fit | icp_notes | current_digital_presence | verification_status | verification_notes |\n"
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
                "| Acme Co. | Printing | LA | - | https://example.com | - | - | - | - | - | - | yes | - | basic | verified | ok |\n",
                encoding="utf-8",
            )
            (workspace_dir / "proposal.md").write_text("# Acme Co.\n## Greeting\nHello\n", encoding="utf-8")
            (workspace_dir / "outreach_emails.md").write_text("# Acme Co.\n## Primary Outbound Email\n- subject: Hi\n- body:\n    Hello\n- cta: Reply\n", encoding="utf-8")
            (workspace_dir / "marketing_plan.md").write_text("# Acme Co.\n## Recommended Offer\n- launch now\n", encoding="utf-8")
            (workspace_dir / "competitor_analysis.md").write_text("# Acme Co.\n## Market Snapshot\n- stable\n", encoding="utf-8")

            (output_dir / "Acme Co._proposal_test.docx").write_bytes(b"docx")
            (output_dir / "Acme Co._proposal_test.pdf").write_bytes(b"pdf")

            with (
                patch("sales_factory.runtime_assets.ASSET_ROOT", asset_root),
                patch("sales_factory.runtime_assets.upload_asset_file", return_value={}),
                patch("sales_factory.runtime_assets.create_asset", side_effect=lambda _asset_id, payload: recorded_assets.append(payload)),
            ):
                company_assets, validation_issues = build_company_assets(
                    "run-123",
                    workspace_dir=workspace_dir,
                    output_dir=output_dir,
                    proposal_language="en",
                )

            self.assertIn("Acme Co.", company_assets)
            self.assertFalse(validation_issues)

            docx_asset = next(asset for asset in recorded_assets if asset["asset_type"] == "proposal_docx")
            pdf_asset = next(asset for asset in recorded_assets if asset["asset_type"] == "proposal_pdf")
            self.assertTrue(str(docx_asset["path"]).startswith(str(asset_root / "run-123")))
            self.assertTrue(str(pdf_asset["path"]).startswith(str(asset_root / "run-123")))


if __name__ == "__main__":
    unittest.main()
