from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import web_dashboard


class DashboardPipelineTests(unittest.TestCase):
    def test_build_pipeline_stages_adds_review_station(self) -> None:
        tasks = [
            {
                "task_name": "lead_research_task",
                "status": "completed",
                "total_tokens": 1800,
            },
            {
                "task_name": "proposal_task",
                "status": "running",
                "total_tokens": 4200,
            },
        ]
        latest_run = {
            "id": "run-1",
            "status": "waiting_approval",
            "error_message": "",
        }

        with patch("web_dashboard.list_approval_items", return_value=[{"run_id": "run-1"}]):
            stages = web_dashboard.build_pipeline_stages(tasks, latest_run)

        self.assertEqual(stages[-1]["department"], "검토 운영본부")
        self.assertEqual(stages[-1]["status"], "waiting_approval")
        self.assertIn("검토 대기", stages[-1]["note"])
        self.assertEqual(stages[1]["status"], "running")

    def test_summarize_pipeline_progress_uses_current_stage(self) -> None:
        stages = [
            {"status": "completed", "task_label": "회사 탐색", "department": "시장 탐색부", "owner_label": "강태준 대리"},
            {"status": "running", "task_label": "제안서 초안", "department": "제안서 초안부", "owner_label": "이현우 차장"},
            {"status": "pending", "task_label": "메일 현지화", "department": "메일 현지화부", "owner_label": "에리카 매니저"},
            {"status": "pending", "task_label": "승인 판단", "department": "검토 운영본부", "owner_label": "오세훈 과장 외 1명"},
        ]

        summary = web_dashboard.summarize_pipeline_progress(stages)

        self.assertEqual(summary["started_count"], 2)
        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(summary["progress_percent"], 50)
        self.assertEqual(summary["current_stage"]["task_label"], "제안서 초안")

    def test_build_pipeline_timing_summary_estimates_eta_and_durations(self) -> None:
        stages = [
            {
                "status": "completed",
                "kind": "task",
                "task_name": "lead_research_task",
                "started_at": "2026-03-31T10:00:00",
                "finished_at": "2026-03-31T10:05:00",
            },
            {
                "status": "running",
                "kind": "task",
                "task_name": "proposal_task",
                "started_at": "2026-03-31T10:05:00",
                "finished_at": "",
            },
            {
                "status": "pending",
                "kind": "task",
                "task_name": "email_localization_task",
                "started_at": "",
                "finished_at": "",
            },
        ]
        latest_run = {
            "status": "running",
            "started_at": "2026-03-31T10:00:00",
            "finished_at": "",
        }

        summary = web_dashboard.build_pipeline_timing_summary(
            stages,
            latest_run,
            reference_time=datetime(2026, 3, 31, 10, 7, 0),
            baselines={
                "lead_research_task": 5,
                "proposal_task": 5,
                "email_localization_task": 5,
                "review_station": 8,
            },
        )

        self.assertEqual(summary["elapsed_label"], "7분")
        self.assertEqual(summary["eta_label"], "8분")
        self.assertEqual(summary["estimated_finish_label"], "03-31 10:15 (화)")
        self.assertEqual(stages[0]["duration_label"], "소요 5분 · 기준 5분")
        self.assertEqual(stages[1]["duration_label"], "체류 2분 · 기준 5분")

    def test_resolve_run_log_path_prefers_metadata_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "dashboard-run-test.log"
            log_path.write_text("hello", encoding="utf-8")

            resolved = web_dashboard.resolve_run_log_path(
                {
                    "metadata_json": {"log_path": str(log_path)},
                }
            )

        self.assertEqual(resolved, log_path)


if __name__ == "__main__":
    unittest.main()
