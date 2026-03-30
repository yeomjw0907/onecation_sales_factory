from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sales_factory.output_validation import collect_validation_issues, normalize_customer_text, resolve_sender_name


class OutputValidationTests(unittest.TestCase):
    def test_resolve_sender_name_defaults_to_yeom_jeongwon(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(resolve_sender_name(), "염정원")

    def test_normalize_customer_text_replaces_known_sender_placeholders(self) -> None:
        with patch.dict("os.environ", {"SALES_FACTORY_SENDER_NAME": "염정원"}, clear=False):
            text = "안녕하세요, [your name]입니다."
            normalized = normalize_customer_text(text, asset_type="email_sequence")

        self.assertEqual(normalized, "안녕하세요, 염정원입니다.")

    def test_collect_validation_issues_flags_unresolved_placeholders(self) -> None:
        text = "Target local SEO around [city] before launch."

        issues = collect_validation_issues(text, asset_type="marketing_plan", proposal_language="en")

        self.assertTrue(any("unresolved placeholders" in issue for issue in issues))

    def test_normalize_customer_text_rewrites_follow_up_date_placeholders(self) -> None:
        text = "I wanted to follow up after [first outreach date]."

        normalized = normalize_customer_text(text, asset_type="email_sequence")

        self.assertEqual(normalized, "I wanted to follow up after earlier.")

    def test_collect_validation_issues_flags_unexpected_hangul_in_japanese_output(self) -> None:
        text = "## Greeting\n안녕하세요. 일본어 문서인데 한글이 섞여 있습니다."

        issues = collect_validation_issues(text, asset_type="proposal", proposal_language="Japanese")

        self.assertTrue(any("unexpected Korean text" in issue for issue in issues))

    def test_collect_validation_issues_flags_network_assertions_in_customer_copy(self) -> None:
        text = "Our audit found a DNS error on the primary domain."

        issues = collect_validation_issues(text, asset_type="email_sequence", proposal_language="en")

        self.assertTrue(any("network failure" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
