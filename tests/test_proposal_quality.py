from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sales_factory.proposal_quality import evaluate_proposal_text


class ProposalQualityTests(unittest.TestCase):
    def test_heading_detection_is_case_insensitive(self) -> None:
        text = """# Example Co.
## Greeting
Hello

## Executive Summary
Summary

## What We Found
Findings

## Why This Matters
Impact

## Market and Competitor Snapshot
Snapshot

## Your Hidden Strengths
Strengths

## Recommended Direction
Direction

## 30-60-90 Day Execution Plan
Plan

## Recommended Packages
Packages

## Pricing Guidance
Pricing

## Why Onecation
Why us

## Suggested Next Step
1. Reply

## Closing
Thanks
"""

        result = evaluate_proposal_text(text)

        self.assertNotIn("Market And Competitor Snapshot", result["missing_sections"])


if __name__ == "__main__":
    unittest.main()
