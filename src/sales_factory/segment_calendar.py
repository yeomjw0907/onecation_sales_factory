from __future__ import annotations

import json
import uuid
from copy import deepcopy
from datetime import date, timedelta
from typing import Any

from sales_factory.runtime_db import RUNTIME_DIR, ensure_runtime_dirs, now_iso


SEGMENT_CALENDAR_PATH = RUNTIME_DIR / "segment_calendar.json"
SEND_WINDOW_SORT_ORDER = {"오전": 0, "오후": 1, "종일": 2}

SEGMENT_PRESETS: list[dict[str, Any]] = [
    {
        "id": "korea-entry-overseas",
        "label": "한국 시장 진입형 해외 기업",
        "description": "한국 고객, 셀러, 파트너, 유저 확보가 필요한 해외 기업을 공략합니다.",
        "offer": "Korea-entry landing page + local acquisition package",
        "target_roles": ["Founder", "CEO", "Head of Growth", "Marketing Director", "Business Development Lead"],
        "portfolio": [
            "Shuning: 월 가입 10 -> 100",
            "Yes Duty Free: 월 매출 3천만원 이상 확보",
        ],
        "recommended_countries": ["US", "CN", "TW", "JP", "SG"],
        "country_queries": {
            "US": "US companies expanding into Korea with weak Korean localization, landing pages, or lead capture",
            "CN": "Chinese companies entering Korea with weak localization websites and no clear Korean acquisition funnel",
            "TW": "Taiwan companies entering Korea with weak Korean localization, landing pages, or commerce conversion flow",
            "JP": "Japanese companies entering Korea with weak Korean localization and no clear lead capture structure",
            "SG": "Singapore companies entering Korea with weak Korean localization and acquisition planning",
            "default": "Overseas companies entering Korea with weak Korean localization websites and no clear acquisition funnel",
        },
        "default_country": "US",
        "default_max_companies": 10,
    },
    {
        "id": "international-student-recruitment",
        "label": "해외 학생 모집 교육기관",
        "description": "한국 포함 아시아권 학생 모집을 늘리고 싶은 대학, 로스쿨, 교육기관을 공략합니다.",
        "offer": "International student recruitment website + enrollment marketing package",
        "target_roles": ["Admissions Director", "Marketing Director", "International Programs Lead", "Dean"],
        "portfolio": [
            "Pacific American University School of Law: 홈페이지 구축 + 매 학기 학생 모집",
        ],
        "recommended_countries": ["US", "JP", "SG"],
        "country_queries": {
            "US": "US universities, law schools, and education institutes recruiting Korean or Asian students with weak admissions websites",
            "JP": "Japanese schools and education institutes recruiting international students with weak multilingual admissions websites",
            "SG": "Singapore education institutes recruiting Korean or Asian students with weak admissions funnels",
            "default": "Education institutions recruiting Korean or international students with weak admissions websites and unclear enrollment funnels",
        },
        "default_country": "US",
        "default_max_companies": 8,
    },
    {
        "id": "portfolio-institution-program",
        "label": "입주기업 다수 기관 프로그램",
        "description": "산하 입주기업, 포트폴리오사, 지원기업이 많은 대학, 공공기관, 재단을 공략합니다.",
        "offer": "Portfolio company branding and website batch program",
        "target_roles": ["Program Manager", "Startup Support Lead", "Innovation Center Director", "Public Program Operator"],
        "portfolio": [
            "국민체육진흥공단: 21개사 브랜딩/홈페이지 구축",
            "성균관대·한양대·고려대: 4년간 50개사 이상 브랜드/소개서 지원",
        ],
        "recommended_countries": ["KR", "US", "JP", "SG"],
        "country_queries": {
            "KR": "Korean universities, public institutions, and innovation centers supporting multiple resident startups that lack branding or websites",
            "US": "US universities, incubators, and innovation programs supporting startup cohorts that lack brand and website assets",
            "JP": "Japanese universities and public startup programs supporting resident companies with weak brand and website assets",
            "SG": "Singapore accelerators, universities, and public startup programs supporting portfolio companies with weak brand and website assets",
            "default": "Universities, public institutions, and startup support programs managing multiple portfolio companies that lack brand and website assets",
        },
        "default_country": "KR",
        "default_max_companies": 6,
    },
]


def list_segment_presets() -> list[dict[str, Any]]:
    return deepcopy(SEGMENT_PRESETS)


