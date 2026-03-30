from __future__ import annotations

import sys
import tempfile
import unittest
from email import message_from_string
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sales_factory.runtime_notifications import send_email_message


class DummySMTP:
    def __init__(self) -> None:
        self.sent_messages: list[tuple[str, list[str], str]] = []

    def sendmail(self, from_email: str, recipients: list[str], message: str) -> None:
        self.sent_messages.append((from_email, recipients, message))

    def quit(self) -> None:
        return None


class RuntimeNotificationsTests(unittest.TestCase):
    def test_send_email_message_wraps_alternative_body_inside_mixed_message(self) -> None:
        smtp = DummySMTP()
        with tempfile.TemporaryDirectory() as temp_dir:
            attachment_path = Path(temp_dir) / "proposal.pdf"
            attachment_path.write_bytes(b"%PDF-1.4")

            with patch("sales_factory.runtime_notifications.build_smtp", return_value=smtp), patch.dict(
                "os.environ",
                {"SMTP_USER": "ops@onecation.co.kr"},
                clear=False,
            ):
                send_email_message(
                    subject="Test subject",
                    body_text="Plain body",
                    body_html="<p>HTML body</p>",
                    to_email="client@example.com",
                    attachment_paths=[attachment_path],
                )

        self.assertEqual(len(smtp.sent_messages), 1)
        from_email, recipients, raw_message = smtp.sent_messages[0]
        self.assertEqual(from_email, "ops@onecation.co.kr")
        self.assertEqual(recipients, ["client@example.com"])

        parsed = message_from_string(raw_message)
        self.assertEqual(parsed.get_content_type(), "multipart/mixed")
        payload = parsed.get_payload()
        self.assertEqual(payload[0].get_content_type(), "multipart/alternative")
        self.assertEqual(payload[1].get_filename(), "proposal.pdf")


if __name__ == "__main__":
    unittest.main()
