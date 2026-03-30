from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sales_factory.managed_run import (
    enforce_identity_disambiguation_guard,
    sanitize_identity_disambiguation_output,
    sanitize_lead_verification_output,
)


class ManagedRunTests(unittest.TestCase):
    def test_sanitize_identity_disambiguation_output_keeps_only_selected_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_dir = Path(temp_dir)
            disambiguation_path = workspace_dir / "identity_disambiguation.md"
            disambiguation_path.write_text(
                "TOTAL_COMPANIES: 2\n"
                "| company_name | industry | location | contact_email_or_phone | homepage_url_if_any | public_profile_links | source_links | company_size_estimate | revenue_estimate | sub_industry | decision_maker_hint | icp_fit | icp_notes | current_digital_presence | official_address | official_phone | official_email_domain | identity_confidence | identity_match_basis | conflict_notes | disambiguation_status |\n"
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
                "| Alpha | Printing | Orange, CA, USA | info@alpha.com | https://alpha.com | - | - | - | - | - | - | yes | - | basic | 100 Main St, Orange, CA | +1-555-0001 | alpha.com | high | address + email domain + homepage match | no conflict | selected |\n"
                "| Alpha | Printing | Holbrook, MA, USA | info@alpha-ma.com | https://alpha-ma.com | - | - | - | - | - | - | yes | - | basic | 200 Main St, Holbrook, MA | +1-555-0002 | alpha-ma.com | medium | conflicting regional footprint | unresolved duplicate | ambiguous |\n",
                encoding="utf-8",
            )

            raw_rows, retained_rows = sanitize_identity_disambiguation_output(workspace_dir)

            self.assertEqual(raw_rows, 2)
            self.assertEqual(retained_rows, 1)
            rewritten = disambiguation_path.read_text(encoding="utf-8")
            self.assertIn("TOTAL_COMPANIES: 1", rewritten)
            self.assertIn("| Alpha | Printing | Orange, CA, USA |", rewritten)
            self.assertNotIn("Holbrook, MA, USA", rewritten)

    def test_sanitize_identity_disambiguation_output_handles_escaped_pipes_inside_cells(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_dir = Path(temp_dir)
            disambiguation_path = workspace_dir / "identity_disambiguation.md"
            disambiguation_path.write_text(
                "TOTAL_COMPANIES: 1\n"
                "| company_name | industry | location | contact_email_or_phone | homepage_url_if_any | public_profile_links | source_links | company_size_estimate | revenue_estimate | sub_industry | decision_maker_hint | icp_fit | icp_notes | current_digital_presence | official_address | official_phone | official_email_domain | identity_confidence | identity_match_basis | conflict_notes | disambiguation_status |\n"
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
                "| QP Graphics, Inc. | Printing | Commack, NY, US | info@qpgraphics.com | https://www.qpgraphics.com | https://linkedin.example/qp \\| https://bbb.example/qp | https://www.qpgraphics.com \\| https://manta.example/qp | 2-4 employees | $150,000 - $300,000 | Graphic Design | Owner | yes | - | dated | 795 Commack Rd, Commack, NY 11725 | (631) 499-5226 | qpgraphics.com | high | homepage domain, email domain, and phone all align | no conflict | selected |\n",
                encoding="utf-8",
            )

            raw_rows, retained_rows = sanitize_identity_disambiguation_output(workspace_dir)

            self.assertEqual(raw_rows, 1)
            self.assertEqual(retained_rows, 1)

    def test_enforce_identity_disambiguation_guard_accepts_single_high_confidence_row(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_dir = Path(temp_dir)
            disambiguation_path = workspace_dir / "identity_disambiguation.md"
            disambiguation_path.write_text(
                "TOTAL_COMPANIES: 1\n"
                "| company_name | industry | location | contact_email_or_phone | homepage_url_if_any | public_profile_links | source_links | company_size_estimate | revenue_estimate | sub_industry | decision_maker_hint | icp_fit | icp_notes | current_digital_presence | official_address | official_phone | official_email_domain | identity_confidence | identity_match_basis | conflict_notes | disambiguation_status |\n"
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
                "| QP Graphics, Inc. | Printing | Orange, CA, USA | info@qpgraphics.com | https://www.qpgraphics.com | - | - | - | - | - | - | yes | - | basic | 123 Sample Ave, Orange, CA 92868 | +1-714-555-0100 | qpgraphics.com | high | exact legal name plus address, phone, and homepage corroborate the same company | no conflict | selected |\n",
                encoding="utf-8",
            )

            enforce_identity_disambiguation_guard(workspace_dir, lead_mode="company_name")

    def test_enforce_identity_disambiguation_guard_rejects_low_confidence_or_weak_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_dir = Path(temp_dir)
            disambiguation_path = workspace_dir / "identity_disambiguation.md"
            disambiguation_path.write_text(
                "TOTAL_COMPANIES: 1\n"
                "| company_name | industry | location | contact_email_or_phone | homepage_url_if_any | public_profile_links | source_links | company_size_estimate | revenue_estimate | sub_industry | decision_maker_hint | icp_fit | icp_notes | current_digital_presence | official_address | official_phone | official_email_domain | identity_confidence | identity_match_basis | conflict_notes | disambiguation_status |\n"
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
                "| QP Graphics, Inc. | Printing | Orange, CA, USA | - | https://www.qpgraphics.com | - | - | - | - | - | - | yes | - | basic | - | - | - | medium | homepage only | no conflict | selected |\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "high identity confidence"):
                enforce_identity_disambiguation_guard(workspace_dir, lead_mode="company_name")

    def test_enforce_identity_disambiguation_guard_rejects_missing_digital_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_dir = Path(temp_dir)
            disambiguation_path = workspace_dir / "identity_disambiguation.md"
            disambiguation_path.write_text(
                "TOTAL_COMPANIES: 1\n"
                "| company_name | industry | location | contact_email_or_phone | homepage_url_if_any | public_profile_links | source_links | company_size_estimate | revenue_estimate | sub_industry | decision_maker_hint | icp_fit | icp_notes | current_digital_presence | official_address | official_phone | official_email_domain | identity_confidence | identity_match_basis | conflict_notes | disambiguation_status |\n"
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
                "| QP Graphics, Inc. | Graphic Design | Los Angeles, CA, US | (213) 683-1678 | - | - | - | - | - | - | - | yes | - | directory-only | 740 S Broadway, Los Angeles, CA 90014 | (213) 683-1678 | - | high | address and phone match public directories | no conflict | selected |\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "official homepage or email-domain anchor"):
                enforce_identity_disambiguation_guard(workspace_dir, lead_mode="company_name")

    def test_enforce_identity_disambiguation_guard_rejects_multiple_selected_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_dir = Path(temp_dir)
            disambiguation_path = workspace_dir / "identity_disambiguation.md"
            disambiguation_path.write_text(
                "TOTAL_COMPANIES: 2\n"
                "| company_name | industry | location | contact_email_or_phone | homepage_url_if_any | public_profile_links | source_links | company_size_estimate | revenue_estimate | sub_industry | decision_maker_hint | icp_fit | icp_notes | current_digital_presence | official_address | official_phone | official_email_domain | identity_confidence | identity_match_basis | conflict_notes | disambiguation_status |\n"
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
                "| QP Graphics, Inc. | Printing | Orange, CA, USA | info@qpgraphics.com | https://www.qpgraphics.com | - | - | - | - | - | - | yes | - | basic | 123 Sample Ave, Orange, CA 92868 | +1-714-555-0100 | qpgraphics.com | high | coherent CA footprint | no conflict | selected |\n"
                "| QP Graphics, Inc. | Printing | Rochester, NY, USA | hello@qp-ny.com | https://www.qp-ny.com | - | - | - | - | - | - | yes | - | basic | 55 Sample Ave, Rochester, NY 14604 | +1-585-555-0100 | qp-ny.com | high | coherent NY footprint | no conflict | selected |\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "exactly one disambiguated company"):
                enforce_identity_disambiguation_guard(workspace_dir, lead_mode="company_name")

    def test_sanitize_lead_verification_output_removes_rejected_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_dir = Path(temp_dir)
            verification_path = workspace_dir / "lead_verification.md"
            verification_path.write_text(
                "TOTAL_COMPANIES: 2\n"
                "| company_name | homepage_url_if_any | verification_status | verification_notes |\n"
                "|---|---|---|---|\n"
                "| Alpha | https://alpha.example | verified | ok |\n"
                "| Beta | https://beta.example | rejected | mismatch |\n",
                encoding="utf-8",
            )

            raw_rows, retained_rows = sanitize_lead_verification_output(workspace_dir)

            self.assertEqual(raw_rows, 2)
            self.assertEqual(retained_rows, 1)
            rewritten = verification_path.read_text(encoding="utf-8")
            self.assertIn("TOTAL_COMPANIES: 1", rewritten)
            self.assertIn("| Alpha | https://alpha.example | verified | ok |", rewritten)
            self.assertNotIn("| Beta | https://beta.example | rejected | mismatch |", rewritten)


if __name__ == "__main__":
    unittest.main()
