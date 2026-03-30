from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


US_STATE_ALIASES = {
    "AL": "alabama",
    "AK": "alaska",
    "AZ": "arizona",
    "AR": "arkansas",
    "CA": "california",
    "CO": "colorado",
    "CT": "connecticut",
    "DE": "delaware",
    "FL": "florida",
    "GA": "georgia",
    "HI": "hawaii",
    "ID": "idaho",
    "IL": "illinois",
    "IN": "indiana",
    "IA": "iowa",
    "KS": "kansas",
    "KY": "kentucky",
    "LA": "louisiana",
    "ME": "maine",
    "MD": "maryland",
    "MA": "massachusetts",
    "MI": "michigan",
    "MN": "minnesota",
    "MS": "mississippi",
    "MO": "missouri",
    "MT": "montana",
    "NE": "nebraska",
    "NV": "nevada",
    "NH": "new hampshire",
    "NJ": "new jersey",
    "NM": "new mexico",
    "NY": "new york",
    "NC": "north carolina",
    "ND": "north dakota",
    "OH": "ohio",
    "OK": "oklahoma",
    "OR": "oregon",
    "PA": "pennsylvania",
    "RI": "rhode island",
    "SC": "south carolina",
    "SD": "south dakota",
    "TN": "tennessee",
    "TX": "texas",
    "UT": "utah",
    "VT": "vermont",
    "VA": "virginia",
    "WA": "washington",
    "WV": "west virginia",
    "WI": "wisconsin",
    "WY": "wyoming",
}

US_REGION_ALIAS_TO_STATE = {
    "san francisco bay area": "CA",
    "bay area": "CA",
    "silicon valley": "CA",
    "greater boston area": "MA",
    "greater boston": "MA",
    "boston area": "MA",
    "metro detroit": "MI",
    "detroit metro": "MI",
    "new york city": "NY",
    "nyc": "NY",
    "long island city": "NY",
    "queens": "NY",
    "rochester": "NY",
    "troy": "MI",
}

AUDIT_UNCERTAINTY_TERMS = (
    "could not be verified",
    "could not verify",
    "review environment",
    "audit environment",
    "prevent scraping",
    "temporary website access issue",
    "technical issues that prevent scraping",
    "temporarily inaccessible",
    "temporarily unavailable",
    "inaccessible from our audit environment",
    "完全な検証を行うことができませんでした",
    "監査環境",
    "レビュー環境",
    "一時的",
    "검증을 완료할 수 없",
    "감사 환경",
    "검토 환경",
)

VERIFIED_FUNCTIONAL_TERMS = (
    "website is otherwise functional",
    "functional website",
    "well-maintained google business profile",
    "responsive website",
    "website that lists services",
    "サイトは機能している",
    "ウェブサイトは機能している",
    "사이트는 정상적으로 동작",
)

ABSOLUTE_WEBSITE_ASSERTION_TERMS = (
    "has no website",
    "no website",
    "website is unreachable",
    "website is currently unreachable",
    "website is inaccessible",
    "currently inaccessible",
    "non-functional website",
    "non-functional",
    "site is down",
    "dead link",
    "online information is inaccessible",
    "アクセス不能",
    "到達できません",
    "サイトがダウン",
    "웹사이트가 없다",
    "웹사이트가 다운",
    "접속 불가",
    "접근할 수 없",
)

URL_RE = re.compile(r"https?://[^\s)>\]]+")


@dataclass(frozen=True)
class VerifiedCompanyFacts:
    company_name: str
    location: str
    homepage_url: str
    homepage_domain: str
    verification_status: str
    verification_notes: str


def normalize_company_key(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"\s*\([^)]*\)", "", text)
    text = re.sub(r"\s*（[^）]*）", "", text)
    text = re.sub(r"[^\w\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+", "", text)
    return text


def split_pipe_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    cells = re.split(r"(?<!\\)\|", stripped)
    return [cell.replace("\\|", "|").strip() for cell in cells]


def extract_domain(url: str) -> str:
    if not url:
        return ""
    candidate = url.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    domain = (parsed.netloc or parsed.path.split("/", 1)[0]).lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def load_verified_company_facts(workspace_dir: Path) -> dict[str, VerifiedCompanyFacts]:
    verification_path = workspace_dir / "lead_verification.md"
    if not verification_path.exists():
        return {}

    lines = verification_path.read_text(encoding="utf-8", errors="replace").splitlines()
    header_index = next((index for index, line in enumerate(lines) if line.strip().startswith("| company_name |")), -1)
    if header_index < 0 or header_index + 1 >= len(lines):
        return {}

    headers = split_pipe_row(lines[header_index])
    facts: dict[str, VerifiedCompanyFacts] = {}

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
        facts[normalize_company_key(company_name)] = VerifiedCompanyFacts(
            company_name=company_name,
            location=row.get("location", "").strip(),
            homepage_url=row.get("homepage_url_if_any", "").strip(),
            homepage_domain=extract_domain(row.get("homepage_url_if_any", "")),
            verification_status=row.get("verification_status", "").strip().lower(),
            verification_notes=row.get("verification_notes", "").strip(),
        )

    return facts


