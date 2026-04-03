#!/usr/bin/env python3
"""
send_emails.py — Crew 출력 → D1/D6/D10 이메일 자동 발송 (PDF 첨부)

사용법:
    # 미리보기 (발송 안 함, 기본값)
    python send_emails.py --preview

    # 특정 회사 1건 미리보기
    python send_emails.py --company "동우문화" --to contact@example.com

    # contacts.csv 기반 전체 발송 (확인 후 발송)
    python send_emails.py --contacts contacts.csv --send

    # 특정 회사만 발송
    python send_emails.py --company "동우문화" --to ceo@dongwoo.com --send

    # D6 리마인더 발송 (D1 발송 후 6일 뒤)
    python send_emails.py --contacts contacts.csv --touch D6 --send

.env 필수 항목:
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=yeomjw0907@onecation.co.kr
    SMTP_PASSWORD=앱비밀번호

contacts.csv 형식:
    company_name,email,name
    동우문화,ceo@dongwoo.com,홍길동 대표님
"""

import argparse
import csv
import io
import json
import mimetypes
import os
import re
import smtplib
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    _env = Path(__file__).parent / ".env"
    if _env.exists():
        for _line in _env.read_text(encoding="utf-8").splitlines():
            if "=" in _line and not _line.startswith("#"):
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

# ─── 경로 & 상수 ──────────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent
OUTREACH_FILE = BASE_DIR / "outreach_emails.md"
OUTPUT_DIR    = BASE_DIR / "output"
LOG_FILE      = OUTPUT_DIR / "email_log.json"
TODAY_FILE    = date.today().strftime("%Y-%m-%d")

BRAND = {
    "name":    "Onecation",
    "tagline": "데이터 기반 마케팅 파트너",
    "phone":   "010-6333-4649",
    "email":   "yeomjw0907@onecation.co.kr",
    "color":   "#0D1B2A",
}

KOREAN_COMPANY_NAME = "주식회사 98점7도"
KOREAN_SENDER_NAME = "염정원"
KOREAN_FIXED_INTRO = f"안녕하세요, {KOREAN_COMPANY_NAME} {KOREAN_SENDER_NAME}입니다."
KOREAN_SUBJECT_PREFIX = f"[{KOREAN_COMPANY_NAME}]"
HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
BRAND_WEBSITE_URL = "https://onecation.co.kr/"
EMAIL_BRANDING_DIR = BASE_DIR / "src" / "sales_factory" / "assets" / "email_branding"
EMAIL_BRANDING_LOGO = EMAIL_BRANDING_DIR / "logo.png"
EMAIL_BRANDING_KR = EMAIL_BRANDING_DIR / "kr.png"
EMAIL_BRANDING_EN = EMAIL_BRANDING_DIR / "en.png"

TOUCH_DAYS = {"D1": 1, "D3": 3, "D6": 6, "D10": 10}


# ═══════════════════════════════════════════════════════════════════════════════
# 데이터 클래스
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Touchpoint:
    tag: str          # D1 / D3 / D6 / D10
    channel: str      # email / call_or_sms
    subject: str = ""
    body: str    = ""
    cta: str     = ""


@dataclass
class CompanySequence:
    company_name: str
    touches: list[Touchpoint] = field(default_factory=list)

    def get(self, tag: str) -> Touchpoint | None:
        for t in self.touches:
            if t.tag.upper() == tag.upper():
                return t
        return None

    @property
    def email_touches(self) -> list[Touchpoint]:
        return [t for t in self.touches if "email" in t.channel.lower()]


@dataclass
class Contact:
    company_name: str
    email: str
    name: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# 파서
# ═══════════════════════════════════════════════════════════════════════════════

