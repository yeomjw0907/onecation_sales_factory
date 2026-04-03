from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sales_factory.managed_run import (
    build_inputs,
    build_llm_retry_overrides,
    build_quality_rework_feedback,
    is_retryable_llm_error,
    should_queue_quality_rework,
)


class ManagedRunRetryTests(unittest.TestCase):
    def test_build_inputs_includes_onecation_proof_points(self) -> None:
        args = argparse.Namespace(
            target_country="KR",
            lead_mode="region_or_industry",
            lead_query="Seoul printing companies",
            max_companies=2,
            proposal_language="Korean",
            currency="KRW",
            notify_email="ops@onecation.co.kr",
            test_mode=True,
            segment_id="korea-entry-overseas",
            segment_label="한국 시장 진입형 해외 기업",
            segment_brief="Only target overseas companies entering Korea.",
            quality_rework_feedback="",
            quality_rework_attempt=0,
        )

        with patch.dict("os.environ", {"SALES_FACTORY_SENDER_NAME": "Minjun Kim"}, clear=False), patch(
            "sales_factory.managed_run.load_onecation_proof_points",
            return_value="Approved proof only.",
        ):
            inputs = build_inputs(args)

        self.assertEqual(inputs["sender_name"], "Minjun Kim")
        self.assertEqual(inputs["onecation_proof_points"], "Approved proof only.")
        self.assertEqual(inputs["segment_id"], "korea-entry-overseas")
        self.assertEqual(inputs["segment_label"], "한국 시장 진입형 해외 기업")
        self.assertEqual(inputs["segment_brief"], "Only target overseas companies entering Korea.")
        self.assertEqual(inputs["quality_rework_feedback"], "")
        self.assertEqual(inputs["quality_rework_attempt"], "0")

    def test_is_retryable_llm_error_detects_transient_503(self) -> None:
        self.assertTrue(is_retryable_llm_error(RuntimeError("503 Service Unavailable: model is overloaded")))

    def test_build_llm_retry_overrides_downgrades_gemini_models(self) -> None:
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}, clear=False):
            overrides = build_llm_retry_overrides(
                [
                    {"task_name": "proposal_task", "model_name": "gemini-2.5-pro"},
                    {"task_name": "lead_research_task", "model_name": "gemini-2.5-flash"},
                ]
            )

        self.assertEqual(overrides["gemini-2.5-pro"], "gemini/gemini-2.5-flash")
        self.assertEqual(overrides["gemini-2.5-flash"], "gemini/gemini-2.5-flash-lite")

    def test_should_queue_quality_rework_when_score_is_below_threshold(self) -> None:
        self.assertTrue(
            should_queue_quality_rework(
                proposal_quality={"score": 82},
                validation_issues=[],
                attempt=0,
            )
        )

    def test_build_quality_rework_feedback_lists_issues(self) -> None:
        feedback = build_quality_rework_feedback(
            company_name="Acme Co.",
            proposal_quality={"score": 81},
            validation_issues=["email_sequence: unresolved placeholders -> [city]"],
            attempt=1,
        )

        self.assertIn("Acme Co.", feedback)
        self.assertIn("Raise proposal quality", feedback)
        self.assertIn("unresolved placeholders", feedback)


if __name__ == "__main__":
    unittest.main()
