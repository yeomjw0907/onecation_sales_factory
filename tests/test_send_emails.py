from __future__ import annotations

import sys
import tempfile
import unittest
from email import message_from_string
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import send_emails


class DummySMTP:
    def __init__(self) -> None:
        self.sent_messages: list[tuple[str, str, str]] = []

    def sendmail(self, from_email: str, recipient: str, message: str) -> None:
        self.sent_messages.append((from_email, recipient, message))


class SendEmailsTests(unittest.TestCase):
    def test_send_one_embeds_inline_branding_images(self) -> None:
        smtp = DummySMTP()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            logo_path = temp_path / "logo.png"
            kr_path = temp_path / "kr.png"
            en_path = temp_path / "en.png"
            png_bytes = bytes.fromhex(
                "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4890000000D49444154789C6360000002000154A24F5D0000000049454E44AE426082"
            )
            logo_path.write_bytes(png_bytes)
            kr_path.write_bytes(png_bytes)
            en_path.write_bytes(png_bytes)

            touch = send_emails.Touchpoint(
                tag="D6",
                channel="email",
                subject="글로벌 브랜드 제안",
                body="안녕하세요\n서울대학교 관련 제안을 드립니다.",
                cta="회신 부탁드립니다.",
            )

            with patch.object(send_emails, "EMAIL_BRANDING_LOGO", logo_path), patch.object(
                send_emails, "EMAIL_BRANDING_KR", kr_path
            ), patch.object(send_emails, "EMAIL_BRANDING_EN", en_path), patch.dict(
                "os.environ",
                {"SMTP_USER": "ops@onecation.co.kr"},
                clear=False,
            ):
                send_emails.send_one(
                    smtp=smtp,
                    to_email="client@example.com",
                    touch=touch,
                    company_name="서울대학교",
                    pdf_path=None,
                )

        parsed = message_from_string(smtp.sent_messages[0][2])
        self.assertEqual(parsed.get_content_type(), "multipart/related")
        payload = parsed.get_payload()
        self.assertEqual(payload[0].get_content_type(), "multipart/alternative")
        content_ids = {part.get("Content-ID") for part in payload[1:]}
        self.assertEqual(content_ids, {"<onecation-logo>", "<onecation-signature>"})
        filenames = {part.get_filename() for part in payload[1:]}
        self.assertEqual(filenames, {"logo.png", "kr.png"})


if __name__ == "__main__":
    unittest.main()