def parse_outreach(path: Path) -> dict[str, CompanySequence]:
    """outreach_emails.md → {company_name: CompanySequence}."""
    text  = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    seqs: dict[str, CompanySequence] = {}
    cur_company: str | None = None
    cur_touch:   Touchpoint | None = None
    body_lines:  list[str] = []
    in_body = False

    def _flush_body():
        nonlocal body_lines, in_body
        if cur_touch and body_lines:
            cur_touch.body = "\n".join(body_lines).strip()
        body_lines = []
        in_body = False

    def _flush_touch():
        nonlocal cur_touch
        _flush_body()
        if cur_company and cur_touch:
            seqs[cur_company].touches.append(cur_touch)
        cur_touch = None

    for line in lines:
        # H1 → 회사명
        m1 = re.match(r"^#\s+(.+)", line)
        if m1:
            _flush_touch()
            cur_company = m1.group(1).strip()
            seqs[cur_company] = CompanySequence(company_name=cur_company)
            continue

        if cur_company is None:
            continue

        # H2 → 터치포인트 (D1, D3, D6, D10)
        m2 = re.match(r"^##\s+(.+)", line)
        if m2:
            _flush_touch()
            heading = m2.group(1).strip().upper()
            tag = "D1"
            for t in ("D10", "D6", "D3", "D1"):
                if t in heading:
                    tag = t
                    break
            channel = "email" if "이메일" in heading.lower() or "email" in heading.lower() else "call_or_sms"
            cur_touch = Touchpoint(tag=tag, channel=channel)
            in_body = False
            continue

        if cur_touch is None:
            continue

        # 불릿 필드 파싱
        stripped = line.lstrip("- ").strip()

        # body: | 다음 줄부터 들여쓰기로 이어짐
        if re.match(r"^body\s*:\s*\|", stripped, re.I):
            in_body = True
            body_lines = []
            continue
        if re.match(r"^body\s*:\s*(.+)", stripped, re.I):
            m = re.match(r"^body\s*:\s*(.+)", stripped, re.I)
            cur_touch.body = m.group(1).strip() if m else ""
            in_body = False
            continue

        # 들여쓰기된 body 내용
        if in_body:
            if line.startswith("  ") or line.startswith("\t") or not line.strip():
                body_lines.append(line.strip())
                continue
            elif re.match(r"^-\s+\w+\s*:", line):
                # 다음 필드 시작 → body 종료
                _flush_body()
            else:
                body_lines.append(line.strip())
                continue

        # subject_if_email / subject
        m_sub = re.match(r"^subject(?:_if_email)?\s*:\s*(.+)", stripped, re.I)
        if m_sub:
            cur_touch.subject = m_sub.group(1).strip()
            continue

        # channel
        m_ch = re.match(r"^channel\s*:\s*(.+)", stripped, re.I)
        if m_ch:
            cur_touch.channel = m_ch.group(1).strip().lower()
            continue

        # CTA
        m_cta = re.match(r"^cta\s*:\s*(.+)", stripped, re.I)
        if m_cta:
            cur_touch.cta = m_cta.group(1).strip()
            continue

    _flush_touch()
    return seqs


def load_contacts(path: Path) -> dict[str, Contact]:
    """contacts.csv → {company_name: Contact}."""
    contacts: dict[str, Contact] = {}
    with path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name    = row.get("company_name", "").strip()
            email   = row.get("email", "").strip()
            contact = row.get("name", "").strip()
            if name and email:
                contacts[name] = Contact(company_name=name, email=email, name=contact)
    return contacts


def find_pdf(company_name: str) -> Path | None:
    """output/ 에서 회사명 PDF 탐색."""
    safe = re.sub(r'[\\/*?:"<>|]', "_", company_name)
    candidates = sorted(OUTPUT_DIR.glob(f"{safe}_제안서_*.pdf"), reverse=True)
    if candidates:
        return candidates[0]
    # 부분 매칭
    for p in sorted(OUTPUT_DIR.glob("*_제안서_*.pdf"), reverse=True):
        if company_name in p.stem or safe in p.stem:
            return p
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# HTML 이메일 렌더링
# ═══════════════════════════════════════════════════════════════════════════════

