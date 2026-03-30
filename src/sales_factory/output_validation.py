from __future__ import annotations

import os
import re

PLACEHOLDER_RE = re.compile(r"\[([^\]\n]{1,80})\](?!\()")
HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
NETWORK_ASSERTION_TERMS = (
    "dns",
    "name resolution",
    "connection refused",
    "getaddrinfo",
    "tls",
    "ssl",
    "timeout",
    "timed out",
)

KNOWN_SENDER_PLACEHOLDERS = {
    "[Your Name]",
    "[your name]",
    "[Contact Name]",
    "[contact name]",
    "[あなたの名前]",
    "[あなたの氏名]",
    "[私/弊社名]",
    "[私の名前]",
    "[弊社名]",
    "[담당자 이름]",
    "[보내는 사람 이름]",
}

COMPOUND_SENDER_REPLACEMENTS = {
    "Onecationの[あなたの名前]と申します。": "Onecationと申します。",
    "Onecationの[あなたの名前]です。": "Onecationです。",
    "Onecationの[あなたの氏名]と申します。": "Onecationと申します。",
    "Onecationの[あなたの氏名]です。": "Onecationです。",
    "Onecationの[私/弊社名]と申します。": "Onecationと申します。",
    "Onecationの[私/弊社名]です。": "Onecationです。",
    "Onecationの[私の名前]と申します。": "Onecationと申します。",
    "Onecationの[私の名前]です。": "Onecationです。",
}

FOLLOW_UP_DATE_REPLACEMENTS = {
    "[first email send date]": "earlier",
    "[first outreach date]": "earlier",
    "[previous send date]": "earlier",
    "[初回メール送信日]": "先日",
    "[一次メール送信日]": "先日",
    "[첫 메일 발송일]": "이전에",
    "[이전 발송일]": "이전에",
}


def resolve_sender_name() -> str:
    return (
        os.environ.get("SALES_FACTORY_SENDER_NAME", "").strip()
        or os.environ.get("SMTP_FROM_NAME", "").strip()
        or "대표"
    )


def normalize_language_code(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized.startswith("english") or normalized in {"en", "en-us", "en-gb"}:
        return "en"
    if normalized.startswith("japanese") or normalized in {"ja", "jp"}:
        return "ja"
    if normalized.startswith("korean") or normalized in {"ko", "kr"}:
        return "ko"
    if normalized.startswith("traditional chinese") or normalized in {"zh-hant", "zh-tw", "tw"}:
        return "zh-hant"
    if normalized.startswith("simplified chinese") or normalized in {"zh-hans", "zh-cn", "cn"}:
        return "zh-hans"
    return normalized


def normalize_customer_text(text: str, *, asset_type: str) -> str:
    if asset_type != "email_sequence":
        return text

    normalized = text
    for source, replacement in COMPOUND_SENDER_REPLACEMENTS.items():
        normalized = normalized.replace(source, replacement)
    for placeholder, replacement in FOLLOW_UP_DATE_REPLACEMENTS.items():
        normalized = normalized.replace(placeholder, replacement)
    normalized = normalized.replace("先日に", "先日")
    sender_name = resolve_sender_name()
    for placeholder in KNOWN_SENDER_PLACEHOLDERS:
        normalized = normalized.replace(placeholder, sender_name)
    return normalized


def extract_unresolved_placeholders(text: str) -> list[str]:
    found = {
        match.group(1).strip()
        for match in PLACEHOLDER_RE.finditer(text)
        if match.group(0) not in KNOWN_SENDER_PLACEHOLDERS
    }
    return sorted(token for token in found if token)


def collect_validation_issues(text: str, *, asset_type: str, proposal_language: str | None) -> list[str]:
    issues: list[str] = []
    placeholders = extract_unresolved_placeholders(text)
    if placeholders:
        issues.append(f"{asset_type}: unresolved placeholders -> {', '.join(placeholders[:4])}")

    language = normalize_language_code(proposal_language)
    hangul_count = len(HANGUL_RE.findall(text))
    if language in {"en", "ja", "zh-hans", "zh-hant"} and hangul_count >= 8:
        issues.append(f"{asset_type}: unexpected Korean text detected ({hangul_count} chars)")

    lowered = text.lower()
    if asset_type in {"proposal", "email_sequence"} and any(term in lowered for term in NETWORK_ASSERTION_TERMS):
        issues.append(f"{asset_type}: audit-environment network failure is referenced in customer-facing copy")

    return issues