def get_segment_preset(segment_id: str) -> dict[str, Any] | None:
    return next((deepcopy(preset) for preset in SEGMENT_PRESETS if preset["id"] == segment_id), None)


def build_segment_query(segment_id: str, target_country: str) -> str:
    preset = get_segment_preset(segment_id)
    if not preset:
        return ""
    queries = preset.get("country_queries", {})
    return str(queries.get(target_country) or queries.get("default") or "").strip()


def build_segment_brief(segment_id: str, target_country: str) -> str:
    preset = get_segment_preset(segment_id)
    if not preset:
        return ""
    query = build_segment_query(segment_id, target_country)
    target_roles = ", ".join(preset.get("target_roles", []))
    portfolio = "; ".join(preset.get("portfolio", []))
    return " | ".join(
        part
        for part in [
            f"Active segment: {preset['label']}",
            f"Description: {preset['description']}",
            f"Offer: {preset['offer']}",
            f"Target roles: {target_roles}",
            f"Relevant proof: {portfolio}",
            f"Lead filter: Only keep companies that clearly match this segment and query: {query}",
        ]
        if part
    )


def load_segment_calendar_entries() -> list[dict[str, Any]]:
    ensure_runtime_dirs()
    if not SEGMENT_CALENDAR_PATH.exists():
        return []
    try:
        payload = json.loads(SEGMENT_CALENDAR_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    rows = [row for row in payload if isinstance(row, dict)]
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("schedule_date", "")),
            SEND_WINDOW_SORT_ORDER.get(str(row.get("send_window", "")), 9),
            str(row.get("segment_label", "")),
        ),
    )


def save_segment_calendar_entries(entries: list[dict[str, Any]]) -> None:
    ensure_runtime_dirs()
    ordered = sorted(
        entries,
        key=lambda row: (
            str(row.get("schedule_date", "")),
            SEND_WINDOW_SORT_ORDER.get(str(row.get("send_window", "")), 9),
            str(row.get("segment_label", "")),
        ),
    )
    SEGMENT_CALENDAR_PATH.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")


def create_segment_calendar_entry(
    *,
    schedule_date: date,
    segment_id: str,
    target_country: str,
    send_window: str,
    max_companies: int,
    notes: str,
) -> dict[str, Any]:
    preset = get_segment_preset(segment_id)
    if not preset:
        raise ValueError(f"Unknown segment preset: {segment_id}")
    timestamp = now_iso()
    return {
        "id": str(uuid.uuid4()),
        "schedule_date": schedule_date.isoformat(),
        "segment_id": segment_id,
        "segment_label": preset["label"],
        "target_country": target_country,
        "send_window": send_window,
        "max_companies": int(max_companies),
        "lead_query": build_segment_query(segment_id, target_country),
        "segment_brief": build_segment_brief(segment_id, target_country),
        "notes": notes.strip(),
        "created_at": timestamp,
        "updated_at": timestamp,
        "last_launched_at": "",
    }


def add_segment_calendar_entry(entry: dict[str, Any]) -> None:
    entries = load_segment_calendar_entries()
    entries.append(entry)
    save_segment_calendar_entries(entries)


def delete_segment_calendar_entry(entry_id: str) -> None:
    entries = [row for row in load_segment_calendar_entries() if row.get("id") != entry_id]
    save_segment_calendar_entries(entries)


def mark_segment_calendar_entry_launched(entry_id: str) -> None:
    entries = load_segment_calendar_entries()
    timestamp = now_iso()
    for row in entries:
        if row.get("id") != entry_id:
            continue
        row["last_launched_at"] = timestamp
        row["updated_at"] = timestamp
        break
    save_segment_calendar_entries(entries)


def list_segment_calendar_entries_for_date(schedule_date: date) -> list[dict[str, Any]]:
    key = schedule_date.isoformat()
    return [row for row in load_segment_calendar_entries() if row.get("schedule_date") == key]


def list_upcoming_segment_calendar_entries(days: int = 14) -> list[dict[str, Any]]:
    today = date.today()
    end_date = today + timedelta(days=max(0, days - 1))
    rows: list[dict[str, Any]] = []
    for row in load_segment_calendar_entries():
        raw_date = str(row.get("schedule_date") or "")
        try:
            row_date = date.fromisoformat(raw_date)
        except ValueError:
            continue
        if today <= row_date <= end_date:
            rows.append(row)
    return rows