def _md_to_html(text: str) -> str:
    """마크다운 본문 → 인라인 HTML."""
    lines = []
    for line in text.splitlines():
        line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        if not line.strip():
            lines.append("<br>")
        else:
            lines.append(line + "<br>")
    return "\n".join(lines)


def _body_with_name(body: str, recipient_name: str) -> str:
    """본문에서 [Contact Name], {{name}}을 수신자 이름으로 치환."""
    name = (recipient_name or "귀하").strip() or "귀하"
    return (body or "").replace("[Contact Name]", name).replace("{{name}}", name)


def _detect_email_language(text: str) -> str:
    return "ko" if HANGUL_RE.search(text or "") else "other"


def _normalize_subject(subject: str, body_text: str) -> str:
    normalized = " ".join((subject or "").split()).strip()
    if _detect_email_language(f"{subject}\n{body_text}") != "ko":
        return normalized

    core = normalized
    if core.startswith(KOREAN_SUBJECT_PREFIX):
        core = core[len(KOREAN_SUBJECT_PREFIX) :].strip()
    if core.endswith("의 건"):
        core = core[: -len("의 건")].strip()
    core = core.strip(" -:|")
    return f"{KOREAN_SUBJECT_PREFIX} {core or '제안'}의 건"


def _is_korean_intro_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if stripped == KOREAN_FIXED_INTRO:
        return True
    if stripped.startswith("안녕하세요") or stripped.startswith("안녕하십니까"):
        return True
    return (
        ("onecation" in lowered or "원케이션" in stripped or KOREAN_COMPANY_NAME in stripped)
        and ("입니다" in stripped or "드립니다" in stripped or "대표" in stripped)
    )


def _normalize_body_intro(body: str) -> str:
    normalized = (body or "").strip()
    if _detect_email_language(normalized) != "ko":
        return normalized

    lines = normalized.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)

    consumed = 0
    for idx, line in enumerate(lines[:3]):
        stripped = line.strip()
        if not stripped:
            consumed = idx + 1
            continue
        if _is_korean_intro_line(stripped):
            consumed = idx + 1
            continue
        break

    remainder = "\n".join(lines[consumed:]).strip() if consumed else normalized
    if not remainder:
        return KOREAN_FIXED_INTRO
    return f"{KOREAN_FIXED_INTRO}\n\n{remainder}"


def _get_branding_inline_image_paths(language: str) -> dict[str, Path]:
    signature_path = EMAIL_BRANDING_KR if language == "ko" else EMAIL_BRANDING_EN
    inline_images: dict[str, Path] = {}
    if EMAIL_BRANDING_LOGO.exists():
        inline_images["onecation-logo"] = EMAIL_BRANDING_LOGO
    if signature_path.exists():
        inline_images["onecation-signature"] = signature_path
    return inline_images


def _render_brand_logo_html() -> str:
    return (
        f'<a href="{BRAND_WEBSITE_URL}" style="text-decoration:none;display:block;">'
        '<img src="cid:onecation-logo" alt="Onecation logo" '
        'style="display:block;width:100%;max-width:820px;height:auto;border:0;border-radius:18px;">'
        "</a>"
    )


def _render_brand_signature_html(language: str) -> str:
    alt = "Onecation Korean signature banner" if language == "ko" else "Onecation English signature banner"
    return (
        f'<a href="{BRAND_WEBSITE_URL}" style="text-decoration:none;display:block;">'
        f'<img src="cid:onecation-signature" alt="{alt}" '
        'style="display:block;width:100%;max-width:850px;height:auto;border:0;border-radius:18px;">'
        "</a>"
    )