def detect_allowed_us_states(location: str) -> set[str]:
    location_lower = location.lower()
    if not re.search(r"\b(usa|u\.s\.a\.|united states|us|u\.s\.)\b", location_lower):
        return set()
    allowed: set[str] = set()
    for code, name in US_STATE_ALIASES.items():
        if re.search(rf"(?:,\s*|\(\s*){re.escape(code.lower())}(?:\b|\s*\))", location_lower) or re.search(
            rf"\b{re.escape(name)}\b",
            location_lower,
        ):
            allowed.add(code)
    return allowed


def detect_us_state_mentions(text: str) -> set[str]:
    mentioned: set[str] = set()
    for code, name in US_STATE_ALIASES.items():
        if re.search(
            rf"(?:,\s*|\(\s*){re.escape(code)}(?=(?:\s*(?:,|\)|$|US\b|USA\b|United States\b)))",
            text,
        ) or re.search(
            rf"\b{re.escape(name)}\b",
            text,
            flags=re.IGNORECASE,
        ):
            mentioned.add(code)
    return mentioned


def detect_us_region_alias_mentions(text: str) -> dict[str, str]:
    lowered = text.lower()
    mentions: dict[str, str] = {}
    for alias, state_code in US_REGION_ALIAS_TO_STATE.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            mentions[alias] = state_code
    return mentions


def collect_location_drift_issues(text: str, facts: VerifiedCompanyFacts) -> list[str]:
    issues: list[str] = []
    allowed_states = detect_allowed_us_states(facts.location)
    if not allowed_states:
        return issues

    mentioned_states = detect_us_state_mentions(text)
    unexpected_states = sorted(code for code in mentioned_states if code not in allowed_states)
    if unexpected_states:
        issues.append(
            f"customer copy: geographic mismatch detected; verified location is `{facts.location}` but output mentions state(s) {', '.join(unexpected_states)}"
        )

    region_alias_mentions = detect_us_region_alias_mentions(text)
    unexpected_aliases = sorted(
        alias for alias, state_code in region_alias_mentions.items() if state_code not in allowed_states
    )
    if unexpected_aliases:
        issues.append(
            f"customer copy: geographic mismatch detected; verified location is `{facts.location}` but output references other metro area(s) {', '.join(unexpected_aliases)}"
        )
    return issues


def collect_website_claim_issues(text: str, facts: VerifiedCompanyFacts) -> list[str]:
    verification_notes = facts.verification_notes.lower()
    lowered_text = text.lower()
    has_hard_claim = any(term in lowered_text for term in ABSOLUTE_WEBSITE_ASSERTION_TERMS)
    if not has_hard_claim:
        return []
    if any(term in verification_notes for term in VERIFIED_FUNCTIONAL_TERMS):
        return [
            "customer copy: verified-functional website status was contradicted by a hard failure claim"
        ]
    if any(term in verification_notes for term in AUDIT_UNCERTAINTY_TERMS):
        if any(term in lowered_text for term in AUDIT_UNCERTAINTY_TERMS):
            return []
        return [
            "customer copy: audit uncertainty was converted into a hard website failure claim"
        ]
    return []


def collect_domain_mismatch_issues(text: str, facts: VerifiedCompanyFacts) -> list[str]:
    if not facts.homepage_domain:
        return []
    mentioned_domains = {
        extract_domain(match.group(0))
        for match in URL_RE.finditer(text)
    }
    mentioned_domains.discard("")
    if not mentioned_domains:
        return []
    if facts.homepage_domain in mentioned_domains:
        return []
    return [
        f"customer copy: verified homepage domain `{facts.homepage_domain}` is missing from referenced URLs"
    ]


def collect_delivery_guard_issues(
    text: str,
    *,
    asset_type: str,
    facts: VerifiedCompanyFacts | None,
) -> list[str]:
    if asset_type not in {"proposal", "email_sequence"} or facts is None:
        return []

    issues: list[str] = []
    issues.extend(collect_website_claim_issues(text, facts))
    issues.extend(collect_location_drift_issues(text, facts))
    issues.extend(collect_domain_mismatch_issues(text, facts))
    return issues
