from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sales_factory.delivery_manager import (
    VerifiedCompanyFacts,
    collect_delivery_guard_issues,
    load_verified_company_facts,
)


class DeliveryManagerTests(unittest.TestCase):
    def test_load_verified_company_facts_reads_lead_verification_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_dir = Path(temp_dir)
            (workspace_dir / "lead_verification.md").write_text(
                "TOTAL_COMPANIES: 1\n"
                "| company_name | industry | location | contact_email_or_phone | homepage_url_if_any | public_profile_links | source_links | company_size_estimate | revenue_estimate | sub_industry | decision_maker_hint | icp_fit | icp_notes | current_digital_presence | verification_status | verification_notes |\n"
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
                "| QP Graphics, Inc. | Printing | Orange, CA, USA | - | https://qpgraphics.com/ | - | - | - | - | - | - | yes | - | basic | verified | The website appears to be experiencing technical issues that prevent scraping. |\n",
                encoding="utf-8",
            )

            facts = load_verified_company_facts(workspace_dir)

            self.assertIn("qpgraphicsinc", facts)
            self.assertEqual(facts["qpgraphicsinc"].homepage_domain, "qpgraphics.com")

    def test_collect_delivery_guard_issues_flags_us_location_drift(self) -> None:
        facts = VerifiedCompanyFacts(
            company_name="QP Graphics, Inc.",
            location="Orange, CA, USA",
            homepage_url="https://qpgraphics.com/",
            homepage_domain="qpgraphics.com",
            verification_status="verified",
            verification_notes="The website appears to be experiencing technical issues that prevent scraping.",
        )
        text = "Your physical business in Holbrook, MA, is well-established and serves the Greater Boston area."

        issues = collect_delivery_guard_issues(text, asset_type="proposal", facts=facts)

        self.assertTrue(any("geographic mismatch" in issue for issue in issues))

    def test_collect_delivery_guard_issues_flags_wrong_metro_alias(self) -> None:
        facts = VerifiedCompanyFacts(
            company_name="QP Graphics, Inc.",
            location="Long Island City, NY, USA",
            homepage_url="https://qpgraphics.com/",
            homepage_domain="qpgraphics.com",
            verification_status="verified",
            verification_notes="The website is otherwise functional.",
        )
        text = "Your strong local reputation deserves an equally powerful online presence in the Bay Area."

        issues = collect_delivery_guard_issues(text, asset_type="email_sequence", facts=facts)

        self.assertTrue(any("metro area" in issue for issue in issues))

    def test_collect_delivery_guard_issues_does_not_treat_la_company_names_as_louisiana(self) -> None:
        facts = VerifiedCompanyFacts(
            company_name="QP Graphics, Inc.",
            location="Los Angeles, CA, US",
            homepage_url="",
            homepage_domain="",
            verification_status="verified",
            verification_notes="Directory evidence only.",
        )
        text = "Competitors include LA Print & Design Co. and Brand L.A., both serving Los Angeles."

        issues = collect_delivery_guard_issues(text, asset_type="proposal", facts=facts)

        self.assertFalse(any("state(s) LA" in issue for issue in issues))

    def test_collect_delivery_guard_issues_flags_hard_website_failure_claim(self) -> None:
        facts = VerifiedCompanyFacts(
            company_name="栄光情報システム株式会社",
            location="Tokyo, Japan",
            homepage_url="https://www.eiko-sys.co.jp/",
            homepage_domain="eiko-sys.co.jp",
            verification_status="verified",
            verification_notes="The website could not be verified from our audit environment.",
        )
        text = "The website is currently unreachable and your company is effectively invisible online."

        issues = collect_delivery_guard_issues(text, asset_type="email_sequence", facts=facts)

        self.assertTrue(any("hard website failure claim" in issue for issue in issues))

    def test_collect_delivery_guard_issues_flags_contradiction_with_functional_verification(self) -> None:
        facts = VerifiedCompanyFacts(
            company_name="QP Graphics, Inc.",
            location="Rochester, NY, US",
            homepage_url="https://www.qpgraphics.com/",
            homepage_domain="qpgraphics.com",
            verification_status="verified",
            verification_notes="The website could not be fully scraped due to JavaScript being disabled, but the website is otherwise functional.",
        )
        text = "Your website is currently inaccessible due to a critical technical error."

        issues = collect_delivery_guard_issues(text, asset_type="email_sequence", facts=facts)

        self.assertTrue(any("verified-functional" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
