from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sales_factory.delivery_manager import extract_domain, normalize_company_key
from sales_factory.output_validation import resolve_sender_name
from sales_factory.proposal_quality import evaluate_proposal_path, evaluate_proposal_text
from sales_factory.runtime_notifications import send_email_message
from sales_factory.runtime_supabase import is_render_environment, materialize_local_asset, read_asset_text

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
HIRAGANA_KATAKANA_RE = re.compile(r"[\u3040-\u30ff]")
NON_WORD_TEXT_RE = re.compile(r"[^0-9A-Za-z\u3040-\u30ff\uac00-\ud7af]+")
KOREAN_COMPANY_NAME = "주식회사 98점7도"
KOREAN_SENDER_NAME = "염정원"
KOREAN_FIXED_INTRO = f"안녕하세요, {KOREAN_COMPANY_NAME} {KOREAN_SENDER_NAME}입니다."
KOREAN_SUBJECT_PREFIX = f"[{KOREAN_COMPANY_NAME}]"
TITLE_ONLY_IDENTITIES = {
    "대표",
    "대표이사",
    "과장",
    "부장",
    "차장",
    "실장",
    "팀장",
    "매니저",
    "이사",
    "상무",
    "전무",
    "ceo",
    "director",
    "manager",
}
PUBLIC_EMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "hotmail.com",
    "outlook.com",
    "live.com",
    "msn.com",
    "yahoo.com",
    "yahoo.co.jp",
    "icloud.com",
    "me.com",
    "mac.com",
    "naver.com",
    "daum.net",
    "hanmail.net",
    "qq.com",
    "163.com",
    "proton.me",
    "protonmail.com",
}
VALID_AUTO_SEND_MODES = {"manual", "shadow", "canary", "live"}


@dataclass(frozen=True)
class AutoSendSettings:
    mode: str
    canary_email: str
    min_proposal_score: int
    require_pdf: bool
    max_items_per_run: int


@dataclass(frozen=True)
class VerifiedRecipient:
    company_name: str
    contact_raw: str
    location: str
    homepage_url: str
    homepage_domain: str
    official_email_domain: str
    verification_status: str


@dataclass(frozen=True)
class AutoSendAssessment:
    company_name: str
    mode: str
    eligible: bool
    blocked_reasons: list[str]
    proposal_score: int
    recipient_email: str
    recipient_domain: str
    expected_domain: str
    quality_label: str
    asset_presence: dict[str, bool]

    def to_metadata(self) -> dict[str, Any]:
        return asdict(self)


