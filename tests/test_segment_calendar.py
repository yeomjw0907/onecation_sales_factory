from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sales_factory import segment_calendar


class SegmentCalendarTests(unittest.TestCase):
    def test_build_segment_query_and_brief_use_selected_preset(self) -> None:
        query = segment_calendar.build_segment_query("korea-entry-overseas", "TW")
        brief = segment_calendar.build_segment_brief("korea-entry-overseas", "TW")

        self.assertIn("Taiwan companies entering Korea", query)
        self.assertIn("Active segment: 한국 시장 진입형 해외 기업", brief)
        self.assertIn("Offer: Korea-entry landing page + local acquisition package", brief)
        self.assertIn(query, brief)

    def test_calendar_entry_lifecycle_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            calendar_path = Path(temp_dir) / "segment_calendar.json"
            today = date.today()
            tomorrow = today + timedelta(days=1)

            with patch.object(segment_calendar, "SEGMENT_CALENDAR_PATH", calendar_path), patch.object(
                segment_calendar, "ensure_runtime_dirs"
            ):
                first = segment_calendar.create_segment_calendar_entry(
                    schedule_date=today,
                    segment_id="international-student-recruitment",
                    target_country="US",
                    send_window="오전",
                    max_companies=8,
                    notes="priority schools",
                )
                second = segment_calendar.create_segment_calendar_entry(
                    schedule_date=tomorrow,
                    segment_id="portfolio-institution-program",
                    target_country="KR",
                    send_window="오후",
                    max_companies=5,
                    notes="batch outreach",
                )

                segment_calendar.add_segment_calendar_entry(second)
                segment_calendar.add_segment_calendar_entry(first)

                today_rows = segment_calendar.list_segment_calendar_entries_for_date(today)
                self.assertEqual(len(today_rows), 1)
                self.assertEqual(today_rows[0]["id"], first["id"])
                self.assertEqual(today_rows[0]["segment_label"], "해외 학생 모집 교육기관")
                self.assertIn("admissions websites", today_rows[0]["lead_query"])

                upcoming_rows = segment_calendar.list_upcoming_segment_calendar_entries(days=2)
                self.assertEqual([row["id"] for row in upcoming_rows], [first["id"], second["id"]])

                segment_calendar.mark_segment_calendar_entry_launched(first["id"])
                relaunched = segment_calendar.list_segment_calendar_entries_for_date(today)[0]
                self.assertTrue(relaunched["last_launched_at"])

                segment_calendar.delete_segment_calendar_entry(first["id"])
                self.assertEqual(segment_calendar.list_segment_calendar_entries_for_date(today), [])


if __name__ == "__main__":
    unittest.main()