def render_html(touch: Touchpoint, company_name: str, has_pdf: bool, recipient_name: str = "") -> str:
    body_text = _normalize_body_intro(_body_with_name(touch.body or "", recipient_name))
    body_html = _md_to_html(body_text) if body_text else ""
    cta_text  = touch.cta or f"연락 주시면 바로 안내드리겠습니다 — {BRAND['phone']} / {BRAND['email']}"
    pdf_note  = (
        f'<p style="color:#0B7285;font-size:13px;margin:0 0 8px;">'
        f'📎 <strong>{company_name}</strong> 맞춤 제안서를 첨부했습니다. '
        f'1–2장만 보셔도 핵심을 파악하실 수 있게 구성해 두었습니다.</p>'
    ) if has_pdf else ""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F7F9FC;font-family:'Malgun Gothic','맑은 고딕',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F7F9FC;padding:24px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:8px;overflow:hidden;
                    box-shadow:0 2px 8px rgba(0,0,0,0.08);">

        <!-- 헤더 -->
        <tr>
          <td style="background:{BRAND['color']};padding:20px 32px;">
            <span style="color:#D4A030;font-size:18px;font-weight:bold;">{BRAND['name']}</span>
            <span style="color:#8BACC8;font-size:12px;margin-left:10px;">{BRAND['tagline']}</span>
          </td>
        </tr>

        <!-- 본문 -->
        <tr>
          <td style="padding:32px 32px 16px;">
            <p style="font-size:15px;color:#1A202C;line-height:1.8;margin:0;">
              {body_html}
            </p>
          </td>
        </tr>

        <!-- PDF 안내 -->
        {f'<tr><td style="padding:0 32px 8px;">{pdf_note}</td></tr>' if pdf_note else ''}

        <!-- CTA -->
        <tr>
          <td style="padding:16px 32px 32px;">
            <div style="background:#F7F9FC;border-left:4px solid #0B7285;
                        padding:14px 18px;border-radius:0 6px 6px 0;">
              <span style="font-size:12px;color:#64748B;">다음 단계</span><br>
              <span style="font-size:14px;color:#0D1B2A;font-weight:bold;">
                {cta_text}
              </span>
            </div>
          </td>
        </tr>

        <!-- 서명 -->
        <tr>
          <td style="padding:0 32px 24px;border-top:1px solid #E2E8F0;">
            <table cellpadding="0" cellspacing="0" style="margin-top:16px;">
              <tr>
                <td style="padding-right:16px;border-right:2px solid #D4A030;">
                  <p style="margin:0;font-size:14px;font-weight:bold;color:#0D1B2A;">{BRAND['name']}</p>
                  <p style="margin:2px 0 0;font-size:11px;color:#64748B;">{BRAND['tagline']}</p>
                </td>
                <td style="padding-left:16px;">
                  <p style="margin:0;font-size:12px;color:#5E6E82;">
                    📞 {BRAND['phone']}<br>
                    ✉ {BRAND['email']}
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- 푸터 -->
        <tr>
          <td style="background:#F7F9FC;padding:12px 32px;text-align:center;">
            <p style="margin:0;font-size:10px;color:#94A3B8;">
              본 메일은 {company_name} 맞춤 제안 목적으로 발송되었습니다.
              수신 거부 시 답장 주시면 반영하겠습니다.
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def render_branded_html(touch: Touchpoint, company_name: str, has_pdf: bool, recipient_name: str = "") -> str:
    body_text = _normalize_body_intro(_body_with_name(touch.body or "", recipient_name))
    body_html = _md_to_html(body_text) if body_text else ""
    language = _detect_email_language(body_text)
    cta_text = touch.cta or f"?곕씫 二쇱떆硫?諛붾줈 ?덈궡?쒕━寃좎뒿?덈떎 ??{BRAND['phone']} / {BRAND['email']}"
    pdf_note = (
        f'<p style="color:#0B7285;font-size:13px;margin:0 0 8px;">'
        f'?뱨 <strong>{company_name}</strong> 留욎땄 ?쒖븞?쒕? 泥⑤??덉뒿?덈떎. '
        f'1???λ쭔 蹂댁뀛???듭떖???뚯븙?섏떎 ???덇쾶 援ъ꽦???먯뿀?듬땲??</p>'
    ) if has_pdf else ""

    return f"""<!DOCTYPE html>
<html lang="{language if language == 'ko' else 'en'}">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F3F5F9;font-family:'Malgun Gothic','Apple SD Gothic Neo','Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F3F5F9;padding:28px 12px;">
    <tr><td align="center">
      <table width="680" cellpadding="0" cellspacing="0" style="width:100%;max-width:680px;">
        <tr>
          <td style="padding-bottom:14px;">
            {_render_brand_logo_html()}
          </td>
        </tr>
        <tr>
          <td style="background:#ffffff;border:1px solid #E2E8F0;border-radius:18px;padding:34px 34px 28px;box-shadow:0 10px 30px rgba(15,23,42,0.08);">
            <div style="font-size:15px;color:#1D2433;line-height:1.8;">{body_html}</div>
            {pdf_note}
            <div style="margin-top:18px;background:#F7F9FC;border-left:4px solid #0B7285;padding:14px 18px;border-radius:0 6px 6px 0;">
              <span style="font-size:12px;color:#64748B;">?ㅼ쓬 ?④퀎</span><br>
              <span style="font-size:14px;color:#0D1B2A;font-weight:bold;">{cta_text}</span>
            </div>
          </td>
        </tr>
        <tr>
          <td style="padding-top:16px;">
            {_render_brand_signature_html(language)}
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def render_plain(touch: Touchpoint, company_name: str, recipient_name: str = "") -> str:
    """HTML 미지원 클라이언트용 plain text. [Contact Name]은 recipient_name으로 치환."""
    body = _normalize_body_intro(_body_with_name(touch.body or "", recipient_name))
    cta = touch.cta or BRAND["phone"]
    lines = [body, "", f"→ {cta}", "", "---", BRAND["name"], BRAND["phone"], BRAND["email"]]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# 발송 로그
# ═══════════════════════════════════════════════════════════════════════════════

def load_log() -> dict:
    if LOG_FILE.exists():
        try:
            return json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_log(log: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def log_key(company: str, touch: str) -> str:
    return f"{company}::{touch}"


def is_sent(log: dict, company: str, touch: str) -> bool:
    return log_key(company, touch) in log


def mark_sent(log: dict, company: str, touch: str, to_email: str, status: str) -> None:
    log[log_key(company, touch)] = {
        "company":    company,
        "touch":      touch,
        "to":         to_email,
        "status":     status,
        "sent_at":    datetime.now().isoformat(timespec="seconds"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SMTP 발송
# ═══════════════════════════════════════════════════════════════════════════════

def build_smtp() -> smtplib.SMTP:
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    pwd  = os.environ.get("SMTP_PASSWORD", "")

    if not user or not pwd:
        raise RuntimeError(
            ".env에 SMTP_USER와 SMTP_PASSWORD를 설정해주세요.\n"
            "  Gmail 앱 비밀번호: https://myaccount.google.com/apppasswords"
        )

    smtp = smtplib.SMTP(host, port, timeout=15)
    smtp.ehlo()
    smtp.starttls()
    smtp.login(user, pwd)
    return smtp


def _legacy_send_one(
    smtp: smtplib.SMTP,
    to_email: str,
    touch: Touchpoint,
    company_name: str,
    pdf_path: Path | None,
    recipient_name: str = "",
) -> bool:
    """이메일 1건 발송. recipient_name은 본문 [Contact Name]/{{name}} 치환용."""
    from_addr = os.environ.get("SMTP_USER", BRAND["email"])
    subject_body = _body_with_name(touch.body or "", recipient_name)
    subject = _normalize_subject(
        touch.subject or f"[{company_name}] 맞춤 마케팅 제안 — {touch.tag}",
        subject_body,
    )

    plain_body = render_plain(touch, company_name, recipient_name)
    msg["From"]    = f"{BRAND['name']} <{from_addr}>"
    msg["To"]      = to_email
    msg["Subject"] = subject

    has_pdf = pdf_path is not None and pdf_path.exists()
    msg.attach(MIMEText(render_plain(touch, company_name, recipient_name), "plain", "utf-8"))
    msg.attach(MIMEText(render_html(touch, company_name, has_pdf, recipient_name), "html", "utf-8"))

    # PDF 첨부 (D1만)
    if has_pdf and touch.tag == "D1":
        outer = MIMEMultipart("mixed")
        outer["From"]    = msg["From"]
        outer["To"]      = msg["To"]
        outer["Subject"] = msg["Subject"]
        outer.attach(msg)
        with open(pdf_path, "rb") as f:
            att = MIMEApplication(f.read(), _subtype="pdf")
            att.add_header("Content-Disposition", "attachment",
                           filename=pdf_path.name.encode("utf-8").decode("ascii", errors="replace"))
            outer.attach(att)
        smtp.sendmail(from_addr, to_email, outer.as_string())
    else:
        smtp.sendmail(from_addr, to_email, msg.as_string())

    return True


# ═══════════════════════════════════════════════════════════════════════════════
# 미리보기 출력
# ═══════════════════════════════════════════════════════════════════════════════

def send_one(
    smtp: smtplib.SMTP,
    to_email: str,
    touch: Touchpoint,
    company_name: str,
    pdf_path: Path | None,
    recipient_name: str = "",
) -> bool:
    """Branded email send path with inline logo/signature images."""
    from_addr = os.environ.get("SMTP_USER", BRAND["email"])
    subject_body = _body_with_name(touch.body or "", recipient_name)
    subject = _normalize_subject(
        touch.subject or f"[{company_name}] 留욎땄 留덉????쒖븞 ??{touch.tag}",
        subject_body,
    )

    has_pdf = pdf_path is not None and pdf_path.exists()
    plain_body = render_plain(touch, company_name, recipient_name)
    language = _detect_email_language(subject_body or plain_body)
    inline_image_paths = {
        cid: path
        for cid, path in _get_branding_inline_image_paths(language).items()
        if path.exists() and path.is_file()
    }

    message = MIMEMultipart("mixed") if has_pdf and touch.tag == "D1" else MIMEMultipart("related" if inline_image_paths else "alternative")
    message["From"] = f"{BRAND['name']} <{from_addr}>"
    message["To"] = to_email
    message["Subject"] = subject

    body_container: MIMEMultipart = MIMEMultipart("related") if (has_pdf and touch.tag == "D1" and inline_image_paths) else message
    if body_container is not message:
        message.attach(body_container)

    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(plain_body, "plain", "utf-8"))
    alternative.attach(MIMEText(render_branded_html(touch, company_name, has_pdf, recipient_name), "html", "utf-8"))
    body_container.attach(alternative)

    for cid, image_path in inline_image_paths.items():
        mime_type, _ = mimetypes.guess_type(str(image_path))
        subtype = "png"
        if mime_type and "/" in mime_type:
            subtype = mime_type.split("/", 1)[1]
        image_part = MIMEImage(image_path.read_bytes(), _subtype=subtype)
        image_part.add_header("Content-ID", f"<{cid}>")
        image_part.add_header("Content-Disposition", "inline", filename=image_path.name)
        body_container.attach(image_part)

    if has_pdf and touch.tag == "D1":
        with open(pdf_path, "rb") as f:
            att = MIMEApplication(f.read(), _subtype="pdf")
            att.add_header(
                "Content-Disposition",
                "attachment",
                filename=pdf_path.name.encode("utf-8").decode("ascii", errors="replace"),
            )
            message.attach(att)

    smtp.sendmail(from_addr, to_email, message.as_string())
    return True


def print_preview(
    company: str,
    contact: Contact | None,
    touch: Touchpoint,
    pdf_path: Path | None,
    log: dict,
    force: bool,
) -> None:
    to_email = contact.email if contact else "(이메일 미지정)"
    already  = is_sent(log, company, touch.tag) and not force
    status   = "[이미 발송됨 - 스킵]" if already else "[발송 예정]"

    print(f"\n{'─'*60}")
    print(f"  회사: {company}")
    print(f"  수신: {to_email}  ({contact.name if contact else '-'})")
    print(f"  터치: {touch.tag}  {status}")
    preview_subject = _normalize_subject(touch.subject or "(제목 없음)", touch.body or "")
    print(f"  제목: {preview_subject}")
    print(f"  본문: {(touch.body or '')[:120].replace(chr(10),' ')}...")
    print(f"  PDF:  {pdf_path.name if pdf_path else '(없음)'}")
    print(f"  CTA:  {touch.cta or '-'}")


# ═══════════════════════════════════════════════════════════════════════════════
# 메인 로직
# ═══════════════════════════════════════════════════════════════════════════════

def run(args: argparse.Namespace) -> None:
    outreach_path = Path(args.outreach)
    if not outreach_path.exists():
        print(f"[오류] outreach_emails.md 없음: {outreach_path}")
        sys.exit(1)

    seqs = parse_outreach(outreach_path)
    if not seqs:
        print("[오류] 파싱된 이메일 시퀀스가 없습니다.")
        sys.exit(1)

    # 연락처 로드
    contacts: dict[str, Contact] = {}
    if args.contacts and Path(args.contacts).exists():
        contacts = load_contacts(Path(args.contacts))
    if args.to and args.company:
        contacts[args.company] = Contact(
            company_name=args.company, email=args.to, name=args.recipient_name or ""
        )

    # 회사 필터
    if args.company:
        seqs = {k: v for k, v in seqs.items()
                if args.company in k or k in args.company}
        if not seqs:
            print(f"[오류] '{args.company}' 시퀀스를 찾지 못했습니다.")
            print(f"  감지된 회사: {list(parse_outreach(outreach_path).keys())}")
            sys.exit(1)

    touch_filter = args.touch.upper() if args.touch else "D1"
    log = load_log()

    # 발송 대상 수집
    tasks = []
    for company_name, seq in seqs.items():
        touch = seq.get(touch_filter)
        if touch is None or "email" not in touch.channel.lower():
            continue
        contact  = contacts.get(company_name)
        pdf_path = find_pdf(company_name)
        tasks.append((company_name, contact, touch, pdf_path))

    if not tasks:
        print(f"[알림] {touch_filter} 이메일 터치포인트가 없거나 수신자 정보가 없습니다.")
        sys.exit(0)

    # ── 미리보기 ─────────────────────────────────────────────────────────────
    print(f"\n[Sales Factory 이메일 발송기]")
    print(f"  터치: {touch_filter}  |  대상: {len(tasks)}건  |  {'실제 발송' if args.send else '미리보기'}")

    sendable = []
    for company_name, contact, touch, pdf_path in tasks:
        print_preview(company_name, contact, touch, pdf_path, log, args.force)
        if contact and contact.email:
            if not is_sent(log, company_name, touch_filter) or args.force:
                sendable.append((company_name, contact, touch, pdf_path))
        else:
            print(f"  [스킵] 수신 이메일 없음 — contacts.csv 또는 --to 로 지정하세요")

    if not args.send:
        print(f"\n{'─'*60}")
        print(f"  미리보기 완료. 실제 발송하려면 --send 플래그를 추가하세요.")
        print(f"  발송 가능: {len(sendable)}건")
        return

    if not sendable:
        print("\n  발송할 항목이 없습니다.")
        return

    # ── 발송 확인 ─────────────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    ans = input(f"  정말 {len(sendable)}건을 발송합니까? (yes/no): ").strip().lower()
    if ans not in ("yes", "y"):
        print("  발송 취소.")
        return

    # ── SMTP 연결 + 발송 ──────────────────────────────────────────────────────
    try:
        smtp = build_smtp()
        print(f"  SMTP 연결 성공: {os.environ.get('SMTP_HOST','smtp.gmail.com')}")
    except Exception as e:
        print(f"\n[SMTP 오류] {e}")
        sys.exit(1)

    ok_count = fail_count = 0
    try:
        for company_name, contact, touch, pdf_path in sendable:
            try:
                send_one(smtp, contact.email, touch, company_name, pdf_path, contact.name)
                mark_sent(log, company_name, touch_filter, contact.email, "sent")
                save_log(log)
                ok_count += 1
                print(f"  [발송완료] {company_name} → {contact.email}")

                # 연속 발송 간격 (Gmail 제한 방지)
                if ok_count < len(sendable):
                    import time; time.sleep(2)

            except Exception as e:
                mark_sent(log, company_name, touch_filter, contact.email, f"failed: {e}")
                save_log(log)
                fail_count += 1
                print(f"  [실패] {company_name}: {e}")
    finally:
        smtp.quit()

    print(f"\n  완료: 성공 {ok_count}건 / 실패 {fail_count}건")
    print(f"  로그: {LOG_FILE}")

    # ── (선택) Notion에 제안서 PDF 링크 반영 ───────────────────────────────────
    if args.sync_notion and sendable:
        sync_script = BASE_DIR / "sync_pdf_to_notion.py"
        if not sync_script.exists():
            print(f"\n  [sync-notion] 스크립트 없음: {sync_script}")
        elif not os.getenv("NOTION_PDF_BASE_URL") and not (os.getenv("NOTION_PDF_UPLOAD") or "").strip().lower() in ("true", "1", "yes", "on"):
            print("\n  [sync-notion] NOTION_PDF_BASE_URL 또는 NOTION_PDF_UPLOAD=true 미설정 → 스킵.")
        else:
            import subprocess
            print("\n  [sync-notion] Notion 페이지에 제안서 PDF 링크 반영 중...")
            rc = subprocess.run(
                [sys.executable, str(sync_script)],
                cwd=str(BASE_DIR),
                capture_output=False,
            )
            if rc.returncode != 0:
                print(f"  [sync-notion] 종료 코드: {rc.returncode}")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crew 이메일 시퀀스 → 자동 발송 (PDF 첨부)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--outreach",        default=str(OUTREACH_FILE),
                        help="outreach_emails.md 경로")
    parser.add_argument("--contacts",        default=None,
                        help="contacts.csv 경로 (company_name, email, name)")
    parser.add_argument("--company",         default=None,
                        help="특정 회사만 (부분 매칭)")
    parser.add_argument("--to",              default=None,
                        help="수신 이메일 (--company와 함께 사용)")
    parser.add_argument("--recipient-name",  default="",
                        help="수신자 이름 (선택)")
    parser.add_argument("--touch",           default="D1",
                        choices=["D1", "D3", "D6", "D10"],
                        help="발송할 터치포인트 (기본: D1)")
    parser.add_argument("--send",            action="store_true",
                        help="실제 발송 (없으면 미리보기만)")
    parser.add_argument("--force",           action="store_true",
                        help="이미 발송된 건도 재발송")
    parser.add_argument("--sync-notion",     action="store_true",
                        help="발송 후 output/ PDF 링크를 Notion 해당 페이지에 반영 (NOTION_PDF_BASE_URL 필요)")
    parser.add_argument("--preview",         action="store_true",
                        help="미리보기 강제 (--send 무시)")
    parser.add_argument("--log",             action="store_true",
                        help="발송 로그 출력 후 종료")
    args = parser.parse_args()

    if args.preview:
        args.send = False

    if args.log:
        log = load_log()
        if not log:
            print("발송 로그가 없습니다.")
            return
        print(f"\n[발송 로그]  {LOG_FILE}\n")
        print(f"  {'회사':<16} {'터치':<6} {'수신':<30} {'상태':<10} {'발송일시'}")
        print(f"  {'─'*80}")
        for entry in log.values():
            print(f"  {entry['company']:<16} {entry['touch']:<6} {entry['to']:<30} "
                  f"{entry['status']:<10} {entry['sent_at']}")
        return

    run(args)


if __name__ == "__main__":
    main()