def parse_json_value(value: Any, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        import json

        return json.loads(value)
    except Exception:
        return fallback


def get_auto_send_settings() -> AutoSendSettings:
    raw_mode = os.environ.get("SALES_FACTORY_AUTO_SEND_MODE", "").strip().lower()
    if raw_mode:
        mode = raw_mode if raw_mode in VALID_AUTO_SEND_MODES else "manual"
    else:
        mode = "shadow" if is_render_environment() else "manual"
    return AutoSendSettings(
        mode=mode,
        canary_email=os.environ.get("SALES_FACTORY_AUTO_SEND_CANARY_EMAIL", "").strip(),
        min_proposal_score=max(0, int(os.environ.get("SALES_FACTORY_AUTO_SEND_MIN_PROPOSAL_SCORE", "85") or 85)),
        require_pdf=os.environ.get("SALES_FACTORY_AUTO_SEND_REQUIRE_PDF", "1").strip().lower() not in {"0", "false", "no"},
        max_items_per_run=max(1, int(os.environ.get("SALES_FACTORY_AUTO_SEND_MAX_ITEMS_PER_RUN", "3") or 3)),
    )


def split_pipe_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    cells = re.split(r"(?<!\\)\|", stripped)
    return [cell.replace("\\|", "|").strip() for cell in cells]


def load_verified_recipients(workspace_dir: Path) -> dict[str, VerifiedRecipient]:
    verification_path = workspace_dir / "lead_verification.md"
    if not verification_path.exists():
        return {}

    lines = verification_path.read_text(encoding="utf-8", errors="replace").splitlines()
    header_index = next((index for index, line in enumerate(lines) if line.strip().startswith("| company_name |")), -1)
    if header_index < 0 or header_index + 1 >= len(lines):
        return {}

    headers = split_pipe_row(lines[header_index])
    recipients: dict[str, VerifiedRecipient] = {}

    for line in lines[header_index + 2 :]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = split_pipe_row(line)
        if len(cells) != len(headers):
            continue
        row = dict(zip(headers, cells))
        company_name = row.get("company_name", "").strip()
        if not company_name:
            continue
        contact_raw = row.get("contact_email_or_phone", "").strip()
        homepage_url = row.get("homepage_url_if_any", "").strip()
        recipients[normalize_company_key(company_name)] = VerifiedRecipient(
            company_name=company_name,
            contact_raw=contact_raw,
            location=row.get("location", "").strip(),
            homepage_url=homepage_url,
            homepage_domain=extract_domain(homepage_url),
            official_email_domain=_resolve_official_email_domain(contact_raw, homepage_url),
            verification_status=row.get("verification_status", "").strip().lower(),
        )

    return recipients


def _resolve_official_email_domain(contact_raw: str, homepage_url: str) -> str:
    emails = extract_contact_emails(contact_raw)
    for email in emails:
        email_domain = extract_domain(email.split("@", 1)[1])
        if email_domain and email_domain not in PUBLIC_EMAIL_DOMAINS:
            return email_domain
    return extract_domain(homepage_url)


def extract_contact_emails(raw_contact: str) -> list[str]:
    seen: list[str] = []
    for match in EMAIL_RE.findall(raw_contact or ""):
        email = match.strip().lower()
        if email not in seen:
            seen.append(email)
    return seen


def select_best_recipient_email(raw_contact: str, expected_domain: str) -> tuple[str, str]:
    candidates = extract_contact_emails(raw_contact)
    if not candidates:
        return "", ""

    if expected_domain:
        for email in candidates:
            candidate_domain = extract_domain(email.split("@", 1)[1])
            if candidate_domain == expected_domain or candidate_domain.endswith(f".{expected_domain}"):
                return email, expected_domain

    email = candidates[0]
    return email, extract_domain(email.split("@", 1)[1])


def evaluate_proposal_asset(asset_row: dict[str, Any]) -> dict[str, Any]:
    asset_path = Path(asset_row["path"])
    metadata = parse_json_value(asset_row.get("metadata_json"), {})
    text = read_asset_text(asset_path, metadata)
    if text == "(file missing)":
        return evaluate_proposal_path(asset_path)
    return evaluate_proposal_text(text)


def assess_company_sendability(
    *,
    company_name: str,
    asset_rows: list[dict[str, Any]],
    validation_issues: list[str],
    verified_recipients: dict[str, VerifiedRecipient],
    settings: AutoSendSettings,
    test_mode: bool,
) -> AutoSendAssessment:
    issues = sorted(set(validation_issues))
    proposal_asset = next((row for row in asset_rows if row["asset_type"] == "proposal"), None)
    email_asset = next((row for row in asset_rows if row["asset_type"] == "email_sequence"), None)
    docx_asset = next((row for row in asset_rows if row["asset_type"] == "proposal_docx"), None)
    pdf_asset = next((row for row in asset_rows if row["asset_type"] == "proposal_pdf"), None)
    proposal_quality = evaluate_proposal_asset(proposal_asset) if proposal_asset else {
        "score": 0,
        "label": "파일 없음",
    }

    recipient_facts = verified_recipients.get(normalize_company_key(company_name))
    blocked_reasons: list[str] = []
    if issues:
        blocked_reasons.append("validation or delivery guard issues are present")
    if not proposal_asset:
        blocked_reasons.append("proposal asset is missing")
    if not email_asset:
        blocked_reasons.append("email sequence asset is missing")
    if not docx_asset:
        blocked_reasons.append("proposal docx asset is missing")
    if settings.require_pdf and not pdf_asset:
        blocked_reasons.append("proposal pdf asset is missing")
    if int(proposal_quality.get("score", 0) or 0) < settings.min_proposal_score:
        blocked_reasons.append(
            f"proposal quality score {proposal_quality.get('score', 0)} is below threshold {settings.min_proposal_score}"
        )
    if recipient_facts is None:
        blocked_reasons.append("verified recipient facts are missing")

    expected_domain = ""
    recipient_email = ""
    recipient_domain = ""
    if recipient_facts is not None:
        if recipient_facts.verification_status not in {"verified", "corrected"}:
            blocked_reasons.append("company verification status is not verified/corrected")

        expected_domain = recipient_facts.official_email_domain or recipient_facts.homepage_domain
        if not expected_domain:
            blocked_reasons.append("verified official homepage or email domain anchor is missing")

        recipient_email, recipient_domain = select_best_recipient_email(recipient_facts.contact_raw, expected_domain)
        if not recipient_email:
            blocked_reasons.append("recipient email is missing from verified contact details")
        if recipient_domain in PUBLIC_EMAIL_DOMAINS:
            blocked_reasons.append(f"recipient email domain `{recipient_domain}` is a public mailbox")
        if expected_domain and recipient_domain and recipient_domain != expected_domain and not recipient_domain.endswith(
            f".{expected_domain}"
        ):
            blocked_reasons.append(
                f"recipient email domain `{recipient_domain}` does not match verified domain `{expected_domain}`"
            )

    if settings.mode == "live" and test_mode:
        blocked_reasons.append("live auto-send is disabled while test_mode is enabled")

    return AutoSendAssessment(
        company_name=company_name,
        mode=settings.mode,
        eligible=not blocked_reasons,
        blocked_reasons=blocked_reasons,
        proposal_score=int(proposal_quality.get("score", 0) or 0),
        recipient_email=recipient_email,
        recipient_domain=recipient_domain,
        expected_domain=expected_domain,
        quality_label=str(proposal_quality.get("label", "-")),
        asset_presence={
            "proposal": proposal_asset is not None,
            "email_sequence": email_asset is not None,
            "proposal_docx": docx_asset is not None,
            "proposal_pdf": pdf_asset is not None,
        },
    )


def parse_primary_email_asset(path: Path, metadata: dict[str, Any] | None = None) -> tuple[str, str, str, str]:
    text = read_asset_text(path, metadata)
    subject = ""
    preview_line = ""
    body_lines: list[str] = []
    cta = ""
    in_primary = False
    in_body = False

    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "## Primary Outbound Email":
            in_primary = True
            in_body = False
            continue
        if in_primary and stripped.startswith("## ") and stripped != "## Primary Outbound Email":
            break
        if not in_primary:
            continue
        if stripped.startswith("- subject:"):
            subject = stripped.split(":", 1)[1].strip()
            in_body = False
            continue
        if stripped.startswith("- preview_line:"):
            preview_line = stripped.split(":", 1)[1].strip()
            in_body = False
            continue
        if stripped.startswith("- body:"):
            in_body = True
            continue
        if stripped.startswith("- cta:"):
            cta = stripped.split(":", 1)[1].strip()
            in_body = False
            continue
        if in_body:
            body_lines.append(line[4:] if line.startswith("    ") else stripped)

    body = "\n".join(body_lines).strip()
    if not subject or not body:
        raise RuntimeError(f"{path.name}에서 1차 메일을 파싱하지 못했습니다.")
    return subject, body, preview_line, cta


def detect_email_language(text: str) -> str:
    if HANGUL_RE.search(text):
        return "ko"
    if HIRAGANA_KATAKANA_RE.search(text):
        return "ja"
    return "en"


def resolve_sender_identity(language: str) -> str:
    if language == "ko":
        return KOREAN_SENDER_NAME

    sender_name = resolve_sender_name().strip()
    if sender_name and sender_name.lower() != "onecation":
        return sender_name

    return {
        "ko": "Onecation 팀",
        "ja": "Onecationチーム",
        "en": "the Onecation team",
    }.get(language, "Onecation")


def extract_proposal_direction(asset_rows: list[dict[str, Any]]) -> str:
    proposal_asset = next((row for row in asset_rows if row["asset_type"] == "proposal"), None)
    if not proposal_asset:
        return ""

    metadata = parse_json_value(proposal_asset.get("metadata_json"), {})
    text = read_asset_text(Path(proposal_asset["path"]), metadata)
    lines = text.splitlines()
    capture = False
    captured: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == "## Recommended Direction":
            capture = True
            continue
        if capture and stripped.startswith("## "):
            break
        if capture and stripped:
            captured.append(stripped)

    return " ".join(captured).strip()


def summarize_offer_summary(offer_summary: str) -> str:
    cleaned = " ".join(offer_summary.split()).strip()
    if not cleaned:
        return ""
    sentences = re.split(r"(?<=[.!?。！？])\s+", cleaned)
    return (sentences[0] if sentences else cleaned).strip()


def normalize_overlap_text(text: str) -> str:
    normalized = NON_WORD_TEXT_RE.sub(" ", text.lower())
    return " ".join(normalized.split())


def body_already_mentions_offer(body: str, offer_summary: str) -> bool:
    normalized_body = normalize_overlap_text(body)
    normalized_offer = normalize_overlap_text(offer_summary)
    if not normalized_body or not normalized_offer:
        return False
    if normalized_offer in normalized_body:
        return True

    offer_tokens = {token for token in normalized_offer.split() if len(token) >= 4}
    if not offer_tokens:
        offer_tokens = {token for token in normalized_offer.split() if len(token) >= 2}
    if not offer_tokens:
        return False

    overlap_count = sum(1 for token in offer_tokens if token in normalized_body)
    return overlap_count >= max(1, min(3, len(offer_tokens)))


def body_already_has_closing(body: str, language: str) -> bool:
    markers = {
        "ko": ("감사합니다", "검토해 주셔서 감사합니다", "회신 주시면"),
        "ja": ("ありがとうございます", "ご確認ありがとうございます", "ご返信いただければ"),
        "en": ("thank you", "thanks", "i would be glad to", "happy to walk you through"),
    }
    body_lower = body.lower()
    return any(marker.lower() in body_lower for marker in markers.get(language, ()))


def is_title_only_identity(sender_identity: str) -> bool:
    normalized = sender_identity.strip().lower()
    return normalized in TITLE_ONLY_IDENTITIES


def normalize_subject_whitespace(subject: str) -> str:
    return " ".join((subject or "").split()).strip()


def normalize_outbound_subject(subject: str, language: str) -> str:
    normalized = normalize_subject_whitespace(subject)
    if language != "ko":
        return normalized

    core = normalized
    if core.startswith(KOREAN_SUBJECT_PREFIX):
        core = core[len(KOREAN_SUBJECT_PREFIX) :].strip()
    if core.endswith("의 건"):
        core = core[: -len("의 건")].strip()
    core = core.strip(" -:|")
    return f"{KOREAN_SUBJECT_PREFIX} {core or '제안'}의 건"


def is_korean_intro_line(line: str) -> bool:
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


def enforce_fixed_intro(body: str, language: str) -> str:
    normalized = (body or "").strip()
    if language != "ko":
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
        if is_korean_intro_line(stripped):
            consumed = idx + 1
            continue
        break

    remainder = "\n".join(lines[consumed:]).strip() if consumed else normalized
    if not remainder:
        return KOREAN_FIXED_INTRO
    return f"{KOREAN_FIXED_INTRO}\n\n{remainder}"


def format_intro(language: str, sender_identity: str) -> str:
    if language == "ko":
        return KOREAN_FIXED_INTRO

    if "onecation" in sender_identity.lower():
        return {
            "ko": f"안녕하십니까, {sender_identity}입니다.",
            "ja": f"こんにちは。{sender_identity}です。",
            "en": f"Hello, this is {sender_identity}.",
        }[language]

    if is_title_only_identity(sender_identity):
        return {
            "ko": f"안녕하십니까, Onecation의 {sender_identity}입니다.",
            "ja": f"こんにちは。Onecationの{sender_identity}です。",
            "en": f"Hello, this is the {sender_identity} at Onecation.",
        }[language]

    return {
        "ko": f"안녕하십니까, Onecation의 {sender_identity}입니다.",
        "ja": f"こんにちは。Onecationの{sender_identity}です。",
        "en": f"Hello, this is {sender_identity} from Onecation.",
    }[language]


def format_signature_block(language: str, sender_identity: str, sender_email: str) -> str:
    if language == "ko":
        lines = [f"{KOREAN_SENDER_NAME} | {KOREAN_COMPANY_NAME}"]
        if sender_email:
            lines.append(sender_email)
        return "\n".join(lines)

    if not sender_identity or sender_identity.lower() == "onecation":
        first_line = "Onecation"
    elif "onecation" in sender_identity.lower():
        first_line = sender_identity
    elif is_title_only_identity(sender_identity):
        first_line = f"Onecation {sender_identity}"
    else:
        first_line = f"{sender_identity} | Onecation"

    lines = [first_line]
    if sender_email:
        lines.append(sender_email)
    return "\n".join(lines)


def compose_primary_email_body(body: str, *, cta: str, offer_summary: str) -> str:
    language = detect_email_language(body)
    sender_identity = resolve_sender_identity(language)
    sender_email = os.environ.get("SMTP_USER", "").strip()
    normalized_body = enforce_fixed_intro(body, language)

    closing_map = {
        "ko": "검토해 주셔서 감사합니다. 편하신 시간에 회신 주시면 제안 내용을 더 구체적으로 설명드리겠습니다.",
        "ja": "ご確認ありがとうございます。ご都合のよいタイミングでご返信いただければ、提案内容を詳しくご説明します。",
        "en": "Thank you for taking a look. If this is relevant, I would be glad to walk you through the proposal in more detail.",
    }

    chunks: list[str] = []
    if language != "ko" and "onecation" not in normalized_body.lower():
        chunks.append(format_intro(language, sender_identity))

    chunks.append(normalized_body)

    concise_offer_summary = summarize_offer_summary(offer_summary)
    if concise_offer_summary and not body_already_mentions_offer(normalized_body, concise_offer_summary):
        chunks.append(concise_offer_summary)

    if not body_already_has_closing(normalized_body, language):
        chunks.append(closing_map[language])

    if cta:
        chunks.append(cta)

    chunks.append(format_signature_block(language, sender_identity, sender_email))

    return "\n\n".join(part for part in chunks if part and part.strip())


def collect_primary_attachments(asset_rows: list[dict[str, Any]]) -> list[Path]:
    attachments: list[Path] = []
    candidate_found = False
    for asset_type in ("proposal_pdf", "proposal_docx"):
        asset = next((row for row in asset_rows if row["asset_type"] == asset_type), None)
        if not asset:
            continue
        candidate_found = True
        attachment_metadata = parse_json_value(asset.get("metadata_json"), {})
        attachment_path = materialize_local_asset(Path(asset["path"]), attachment_metadata)
        if attachment_path:
            attachments.append(attachment_path)
            break
    if candidate_found and not attachments:
        raise RuntimeError("제안서 첨부 파일을 실제 메일 첨부로 준비하지 못했습니다.")
    return attachments


def build_primary_email_payload(asset_rows: list[dict[str, Any]]) -> tuple[str, str, list[Path]]:
    email_asset = next((row for row in asset_rows if row["asset_type"] == "email_sequence"), None)
    if not email_asset:
        raise RuntimeError("이 패키지에는 메일 시퀀스 산출물이 없습니다.")

    email_metadata = parse_json_value(email_asset.get("metadata_json"), {})
    subject, body, _preview_line, cta = parse_primary_email_asset(Path(email_asset["path"]), email_metadata)
    language = detect_email_language(body)
    subject = normalize_outbound_subject(subject, language)
    body = compose_primary_email_body(
        body,
        cta=cta,
        offer_summary=extract_proposal_direction(asset_rows),
    )
    attachments = collect_primary_attachments(asset_rows)
    return subject, body, attachments


def execute_auto_send(
    *,
    asset_rows: list[dict[str, Any]],
    assessment: AutoSendAssessment,
    settings: AutoSendSettings,
) -> dict[str, Any]:
    subject, body, attachments = build_primary_email_payload(asset_rows)
    if settings.mode == "shadow":
        return {
            "mode": settings.mode,
            "status": "simulated",
            "recipient": assessment.recipient_email,
            "subject": subject,
            "attachments": [str(path) for path in attachments],
        }

    if settings.mode == "canary":
        if not settings.canary_email:
            raise RuntimeError("SALES_FACTORY_AUTO_SEND_CANARY_EMAIL is not configured.")
        canary_subject = f"[CANARY] {subject}"
        canary_body = (
            f"Intended recipient: {assessment.recipient_email or '(missing)'}\n"
            f"Company: {assessment.company_name}\n"
            f"Proposal score: {assessment.proposal_score}\n\n"
            f"{body}"
        )
        send_email_message(
            subject=canary_subject,
            body_text=canary_body,
            to_email=settings.canary_email,
            attachment_paths=attachments,
        )
        return {
            "mode": settings.mode,
            "status": "sent",
            "recipient": settings.canary_email,
            "intended_recipient": assessment.recipient_email,
            "subject": canary_subject,
            "attachments": [str(path) for path in attachments],
        }

    if settings.mode == "live":
        send_email_message(
            subject=subject,
            body_text=body,
            to_email=assessment.recipient_email,
            attachment_paths=attachments,
        )
        return {
            "mode": settings.mode,
            "status": "sent",
            "recipient": assessment.recipient_email,
            "subject": subject,
            "attachments": [str(path) for path in attachments],
        }

    return {
        "mode": settings.mode,
        "status": "skipped",
        "recipient": assessment.recipient_email,
        "subject": subject,
        "attachments": [str(path) for path in attachments],
    }
