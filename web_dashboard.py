from __future__ import annotations

import base64
import html
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from types import SimpleNamespace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    import streamlit as st
except ImportError:
    print("streamlit is required. Install it first.")
    sys.exit(1)

from sales_factory.proposal_quality import evaluate_proposal_path, evaluate_proposal_text
from sales_factory.auto_delivery import build_primary_email_payload, get_auto_send_settings
from sales_factory.runtime_assets import route_rejection
from sales_factory.runtime_copilot import answer_ops_question
from sales_factory.segment_calendar import (
    add_segment_calendar_entry,
    create_segment_calendar_entry,
    delete_segment_calendar_entry,
    get_segment_preset,
    list_segment_calendar_entries_for_date,
    list_segment_presets,
    list_upcoming_segment_calendar_entries,
    mark_segment_calendar_entry_launched,
)
from sales_factory.slack_review import prime_slack_review_handlers
from sales_factory.runtime_db import (
    DB_PATH,
    PROJECT_ROOT,
    describe_runtime_backend,
    get_run,
    init_db,
    list_approval_items as db_list_approval_items,
    list_assets as db_list_assets,
    list_assets_by_ids,
    list_notifications as db_list_notifications,
    list_runs as db_list_runs,
    list_tasks as db_list_tasks,
    query_running_run as db_query_running_run,
    mark_stale_runs,
    now_iso,
    record_notification,
    summarize_approval_items,
    update_approval_item,
    update_run,
)
from sales_factory.runtime_notifications import load_env_file, send_email_message
from sales_factory.runtime_supabase import (
    is_render_environment,
    materialize_local_asset,
    read_asset_bytes,
    read_asset_text,
)
from sales_factory.strategy_runtime import build_strategy_snapshot

COUNTRIES = ["KR", "US", "JP", "TW", "SG", "CN", "AE"]
COUNTRY_LABELS = {
    "KR": "한국",
    "US": "미국",
    "JP": "일본",
    "TW": "대만",
    "SG": "싱가포르",
    "CN": "중국",
    "AE": "두바이 / UAE",
}
COUNTRY_DEFAULTS = {
    "KR": {
        "proposal_language": "Korean",
        "currency": "KRW",
        "lead_query": "서울 인쇄, 패키지, 제조 업체 중 홈페이지가 오래됐거나 업데이트가 멈춘 업체",
    },
    "US": {
        "proposal_language": "English",
        "currency": "USD",
        "lead_query": "California printing companies with outdated websites",
    },
    "JP": {
        "proposal_language": "Japanese",
        "currency": "JPY",
        "lead_query": "Tokyo printing companies with outdated websites",
    },
    "TW": {
        "proposal_language": "Traditional Chinese",
        "currency": "TWD",
        "lead_query": "Taipei printing or packaging companies with outdated websites",
    },
    "SG": {
        "proposal_language": "English",
        "currency": "SGD",
        "lead_query": "Singapore printing or packaging companies with outdated websites",
    },
    "CN": {
        "proposal_language": "Simplified Chinese",
        "currency": "CNY",
        "lead_query": "Shanghai printing or packaging companies with outdated websites",
    },
    "AE": {
        "proposal_language": "English",
        "currency": "AED",
        "lead_query": "Dubai printing or packaging companies with outdated websites",
    },
}
ALERT_EMAIL_DEFAULT = os.environ.get("ALERT_EMAIL_TO", "")
KOREAN_WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
PIPELINE_LOG_DIR = PROJECT_ROOT / ".runtime" / "logs"
PIPELINE_BASELINE_PATH = PROJECT_ROOT / ".runtime" / "pipeline_baselines.json"
DEFAULT_PIPELINE_BASELINES_MINUTES = {
    "lead_research_task": 6,
    "identity_disambiguation_task": 4,
    "lead_verification_task": 4,
    "website_audit_task": 6,
    "competitor_analysis_task": 7,
    "landing_page_task": 5,
    "marketing_recommendation_task": 5,
    "proposal_task": 8,
    "proposal_localization_task": 5,
    "email_outreach_task": 4,
    "email_localization_task": 4,
    "notion_logging_task": 2,
    "review_station": 8,
}

LEAD_MODE_LABELS = {
    "region_or_industry": "지역 / 업종 기준",
    "company_name": "회사명 지정",
}
RUN_STATUS_LABELS = {
    "running": "실행 중",
    "waiting_approval": "검토 대기",
    "completed": "완료",
    "auto_sent": "자동 발송됨",
    "failed": "실패",
    "approved": "승인됨",
    "rejected": "반려됨",
    "pending": "대기 중",
    "simulated": "시뮬레이션",
    "blocked": "차단됨",
    "sent": "발송됨",
}
TASK_NAME_LABELS = {
    "lead_research_task": "회사 탐색",
    "identity_disambiguation_task": "동명이회사 식별",
    "lead_verification_task": "회사 검증",
    "website_audit_task": "홈페이지 진단",
    "competitor_analysis_task": "시장 / 경쟁 분석",
    "landing_page_task": "핵심 메시지 설계",
    "marketing_recommendation_task": "실행안 제안",
    "proposal_task": "제안서 영문 초안 작성",
    "proposal_localization_task": "제안서 현지화",
    "email_outreach_task": "메일 영문 초안 작성",
    "email_localization_task": "메일 현지화",
    "notion_logging_task": "CRM 기록",
}
ASSET_TYPE_LABELS = {
    "proposal": "제안서 원본",
    "proposal_docx": "제안서 Word",
    "proposal_pdf": "제안서 PDF",
    "email_sequence": "메일 시퀀스",
    "marketing_plan": "실행안",
    "competitor_analysis": "시장 / 경쟁 분석",
}
COPILOT_QUICK_QUESTIONS = {
    "오늘 성과": "오늘 성과 알려줘",
    "승인 대기": "지금 승인할 거 뭐 있어?",
    "오늘 비용": "오늘 비용 얼마나 썼어?",
    "다음 추천": "다음에는 뭘 하는 게 좋아?",
}
VALIDATION_ISSUE_LABELS = {
    "missing_pdf": "PDF 파일 없음",
    "missing_docx": "Word 파일 없음",
    "low_score": "제안서 품질 점수 미달",
    "missing_email": "메일 시퀀스 없음",
    "missing_proposal": "제안서 없음",
    "score_below_threshold": "품질 기준 미달",
}
AUTO_SEND_MODE_LABELS = {
    "manual": "수동 검토",
    "shadow": "그림자 모니터링",
    "canary": "카나리 테스트",
    "live": "자동 발송",
}

OUTBOUND_NOTIFICATION_KIND_LABELS = {
    "auto_delivery": "자동 발송",
    "test_outbound_email": "테스트 발송",
}

REVIEW_NOTE_TEMPLATES: list[tuple[str, str]] = [
    ("성과 보강", "성과 근거와 실제 수치를 더 보강해 주세요. Why us와 핵심 제안 근거가 약합니다."),
    ("가격 정리", "가격과 범위 표현을 더 명확하게 정리해 주세요. 제공 범위가 한눈에 보여야 합니다."),
    ("메일 톤 조정", "메일 제목과 본문 톤을 더 간결하고 자연스럽게 다듬어 주세요. 첫 문장 압축이 필요합니다."),
    ("현지화 수정", "현지 시장 표현과 업계 문맥을 더 자연스럽게 맞춰 주세요. 번역투 표현을 줄여야 합니다."),
]

STRATEGY_BIAS_LABELS = {
    "general_digital_recovery": "기본 디지털 회복형",
    "korea_entry_specialist": "한국 진출 특화형",
    "diaspora_business_support": "해외 한인 사업자 지원형",
    "maintenance_recovery": "유지관리 회복형",
    "trust_rebuild_b2b": "B2B 신뢰 회복형",
}
DEPARTMENT_CONFIG = {
    "lead_research_task": {
        "department": "시장 탐색부",
        "summary": "승률이 높은 패턴을 고르고 실제 회사 후보를 찾습니다.",
        "support": ["패턴 탐색팀", "기회 선별팀"],
    },
    "identity_disambiguation_task": {
        "department": "회사 식별부",
        "summary": "동명이회사 후보를 주소, 전화, 이메일 도메인, 홈페이지로 대조해 정확한 회사를 하나로 좁힙니다.",
        "support": ["회사 검증부"],
    },
    "lead_verification_task": {
        "department": "회사 검증부",
        "summary": "회사 실체, 공식 홈페이지, 공개 정보가 서로 맞는지 교차 검증합니다.",
        "support": [],
    },
    "website_audit_task": {
        "department": "디지털 진단부",
        "summary": "홈페이지 신뢰도, 최신성, 문의 흐름을 진단합니다.",
        "support": [],
    },
    "competitor_analysis_task": {
        "department": "시장 전략 분석부",
        "summary": "시장 맥락과 경쟁사 비교 포인트를 정리합니다.",
        "support": [],
    },
    "landing_page_task": {
        "department": "핵심 메시지 설계부",
        "summary": "강점과 차별점을 고객이 이해하기 쉬운 언어로 재구성합니다.",
        "support": [],
    },
    "marketing_recommendation_task": {
        "department": "실행안 제안부",
        "summary": "국가와 업종에 맞는 실행 채널과 우선순위를 제안합니다.",
        "support": [],
    },
    "proposal_task": {
        "department": "제안서 초안부",
        "summary": "사실과 논리를 기준으로 영문 canonical 제안서 초안을 만듭니다.",
        "support": [],
    },
    "proposal_localization_task": {
        "department": "제안서 현지화부",
        "summary": "고객이 읽는 제안서를 목표 국가 문체로 자연스럽게 현지화합니다.",
        "support": ["품질 검토팀"],
    },
    "email_outreach_task": {
        "department": "메일 초안부",
        "summary": "구조가 안정적인 영문 canonical 아웃바운드 메일 초안을 만듭니다.",
        "support": [],
    },
    "email_localization_task": {
        "department": "메일 현지화부",
        "summary": "발송 직전 메일 문안을 현지 세일즈 톤으로 다듬습니다.",
        "support": [],
    },
}
CREW_MEMBER_CONFIG = {
    "lead_research_task": {
        "name": "강민준 대리",
        "crew_label": "lead_research_task",
        "role": "대상 국가에서 실제로 칠 회사를 찾고 탐색 기준을 정리합니다.",
        "vision": "우리에게 유리한 시장부터 정확하게 찾습니다.",
    },
    "identity_disambiguation_task": {
        "name": "정서윤 과장",
        "crew_label": "identity_disambiguation_task",
        "role": "동명이회사 후보를 주소, 연락처, 도메인 기준으로 대조해 정확한 회사만 남깁니다.",
        "vision": "비슷한 이름에 속지 않고 정확한 회사만 다음 단계로 넘깁니다.",
    },
    "lead_verification_task": {
        "name": "윤지후 과장",
        "crew_label": "lead_verification_task",
        "role": "회사 실체, 공식 홈페이지, 공개 정보가 같은 대상을 가리키는지 검증합니다.",
        "vision": "잘못 붙은 회사 정보가 뒤 단계로 퍼지기 전에 끊어냅니다.",
    },
    "market_pattern_finder": {
        "name": "송재민 과장",
        "crew_label": "market_pattern_finder",
        "role": "국가별로 승률이 높은 공략 패턴을 먼저 뽑습니다.",
        "vision": "감이 아니라 패턴으로 먼저 시장을 좁힙니다.",
    },
    "opportunity_selector": {
        "name": "김다온 대리",
        "crew_label": "opportunity_selector",
        "role": "유망 패턴 중 먼저 칠 타깃과 우선순위를 고릅니다.",
        "vision": "많이 찾는 것보다 잘 팔리는 곳을 먼저 고릅니다.",
    },
    "website_audit_task": {
        "name": "윤서현 사원",
        "crew_label": "website_audit_task",
        "role": "홈페이지 노후도, 신뢰 요소, 문의 흐름, 업데이트 상태를 진단합니다.",
        "vision": "사이트에서 놓치고 있는 신뢰의 틈을 먼저 발견합니다.",
    },
    "competitor_analysis_task": {
        "name": "박도윤 대리",
        "crew_label": "competitor_analysis_task",
        "role": "시장 맥락과 경쟁사 비교, 고객이 반응할 포인트를 분석합니다.",
        "vision": "시장 흐름을 읽고, 이길 수 있는 비교 구도를 만듭니다.",
    },
    "market_localization": {
        "name": "신하은 사원",
        "crew_label": "market_localization",
        "role": "국가별 문화와 어필 포인트를 정리해 제안서 톤을 다듬습니다.",
        "vision": "같은 제안도 나라에 맞게 말해야 먹힙니다.",
    },
    "landing_page_task": {
        "name": "한지우 대리",
        "crew_label": "landing_page_task",
        "role": "회사의 강점과 기회를 전달 메시지와 구조로 번역합니다.",
        "vision": "좋은 회사를 바로 이해되는 메시지로 바꿉니다.",
    },
    "marketing_recommendation_task": {
        "name": "최서준 과장",
        "crew_label": "marketing_recommendation_task",
        "role": "국가와 업종에 맞는 실행안, 채널 우선순위, 오퍼 방향을 제안합니다.",
        "vision": "예쁜 계획보다 실제로 먹히는 실행안을 남깁니다.",
    },
    "market_strategy_crew": {
        "name": "문태오 팀장",
        "crew_label": "market_strategy_crew",
        "role": "국가·세그먼트·오퍼 전략을 상위 관점에서 정리합니다.",
        "vision": "실행 전에 판을 어떻게 깔지 먼저 결정합니다.",
    },
    "proposal_task": {
        "name": "이현우 차장",
        "crew_label": "proposal_task",
        "role": "사실과 제안 논리를 기준으로 영문 canonical 제안서 초안을 작성합니다.",
        "vision": "번역 전에 구조와 사업 논리가 흔들리지 않는 초안을 만듭니다.",
    },
    "proposal_localization_task": {
        "name": "사야카 리드",
        "crew_label": "proposal_localization_task",
        "role": "초안을 고객 시장의 언어와 문체로 자연스럽게 현지화합니다.",
        "vision": "번역투 문장이 아니라 현지 영업 문서처럼 읽히게 만듭니다.",
    },
    "proposal_quality_reviewer": {
        "name": "배수빈 사원",
        "crew_label": "proposal_quality_reviewer",
        "role": "제안서 품질을 점수화하고 빠진 섹션을 짚습니다.",
        "vision": "나가기 전에 약한 문서를 먼저 걸러냅니다.",
    },
    "email_outreach_task": {
        "name": "정유진 대리",
        "crew_label": "email_outreach_task",
        "role": "구조가 안정적인 영문 canonical 메일 초안을 작성합니다.",
        "vision": "후반 현지화가 쉬운 메일 뼈대를 먼저 만듭니다.",
    },
    "email_localization_task": {
        "name": "에리카 매니저",
        "crew_label": "email_localization_task",
        "role": "메일 초안을 현지 세일즈 문체로 다듬고 발송용 톤으로 정리합니다.",
        "vision": "템플릿 냄새 없이 자연스럽고 답장받기 쉬운 문장으로 바꿉니다.",
    },
    "response_classifier": {
        "name": "임서윤 사원",
        "crew_label": "response_classifier",
        "role": "답장을 읽고 긍정·거절·미팅 요청 신호로 분류합니다.",
        "vision": "답장도 데이터로 남겨 다음 판단에 연결합니다.",
    },
}
DEPARTMENT_CREW_MEMBERS = {
    "lead_research_task": ["lead_research_task", "market_pattern_finder", "opportunity_selector"],
    "identity_disambiguation_task": ["identity_disambiguation_task"],
    "lead_verification_task": ["lead_verification_task"],
    "website_audit_task": ["website_audit_task"],
    "competitor_analysis_task": ["competitor_analysis_task", "market_localization"],
    "landing_page_task": ["landing_page_task"],
    "marketing_recommendation_task": ["marketing_recommendation_task", "market_strategy_crew"],
    "proposal_task": ["proposal_task"],
    "proposal_localization_task": ["proposal_localization_task", "proposal_quality_reviewer"],
    "email_outreach_task": ["email_outreach_task"],
    "email_localization_task": ["email_localization_task", "response_classifier"],
}
SUPPORT_TEAM_CONFIG = [
    {
        "department": "검토 운영본부",
        "status": "현재 운영 중",
        "members": [
            ("오세훈 과장", "외부 발송 전에 사람이 꼭 봐야 하는 산출물만 검토 대기로 올립니다."),
            ("남예린 대리", "반려 사유를 읽고 어느 부서를 다시 돌릴지 정리합니다."),
        ],
    },
    {
        "department": "전략 지원본부",
        "status": "부분 반영",
        "members": [
            ("송재민 과장", "국가별로 승률이 높은 공략 패턴을 정리합니다."),
            ("김다온 대리", "유망 패턴 중 실제로 먼저 칠 대상을 고릅니다."),
            ("배수빈 사원", "제안서 품질을 점수화하고 보완 포인트를 짚습니다."),
        ],
    },
    {
        "department": "후속 대응본부",
        "status": "준비 중",
        "members": [
            ("신하은 사원", "답장 메일을 읽고 긍정/거절/미팅 요청으로 분류합니다."),
            ("문태오 팀장", "답장 반응과 제안서 품질을 보고 다음 전략을 추천합니다."),
        ],
    },
]


def get_crew_member_profile(member_key: str | None) -> dict[str, str]:
    profile = CREW_MEMBER_CONFIG.get(member_key or "", {})
    return {
        "name": profile.get("name", "-"),
        "crew_label": profile.get("crew_label", member_key or "-"),
        "role": profile.get("role", "-"),
        "vision": profile.get("vision", "-"),
    }


def get_department_members(task_name: str | None) -> list[dict[str, str]]:
    member_keys = DEPARTMENT_CREW_MEMBERS.get(task_name or "", [])
    if not member_keys and task_name:
        member_keys = [task_name]
    return [get_crew_member_profile(member_key) for member_key in member_keys]


def parse_json_field(value: Any, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def display_status(value: str | None) -> str:
    if not value:
        return "-"
    return RUN_STATUS_LABELS.get(value, value)


def summarize_auto_delivery(metadata: dict[str, Any] | None) -> str:
    payload = parse_json_field((metadata or {}).get("auto_delivery"), {})
    if not payload:
        return "판정 없음"
    eligible = bool(payload.get("eligible"))
    mode = payload.get("mode") or "manual"
    reasons = payload.get("blocked_reasons") or []
    mode_label = display_delivery_mode(str(mode))
    if eligible:
        return f"{mode_label} 가능"
    if reasons:
        return f"{mode_label} 차단: {reasons[0]}"
    return f"{mode_label} 차단"


def summarize_run_auto_delivery(run_row: dict[str, Any] | None) -> dict[str, Any]:
    metadata = parse_json_field(run_row.get("metadata_json") if run_row else None, {})
    return parse_json_field(metadata.get("auto_delivery_summary"), {})


def display_delivery_mode(value: str | None) -> str:
    return AUTO_SEND_MODE_LABELS.get(str(value or "manual"), "수동 검토")


def display_storage_status(backend_info: dict[str, Any] | None) -> str:
    backend = str((backend_info or {}).get("backend") or "")
    if backend == "supabase":
        return "원격 저장 정상"
    return "로컬 저장 중"


def get_run_metadata(run_row: dict[str, Any] | None) -> dict[str, Any]:
    return parse_json_field(run_row.get("metadata_json") if run_row else None, {})


def get_run_inputs(run_row: dict[str, Any] | None) -> dict[str, Any]:
    return parse_json_field(run_row.get("inputs_json") if run_row else None, {})


def get_run_segment_label(run_row: dict[str, Any] | None) -> str:
    inputs = get_run_inputs(run_row)
    metadata = get_run_metadata(run_row)
    if inputs.get("segment_label"):
        return str(inputs["segment_label"])
    if metadata.get("segment_label"):
        return str(metadata["segment_label"])
    if metadata.get("auto_mode"):
        return "자동 패턴 추천"
    return "수동/일반 실행"


def infer_run_focus_task_name(run_row: dict[str, Any] | None, tasks: list[dict[str, Any]] | None = None) -> str | None:
    current_task = str((run_row or {}).get("current_task") or "").strip()
    if current_task:
        return current_task

    ordered_tasks = sorted(tasks or [], key=lambda row: int(row.get("task_order") or 0))
    for status in ("running", "failed", "waiting_approval", "pending"):
        matched = next((row for row in ordered_tasks if row.get("status") == status), None)
        if matched and matched.get("task_name"):
            return str(matched["task_name"])

    if ordered_tasks and ordered_tasks[-1].get("task_name"):
        return str(ordered_tasks[-1]["task_name"])
    return None


def summarize_asset_rows(asset_rows: list[dict[str, Any]]) -> dict[str, int]:
    company_count = len({str(row.get("company_name") or "").strip() for row in asset_rows if row.get("company_name")})
    proposal_count = sum(1 for row in asset_rows if row.get("asset_type") == "proposal")
    pdf_count = sum(1 for row in asset_rows if row.get("asset_type") == "proposal_pdf")
    today_count = len(filter_rows_by_date(asset_rows, "created_at", date.today()))
    return {
        "asset_count": len(asset_rows),
        "company_count": company_count,
        "proposal_count": proposal_count,
        "pdf_count": pdf_count,
        "today_count": today_count,
    }


def get_auto_refresh_interval_seconds(
    *,
    running_run: dict[str, Any] | None,
    latest_run: dict[str, Any] | None,
    enabled: bool,
) -> int | None:
    if not enabled:
        return None
    if running_run:
        return 4
    if latest_run and str(latest_run.get("status") or "") == "waiting_approval":
        return None
    return None


def format_reroute_targets(value: Any) -> str:
    targets = parse_json_field(value, [])
    if not targets:
        return "-"
    if not isinstance(targets, list):
        targets = [targets]
    labels = [display_task_name(str(item)) for item in targets if str(item).strip()]
    return ", ".join(labels) if labels else "-"


def is_urgent_approval_item(item: dict[str, Any]) -> bool:
    metadata = parse_json_field(item.get("metadata_json"), {})
    auto_delivery = parse_json_field(metadata.get("auto_delivery"), {})
    validation_issues = metadata.get("validation_issues") or []
    blocked_reasons = auto_delivery.get("blocked_reasons") or []
    return int(item.get("priority", 0) or 0) >= 2 or bool(validation_issues) or bool(blocked_reasons)


def summarize_run_issue(run_row: dict[str, Any] | None, tasks: list[dict[str, Any]] | None = None) -> dict[str, str] | None:
    if not run_row:
        return None

    status = str(run_row.get("status") or "")
    error_message = str(run_row.get("error_message") or "").strip()
    lowered_error = error_message.lower()
    focus_task_name = infer_run_focus_task_name(run_row, tasks)
    waiting_count = int(run_row.get("approval_count", 0) or 0)
    waiting_items_count = waiting_count

    if status in {"waiting_approval", "rejected"} and not waiting_items_count and run_row.get("id"):
        waiting_items_count = len([item for item in list_approval_items("waiting_approval") if item.get("run_id") == run_row.get("id")])

    if status == "waiting_approval":
        if waiting_items_count <= 0:
            return {
                "severity": "warning",
                "title": "검토 대기 누락",
                "summary": "상태는 검토 대기인데 실제 승인 항목이 연결되지 않았습니다.",
                "action": "실행 로그를 확인하고 산출물/검토 큐를 다시 맞춘 뒤 재실행하세요.",
                "raw_error": error_message,
            }
        return {
            "severity": "warning",
            "title": "사람 검토 대기",
            "summary": f"지금 사람이 판단해야 할 항목이 {waiting_items_count}건 남아 있습니다.",
            "action": "검토 대기 탭에서 승인하거나 보완 요청을 처리하세요.",
            "raw_error": error_message,
        }

    if status != "failed":
        return None

    if any(keyword in lowered_error for keyword in ("503", "overloaded", "temporarily overloaded", "retrying transient llm failure")):
        return {
            "severity": "error",
            "title": "LLM 재시도 초과",
            "summary": "모델 과부하 또는 일시 오류가 계속되어 자동 재시도 후에도 완료하지 못했습니다.",
            "action": "잠시 후 다시 실행하거나 대상 수를 줄여서 다시 시도하세요.",
            "raw_error": error_message,
        }
    if "slack" in lowered_error and any(keyword in lowered_error for keyword in ("socket", "connection", "timeout", "handshake")):
        return {
            "severity": "error",
            "title": "Slack 연결 지연",
            "summary": "Slack 버튼 또는 알림 연결이 제때 붙지 않아 흐름이 멈췄습니다.",
            "action": "Slack 연결 상태를 확인한 뒤 다시 실행하세요.",
            "raw_error": error_message,
        }
    if any(
        keyword in lowered_error
        for keyword in (
            "lead verification rejected every company",
            "manual review is required before proposal generation",
            "rejected every company",
            "no verified company",
        )
    ):
        return {
            "severity": "error",
            "title": "리드 없음",
            "summary": "검증을 통과한 회사가 없어 제안서 단계로 넘어가지 못했습니다.",
            "action": "탐색 조건을 넓히거나 세그먼트/국가를 바꿔 다시 실행하세요.",
            "raw_error": error_message,
        }
    if "approval" in lowered_error and any(keyword in lowered_error for keyword in ("missing", "queue", "review")):
        return {
            "severity": "error",
            "title": "검토 대기 누락",
            "summary": "승인 단계로 이어지는 검토 항목을 만들지 못해 흐름이 끊겼습니다.",
            "action": "산출물과 검토 대기 탭을 확인한 뒤 다시 실행하세요.",
            "raw_error": error_message,
        }
    if any(keyword in lowered_error for keyword in ("stale", "heartbeat")):
        return {
            "severity": "error",
            "title": "실행이 오래 멈춤",
            "summary": "하트비트가 끊겨 시스템이 실행을 자동 실패 처리했습니다.",
            "action": "네트워크나 배포 상태를 확인한 뒤 다시 실행하세요.",
            "raw_error": error_message,
        }

    stage_label = display_task_name(focus_task_name) if focus_task_name else "실행"
    return {
        "severity": "error",
        "title": f"{stage_label} 실패",
        "summary": f"{stage_label} 단계에서 예외가 발생해 실행이 중단되었습니다.",
        "action": "실행 로그를 열어 마지막 단계와 오류 메시지를 확인한 뒤 다시 실행하세요.",
        "raw_error": error_message,
    }


def render_run_issue_banner(issue: dict[str, str]) -> None:
    palette = {
        "error": {
            "bg": "var(--sf-panel)",
            "border": "#ef4444",
            "badge_bg": "#fff1f2",
            "badge_text": "#b91c1c",
            "shadow": "0 0 0 4px rgba(239,68,68,0.10), 0 18px 38px rgba(239,68,68,0.08)",
        },
        "warning": {
            "bg": "var(--sf-panel)",
            "border": "#f59e0b",
            "badge_bg": "#fffbeb",
            "badge_text": "#b45309",
            "shadow": "0 0 0 4px rgba(245,158,11,0.10), 0 18px 38px rgba(245,158,11,0.08)",
        },
        "info": {
            "bg": "var(--sf-panel)",
            "border": "#60a5fa",
            "badge_bg": "#eff6ff",
            "badge_text": "#2563eb",
            "shadow": "0 0 0 4px rgba(96,165,250,0.10), 0 18px 38px rgba(96,165,250,0.08)",
        },
        "success": {
            "bg": "var(--sf-panel)",
            "border": "#22c55e",
            "badge_bg": "#f0fdf4",
            "badge_text": "#15803d",
            "shadow": "0 0 0 4px rgba(34,197,94,0.10), 0 18px 38px rgba(34,197,94,0.08)",
        },
    }.get(
        issue.get("severity") or "info",
        {
            "bg": "var(--sf-panel)",
            "border": "#60a5fa",
            "badge_bg": "#eff6ff",
            "badge_text": "#2563eb",
            "shadow": "0 0 0 4px rgba(96,165,250,0.10), 0 18px 38px rgba(96,165,250,0.08)",
        },
    )
    badge_label = {
        "error": "즉시 확인",
        "warning": "확인 필요",
        "info": "진행 중",
        "success": "완료",
    }.get(issue.get("severity") or "info", "안내")

    st.markdown(
        f"""
        <div style="border:1px solid {palette['border']};border-radius:16px;background:{palette['bg']};
        box-shadow:{palette['shadow']};padding:16px 18px;margin:6px 0 14px 0;color:var(--sf-text);">
            <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;">
                <div style="font-size:18px;font-weight:800;line-height:1.25;">{html.escape(issue.get('title') or '상태 요약')}</div>
                <span style="display:inline-flex;align-items:center;padding:4px 10px;border-radius:999px;
                background:{palette['badge_bg']};color:{palette['badge_text']};font-size:12px;font-weight:800;">
                    {html.escape(badge_label)}
                </span>
            </div>
            <div style="font-size:13px;color:var(--sf-muted);line-height:1.6;margin-top:8px;">{html.escape(issue.get('summary') or '-')}</div>
            <div style="font-size:13px;font-weight:700;color:var(--sf-text);line-height:1.6;margin-top:10px;">
                지금 할 일: {html.escape(issue.get('action') or '-')}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def display_task_name(value: str | None) -> str:
    if not value:
        return "-"
    return TASK_NAME_LABELS.get(value, value)


def display_asset_type(value: str | None) -> str:
    if not value:
        return "-"
    return ASSET_TYPE_LABELS.get(value, value)


def display_country(value: str | None) -> str:
    if not value:
        return "-"
    return COUNTRY_LABELS.get(value, value)


def display_strategy_bias(value: str | None) -> str:
    if not value:
        return "-"
    return STRATEGY_BIAS_LABELS.get(value, value)


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat((value or "")[:10])
        except ValueError:
            return None


def format_local_date(value: date | None) -> str:
    if not value:
        return "-"
    return f"{value.isoformat()} ({KOREAN_WEEKDAYS[value.weekday()]})"


def format_local_datetime(value: str | None) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return f"{dt.strftime('%m-%d %H:%M')} ({KOREAN_WEEKDAYS[dt.weekday()]})"
    except ValueError:
        return value[:16] if value else "-"


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def format_duration_compact(seconds: float | int | None) -> str:
    if seconds is None:
        return "-"
    total_seconds = max(0, int(round(float(seconds))))
    if total_seconds < 60:
        return f"{total_seconds}초"
    minutes, remaining_seconds = divmod(total_seconds, 60)
    hours, remaining_minutes = divmod(minutes, 60)
    if hours:
        if remaining_minutes:
            return f"{hours}시간 {remaining_minutes}분"
        return f"{hours}시간"
    if remaining_seconds and minutes < 10:
        return f"{minutes}분 {remaining_seconds}초"
    return f"{minutes}분"


def filter_rows_by_date(rows: list[dict[str, Any]], field: str, selected_date: date | None) -> list[dict[str, Any]]:
    if not selected_date:
        return rows
    filtered: list[dict[str, Any]] = []
    for row in rows:
        row_date = parse_iso_date(row.get(field))
        if row_date == selected_date:
            filtered.append(row)
    return filtered


def resolve_python_executable() -> str:
    local_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if local_python.exists():
        return str(local_python)
    return sys.executable


def load_runtime() -> None:
    load_env_file()
    init_db()
    mark_stale_runs()
    prime_slack_review_handlers()


def query_running_run() -> dict[str, Any] | None:
    return db_query_running_run()


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    return db_list_runs(limit=limit)


def list_tasks(run_id: str) -> list[dict[str, Any]]:
    return db_list_tasks(run_id)


def list_assets(run_id: str | None = None) -> list[dict[str, Any]]:
    return db_list_assets(run_id)


def list_approval_items(status: str | None = None) -> list[dict[str, Any]]:
    return db_list_approval_items(status)


def load_approval_assets(item: dict[str, Any]) -> list[dict[str, Any]]:
    bundle_ids = parse_json_field(item.get("asset_bundle_json"), [])
    return list_assets_by_ids(bundle_ids)


def list_notifications(limit: int = 20) -> list[dict[str, Any]]:
    return db_list_notifications(limit=limit)


def load_pipeline_baselines() -> dict[str, int]:
    baselines = dict(DEFAULT_PIPELINE_BASELINES_MINUTES)
    if not PIPELINE_BASELINE_PATH.exists():
        return baselines
    try:
        payload = json.loads(PIPELINE_BASELINE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return baselines
    if not isinstance(payload, dict):
        return baselines
    for key, value in payload.items():
        try:
            minutes = int(value)
        except (TypeError, ValueError):
            continue
        if minutes > 0:
            baselines[str(key)] = minutes
    return baselines


def save_pipeline_baselines(baselines: dict[str, int]) -> None:
    PIPELINE_BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ordered = {key: int(baselines[key]) for key in DEFAULT_PIPELINE_BASELINES_MINUTES}
    PIPELINE_BASELINE_PATH.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")


def list_recent_runtime_logs(limit: int = 20) -> list[Path]:
    if not PIPELINE_LOG_DIR.exists():
        return []
    return sorted(PIPELINE_LOG_DIR.glob("dashboard-run-*.log"), key=lambda path: path.stat().st_mtime, reverse=True)[:limit]


def resolve_run_log_path(run_row: dict[str, Any] | None) -> Path | None:
    if not run_row:
        return None
    metadata = parse_json_field(run_row.get("metadata_json"), {})
    raw_path = str(metadata.get("log_path") or "").strip()
    if raw_path:
        path = Path(raw_path)
        if path.exists():
            return path
    recent_logs = list_recent_runtime_logs(limit=1)
    return recent_logs[0] if recent_logs else None


def read_log_tail(log_path: Path, *, max_chars: int = 12000) -> str:
    content = log_path.read_text(encoding="utf-8", errors="replace")
    return content[-max_chars:] if len(content) > max_chars else content


def render_run_log_panel(run_row: dict[str, Any] | None, *, key_prefix: str) -> None:
    st.markdown("**실행 로그**")
    if not run_row:
        st.info("연결된 실행이 없습니다.")
        return

    recent_logs = list_recent_runtime_logs(limit=10)
    linked_log = resolve_run_log_path(run_row)
    options: list[Path] = []
    if linked_log:
        options.append(linked_log)
    for candidate in recent_logs:
        if candidate not in options:
            options.append(candidate)

    if not options:
        st.info("표시할 로그 파일이 없습니다.")
        return

    default_index = 0
    selected_log_name = st.selectbox(
        "로그 파일",
        options=[path.name for path in options],
        index=default_index,
        key=f"{key_prefix}_log_file",
    )
    selected_log = next((path for path in options if path.name == selected_log_name), options[0])
    max_chars = st.select_slider(
        "표시 범위",
        options=[4000, 8000, 12000, 20000],
        value=12000,
        key=f"{key_prefix}_log_chars",
        format_func=lambda value: f"최근 {value:,}자",
    )

    try:
        content = read_log_tail(selected_log, max_chars=max_chars)
    except Exception as exc:
        st.warning(f"로그 읽기 실패: {exc}")
        return

    log_stat = selected_log.stat()
    c1, c2, c3 = st.columns([2.8, 1.1, 1.2])
    c1.caption(f"로그 파일: `{selected_log.name}`")
    c2.caption(f"수정: {format_local_datetime(datetime.fromtimestamp(log_stat.st_mtime).isoformat(timespec='seconds'))}")
    c3.caption(f"크기: {log_stat.st_size:,} bytes")
    st.code(content or "(비어있음)", language="text")


def set_ui_notice(level: str, message: str) -> None:
    st.session_state["ui_notice"] = {"level": level, "message": message}


def render_ui_notice() -> None:
    notice = st.session_state.pop("ui_notice", None)
    if not notice:
        return
    level = notice.get("level")
    message = notice.get("message") or ""
    if level == "success":
        st.success(message)
    elif level == "warning":
        st.warning(message)
    elif level == "error":
        st.error(message)
    else:
        st.info(message)


def inject_app_shell_styles() -> None:
    st.markdown(
        """
        <style>
        @import url("https://fonts.bunny.net/css?family=inter:300,400,500,600,700&display=swap");
        @import url("https://cdn.jsdelivr.net/npm/geist@1.3.0/dist/fonts/geist-mono/style.css");

        :root {
            color-scheme: light dark;
            --sf-native-bg:      var(--background-color, #0d0d0f);
            --sf-native-surface: var(--secondary-background-color, #121317);
            --sf-native-text:    var(--text-color, #f3f4f6);
            --sf-native-accent:  var(--primary-color, #3b82f6);

            --sf-bg:           var(--sf-native-bg);
            --sf-surface:      var(--sf-native-surface);
            --sf-panel:        color-mix(in srgb, var(--sf-native-surface) 88%, var(--sf-native-bg) 12%);
            --sf-panel-strong: color-mix(in srgb, var(--sf-native-surface) 92%, var(--sf-native-text) 8%);
            --sf-border:       color-mix(in srgb, var(--sf-native-text) 10%, transparent);
            --sf-border-md:    color-mix(in srgb, var(--sf-native-text) 16%, transparent);
            --sf-border-str:   color-mix(in srgb, var(--sf-native-text) 24%, transparent);
            --sf-text:         var(--sf-native-text);
            --sf-muted:        color-mix(in srgb, var(--sf-native-text) 62%, var(--sf-native-bg));
            --sf-dim:          color-mix(in srgb, var(--sf-native-text) 30%, var(--sf-native-bg));
            --sf-accent:       var(--sf-native-accent);
            --sf-accent-soft:  color-mix(in srgb, var(--sf-native-accent) 14%, transparent);
            --sf-accent-str:   color-mix(in srgb, var(--sf-native-accent) 24%, transparent);
            --sf-green:        #22c55e;
            --sf-green-soft:   color-mix(in srgb, #22c55e 12%, transparent);
            --sf-amber:        #f59e0b;
            --sf-amber-soft:   color-mix(in srgb, #f59e0b 12%, transparent);
            --sf-red:          #ef4444;
            --sf-red-soft:     color-mix(in srgb, #ef4444 12%, transparent);
            --sf-chip-bg:      color-mix(in srgb, var(--sf-native-text) 7%, transparent);
            --sf-chip-border:  color-mix(in srgb, var(--sf-native-text) 14%, transparent);
            --sf-chip-text:    color-mix(in srgb, var(--sf-native-text) 72%, var(--sf-native-bg));
            --sf-shadow:       none;
        }

        html, body, [class*="css"] {
            font-family: "Inter", system-ui, "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
            color: var(--sf-text);
            background: var(--sf-bg);
            -webkit-font-smoothing: antialiased;
        }

        .stApp {
            background: var(--sf-bg) !important;
        }

        [data-testid="stHeader"] {
            background: color-mix(in srgb, var(--sf-bg) 82%, transparent) !important;
        }

        [data-testid="stAppViewContainer"] > .main {
            background: transparent;
        }

        [data-testid="stSidebar"] {
            background: var(--sf-surface) !important;
            border-right: 1px solid var(--sf-border) !important;
        }

        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
            color: var(--sf-text);
        }

        [data-testid="stSidebar"] .stButton > button {
            border-radius: 6px;
            font-weight: 600;
            font-size: 13px;
            min-height: 36px;
        }

        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 6px;
            border-color: var(--sf-border-md);
            background: transparent;
            box-shadow: none;
        }

        div[data-testid="stMetric"] {
            background: var(--sf-panel);
            border: 1px solid var(--sf-border-md);
            border-radius: 6px;
            padding: 14px 16px;
            min-height: 92px;
        }

        div[data-testid="stMetricLabel"] {
            color: var(--sf-muted);
            font-size: 0.75rem;
            font-weight: 600;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }

        div[data-testid="stMetricValue"] {
            letter-spacing: -0.04em;
            font-weight: 700;
            font-family: "DM Sans", sans-serif;
        }

        .stTabs [data-baseweb="tab-list"] {
            gap: 0;
            border-bottom: 1px solid var(--sf-border);
            padding-bottom: 0;
            background: transparent;
        }

        .stTabs [data-baseweb="tab"] {
            height: auto;
            padding: 10px 14px 9px;
            font-weight: 500;
            font-size: 12px;
            color: var(--sf-muted);
            background: transparent !important;
        }

        .stTabs [aria-selected="true"] {
            color: var(--sf-text) !important;
            border-bottom: 2px solid var(--sf-accent) !important;
        }

        [data-testid="stExpander"] details {
            border-radius: 6px;
            border: 1px solid var(--sf-border-md);
            background: transparent;
        }

        [data-testid="stExpander"] summary p {
            font-weight: 600;
            font-size: 13px;
            color: var(--sf-text);
        }

        h1, h2, h3 {
            letter-spacing: -0.03em;
            color: var(--sf-text);
            font-family: "Inter", system-ui, sans-serif;
        }

        h1 { font-size: clamp(1.8rem, 3vw, 2.4rem); margin-bottom: 0.2rem; }
        h3 { font-size: 1.4rem; margin-top: 0.4rem; }

        code {
            font-family: "Geist Mono", "JetBrains Mono", monospace;
            color: var(--sf-accent);
            background: var(--sf-accent-soft);
            padding: 0.12rem 0.4rem;
            border-radius: 4px;
            font-size: 0.85em;
        }

        .stButton > button[kind="primary"] {
            background: var(--sf-accent);
            border: none;
            border-radius: 6px;
            font-weight: 600;
            font-size: 13px;
            letter-spacing: -0.01em;
        }

        .stButton > button[kind="secondary"] {
            background: transparent;
            border: 1px solid var(--sf-border-md);
            border-radius: 6px;
            color: var(--sf-muted);
            font-size: 12px;
        }

        .stSelectbox [data-baseweb="select"] > div,
        .stTextInput > div > div > input,
        .stTextArea > div > div > textarea,
        .stNumberInput > div > div > input {
            background: var(--sf-panel) !important;
            border-color: var(--sf-border-md) !important;
            border-radius: 6px !important;
            color: var(--sf-text) !important;
            font-size: 12px !important;
        }

        .stSlider [data-testid="stSliderThumb"] { background: var(--sf-accent) !important; }
        .stSlider [data-baseweb="slider"] > div > div { background: var(--sf-accent) !important; }

        .stCheckbox [data-testid="stCheckbox"] label span {
            font-size: 12px;
            color: var(--sf-muted);
        }

        p, li, label { color: var(--sf-text); font-size: 13px; }
        small, .stCaption { color: var(--sf-muted) !important; font-size: 11px !important; }

        [data-testid="stDataFrame"] { border-radius: 6px; overflow: hidden; }

        .sf-pill {
            display:inline-flex;
            align-items:center;
            gap:6px;
            padding:4px 10px;
            border-radius:999px;
            border:1px solid var(--sf-chip-border);
            font-size:12px;
            font-weight:600;
            white-space:nowrap;
        }

        .sf-spin-dot {
            width:10px;
            height:10px;
            border-radius:999px;
            border:2px solid currentColor;
            border-top-color: transparent;
            display:inline-block;
            animation: sf-spin 0.9s linear infinite;
        }

        .sf-row {
            display:flex;
            align-items:flex-start;
            gap:12px;
            padding:12px 10px;
            border-bottom:1px solid var(--sf-border);
        }

        .sf-row-accent {
            width:3px;
            min-width:3px;
            border-radius:999px;
            align-self:stretch;
            opacity:0.9;
        }

        .sf-row-body {
            min-width:0;
            flex:1;
        }

        .sf-row-title {
            font-size:13px;
            font-weight:600;
            color:var(--sf-text);
            line-height:1.45;
        }

        .sf-row-subtitle {
            margin-top:3px;
            font-size:12px;
            color:var(--sf-muted);
            line-height:1.45;
        }

        .sf-row-meta {
            margin-top:5px;
            font-size:11px;
            color:var(--sf-dim);
            line-height:1.45;
        }

        .sf-row-side {
            padding-top:2px;
        }

        @keyframes sf-spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def launch_background_run(
    *,
    target_country: str,
    lead_query: str,
    lead_mode: str,
    max_companies: int,
    notify_email: str,
    test_mode: bool,
    trigger_source: str = "dashboard",
    segment_id: str = "",
    segment_label: str = "",
    segment_brief: str = "",
) -> None:
    defaults = COUNTRY_DEFAULTS[target_country]
    log_dir = PROJECT_ROOT / ".runtime" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"dashboard-run-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.log"
    args = [
        resolve_python_executable(),
        "-m",
        "sales_factory.managed_run",
        "--trigger-source",
        trigger_source,
        "--target-country",
        target_country,
        "--lead-mode",
        lead_mode,
        "--lead-query",
        lead_query,
        "--max-companies",
        str(max_companies),
        "--notify-email",
        notify_email,
        "--proposal-language",
        defaults["proposal_language"],
        "--currency",
        defaults["currency"],
        "--log-path",
        str(log_path),
    ]
    if segment_id:
        args.extend(["--segment-id", segment_id])
    if segment_label:
        args.extend(["--segment-label", segment_label])
    if segment_brief:
        args.extend(["--segment-brief", segment_brief])
    if test_mode:
        args.append("--test-mode")

    if is_render_environment():
        from sales_factory.managed_run import run_managed

        run_args = SimpleNamespace(
            trigger_source=trigger_source,
            target_country=target_country,
            lead_mode=lead_mode,
            lead_query=lead_query,
            max_companies=max_companies,
            notify_email=notify_email,
            proposal_language=defaults["proposal_language"],
            currency=defaults["currency"],
            segment_id=segment_id,
            segment_label=segment_label,
            segment_brief=segment_brief,
            log_path=str(log_path),
            test_mode=test_mode,
        )

        def _run_in_background() -> None:
            with log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(f"[{datetime.now().isoformat(timespec='seconds')}] Render in-process run started\n")
                try:
                    run_managed(run_args)
                    log_file.write(f"[{datetime.now().isoformat(timespec='seconds')}] Render in-process run finished\n")
                except Exception:
                    log_file.write(traceback.format_exc())
                    log_file.flush()

        thread = threading.Thread(
            target=_run_in_background,
            name=f"managed-run-{datetime.now().strftime('%H%M%S')}",
            daemon=True,
        )
        thread.start()
        return

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{SRC_DIR}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    with log_path.open("a", encoding="utf-8") as log_file:
        subprocess.Popen(
            args,
            cwd=str(PROJECT_ROOT),
            creationflags=creationflags,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=log_file,
            close_fds=True,
        )


def finalize_run_review_state(run_id: str) -> None:
    summary = summarize_approval_items(run_id)
    waiting_count = int(summary.get("waiting_count") or 0)
    approved_count = int(summary.get("approved_count") or 0)
    rejected_count = int(summary.get("rejected_count") or 0)

    if waiting_count > 0:
        update_run(run_id, status="waiting_approval", approval_count=waiting_count)
        return

    run_row = get_run(run_id)
    metadata = parse_json_field(run_row.get("metadata_json") if run_row else None, {})
    metadata["review_summary"] = {
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "closed_at": now_iso(),
    }
    final_status = "rejected" if rejected_count else "approved"
    update_run(
        run_id,
        status=final_status,
        approval_count=0,
        metadata_json=metadata,
    )


def launch_rework_for_approval(item: dict[str, Any], reason: str) -> tuple[bool, str]:
    running = query_running_run()
    if running:
        return False, f"현재 다른 실행이 진행 중이라 재작업을 바로 시작하지 않았습니다: {running['id'][:8]}"

    source_run = get_run(item["run_id"])
    if not source_run:
        return False, "원본 실행 기록을 찾지 못해 재작업을 시작하지 못했습니다."

    company_name = (item.get("company_name") or "").strip()
    target_country = source_run.get("target_country") or "US"
    lead_query = company_name or source_run.get("lead_query") or ""
    lead_mode = "company_name" if company_name else (source_run.get("lead_mode") or "region_or_industry")
    max_companies = 1 if company_name else int(source_run.get("max_companies") or 1)
    source_metadata = parse_json_field(source_run.get("metadata_json"), {})
    notify_email = (
        source_metadata.get("notify_email")
        or st.session_state.get("alert_email_input")
        or os.environ.get("ALERT_EMAIL_TO", ALERT_EMAIL_DEFAULT)
    )

    launch_background_run(
        target_country=target_country,
        lead_query=lead_query,
        lead_mode=lead_mode,
        max_companies=max_companies,
        notify_email=notify_email,
        test_mode=bool(source_run.get("test_mode", 1)),
        trigger_source="approval_rework",
    )
    record_notification(
        item["run_id"],
        "rework_run",
        "queued",
        f"Rework queued for {company_name or target_country}",
        notify_email,
        {
            "approval_item_id": item["id"],
            "company_name": company_name,
            "reason": reason,
            "lead_mode": lead_mode,
            "lead_query": lead_query,
            "target_country": target_country,
        },
    )
    return True, f"{company_name or '선택 항목'} 재작업을 다시 시작했습니다."


def read_asset_content(path: Path, metadata: dict[str, Any] | None = None) -> str:
    if path.suffix.lower() == ".pdf":
        return "(binary pdf)"
    return read_asset_text(path, metadata)


def evaluate_proposal_asset(asset: dict[str, Any]) -> dict[str, Any]:
    path = Path(asset["path"])
    metadata = parse_json_field(asset.get("metadata_json"), {})
    text = read_asset_content(path, metadata)
    if text == "(file missing)":
        local_path = materialize_local_asset(path, metadata)
        if not local_path:
            return evaluate_proposal_path(path)
        return evaluate_proposal_path(local_path)
    return evaluate_proposal_text(text)


def get_run_strategy_snapshot(run_row: dict[str, Any] | None) -> dict[str, Any]:
    if not run_row:
        return {}
    metadata = parse_json_field(run_row.get("metadata_json"), {})
    if metadata.get("strategy_snapshot"):
        return metadata["strategy_snapshot"]
    inputs = parse_json_field(run_row.get("inputs_json"), {})
    if inputs.get("strategy_snapshot"):
        return inputs["strategy_snapshot"]
    return build_strategy_snapshot(
        target_country=run_row.get("target_country") or "US",
        lead_mode=run_row.get("lead_mode") or "region_or_industry",
        lead_query=run_row.get("lead_query") or "",
    )


def build_quality_rows(run_id: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not run_id:
        return rows

    for asset in list_assets(run_id):
        if asset["asset_type"] != "proposal":
            continue
        quality = evaluate_proposal_asset(asset)
        rows.append(
            {
                "company_name": asset.get("company_name") or "-",
                "title": asset["title"],
                "score": quality["score"],
                "label": quality["label"],
                "missing_sections": quality["missing_sections"],
                "table_count": quality["table_count"],
                "bullet_count": quality["bullet_count"],
                "path": asset["path"],
            }
        )

    return sorted(rows, key=lambda row: row["score"], reverse=True)


def quality_summary_text(quality_rows: list[dict[str, Any]]) -> str:
    if not quality_rows:
        return "평가 가능한 제안서가 아직 없습니다."
    best = quality_rows[0]
    return f"가장 점수가 높은 제안서는 {best['company_name']} ({best['score']}점, {best['label']})입니다."


def parse_primary_email_asset(path: Path, metadata: dict[str, Any] | None = None) -> tuple[str, str]:
    text = read_asset_content(path, metadata)
    subject = ""
    body_lines: list[str] = []
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
        if stripped.startswith("- body:"):
            in_body = True
            continue
        if stripped.startswith("- cta:") or stripped.startswith("- preview_line:"):
            in_body = False
            continue
        if in_body:
            body_lines.append(line[4:] if line.startswith("    ") else stripped)

    body = "\n".join(body_lines).strip()
    if not subject or not body:
        raise RuntimeError(f"{path.name}에서 1차 메일을 파싱하지 못했습니다.")
    return subject, body


def build_review_email_preview(asset_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    email_asset = next((row for row in asset_rows if row.get("asset_type") == "email_sequence"), None)
    if not email_asset:
        return None

    email_path = Path(str(email_asset["path"]))
    email_metadata = parse_json_field(email_asset.get("metadata_json"), {})

    try:
        subject, body, attachments = build_primary_email_payload(asset_rows)
        attachment_names = [path.name for path in attachments]
    except Exception:
        subject, body = parse_primary_email_asset(email_path, email_metadata)
        attachment_names = []

    return {
        "subject": subject,
        "body": body,
        "attachment_names": attachment_names,
    }


def build_downloadable_asset_payload(asset_row: dict[str, Any]) -> dict[str, Any] | None:
    asset_path = Path(str(asset_row["path"]))
    asset_metadata = parse_json_field(asset_row.get("metadata_json"), {})
    data = read_asset_bytes(asset_path, asset_metadata)
    if not data:
        return None

    mime = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".md": "text/markdown",
        ".txt": "text/plain",
    }.get(asset_path.suffix.lower(), "application/octet-stream")

    return {
        "label": f"{display_asset_type(asset_row.get('asset_type'))} 받기",
        "file_name": asset_path.name,
        "mime": mime,
        "data": data,
    }


def render_safe_download_button(
    payload: dict[str, Any],
    *,
    key: str,
    use_container_width: bool = True,
) -> None:
    kwargs = {
        "label": payload["label"],
        "data": payload["data"],
        "file_name": payload["file_name"],
        "mime": payload["mime"],
        "key": key,
        "use_container_width": use_container_width,
    }
    try:
        st.download_button(on_click="ignore", **kwargs)
    except TypeError:
        st.download_button(**kwargs)


def build_status_pill_html(
    label: str,
    *,
    tone: str = "neutral",
    spinning: bool = False,
) -> str:
    tone_map = {
        "neutral": ("var(--sf-chip-bg)", "var(--sf-chip-text)", "var(--sf-chip-border)"),
        "blue": ("var(--sf-accent-soft)", "var(--sf-accent)", "color-mix(in srgb, var(--sf-accent) 28%, transparent)"),
        "green": ("var(--sf-green-soft)", "var(--sf-green)", "color-mix(in srgb, var(--sf-green) 28%, transparent)"),
        "amber": ("var(--sf-amber-soft)", "var(--sf-amber)", "color-mix(in srgb, var(--sf-amber) 28%, transparent)"),
        "red": ("var(--sf-red-soft)", "var(--sf-red)", "color-mix(in srgb, var(--sf-red) 28%, transparent)"),
    }
    background, color, border = tone_map.get(tone, tone_map["neutral"])
    spinner = "<span class='sf-spin-dot'></span>" if spinning else ""
    return (
        f"<span class='sf-pill sf-pill--{tone}' "
        f"style='background:{background};color:{color};border-color:{border};'>"
        f"{spinner}{html.escape(label)}</span>"
    )


def render_compact_row(
    *,
    title: str,
    subtitle: str = "",
    meta: str = "",
    pill_html: str = "",
    accent_tone: str = "neutral",
) -> None:
    accent_colors = {
        "neutral": "var(--sf-border-md)",
        "blue": "var(--sf-accent)",
        "green": "var(--sf-green)",
        "amber": "var(--sf-amber)",
        "red": "var(--sf-red)",
    }
    accent = accent_colors.get(accent_tone, accent_colors["neutral"])
    subtitle_html = f"<div class='sf-row-subtitle'>{html.escape(subtitle)}</div>" if subtitle else ""
    meta_html = f"<div class='sf-row-meta'>{html.escape(meta)}</div>" if meta else ""
    st.markdown(
        f"""
        <div class="sf-row">
            <div class="sf-row-accent" style="background:{accent};"></div>
            <div class="sf-row-body">
                <div class="sf-row-title">{html.escape(title)}</div>
                {subtitle_html}
                {meta_html}
            </div>
            <div class="sf-row-side">{pill_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def build_rework_state_lookup(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    item_ids = {str(item.get("id")) for item in items if item.get("id")}
    if not item_ids:
        return {}

    latest_by_item: dict[str, dict[str, Any]] = {}
    for row in list_notifications(limit=200):
        if str(row.get("kind") or "") != "rework_run":
            continue
        metadata = parse_json_field(row.get("metadata_json"), {})
        item_id = str(metadata.get("approval_item_id") or "")
        if item_id not in item_ids:
            continue
        existing = latest_by_item.get(item_id)
        if not existing or str(row.get("created_at") or "") > str(existing.get("created_at") or ""):
            latest_by_item[item_id] = row

    running_run = query_running_run()
    running_rework = bool(running_run and str(running_run.get("trigger_source") or "").startswith("approval_rework"))
    active_item_id = ""
    if running_rework and latest_by_item:
        active_item_id = max(
            latest_by_item.items(),
            key=lambda pair: str(pair[1].get("created_at") or ""),
        )[0]

    lookup: dict[str, dict[str, Any]] = {}
    for item_id in item_ids:
        if item_id == active_item_id:
            lookup[item_id] = {"label": "재작업 중", "tone": "blue", "spinning": True}
        elif item_id in latest_by_item:
            lookup[item_id] = {"label": "재작업 요청됨", "tone": "amber", "spinning": False}
    return lookup


def tone_for_status(status: str | None) -> str:
    normalized = str(status or "").lower()
    if normalized in {"sent", "auto_sent", "running"}:
        return "blue"
    if normalized in {"approved", "completed"}:
        return "green"
    if normalized in {"waiting_approval", "queued", "pending"}:
        return "amber"
    if normalized in {"failed", "blocked", "rejected"}:
        return "red"
    return "neutral"


def render_pdf_preview(asset_row: dict[str, Any], *, key_prefix: str, height: int = 560) -> None:
    payload = build_downloadable_asset_payload(asset_row)
    if not payload:
        st.info("PDF 미리보기를 불러오지 못했습니다.")
        return

    encoded = base64.b64encode(payload["data"]).decode("ascii")
    st.markdown(
        (
            f'<iframe title="{html.escape(payload["file_name"])}" '
            f'src="data:application/pdf;base64,{encoded}" '
            f'width="100%" height="{height}" '
            'style="border:1px solid var(--sf-border-md);border-radius:12px;background:var(--sf-panel);"></iframe>'
        ),
        unsafe_allow_html=True,
    )


def build_runtime_version_info() -> dict[str, str]:
    raw_commit = (
        os.environ.get("RENDER_GIT_COMMIT")
        or os.environ.get("GIT_COMMIT")
        or os.environ.get("COMMIT_SHA")
        or ""
    ).strip()
    raw_branch = (os.environ.get("RENDER_GIT_BRANCH") or os.environ.get("GIT_BRANCH") or "").strip()

    if not raw_commit:
        try:
            raw_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        except Exception:
            raw_commit = ""

    if not raw_branch:
        try:
            raw_branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        except Exception:
            raw_branch = ""

    build_time = datetime.fromtimestamp(Path(__file__).stat().st_mtime).isoformat(timespec="seconds")
    return {
        "environment": "Render" if is_render_environment() else "Local",
        "commit": raw_commit[:7] if raw_commit else "-",
        "branch": raw_branch or "-",
        "build_time": format_local_datetime(build_time),
        "service": os.environ.get("RENDER_SERVICE_NAME", "").strip() or "-",
    }


def build_delivery_archive_rows(selected_date: date, *, limit: int = 400) -> list[dict[str, Any]]:
    notifications = filter_rows_by_date(list_notifications(limit=limit), "created_at", selected_date)
    run_cache: dict[str, dict[str, Any] | None] = {}
    rows: list[dict[str, Any]] = []

    for row in notifications:
        kind = str(row.get("kind") or "")
        if kind not in OUTBOUND_NOTIFICATION_KIND_LABELS:
            continue
        run_id = str(row.get("run_id") or "")
        if run_id not in run_cache:
            run_cache[run_id] = get_run(run_id) if run_id else None
        run_row = run_cache.get(run_id) or {}
        metadata = parse_json_field(row.get("metadata_json"), {})
        rows.append(
            {
                "created_at": row.get("created_at"),
                "status": str(row.get("status") or ""),
                "status_label": display_status(row.get("status")),
                "kind": kind,
                "kind_label": OUTBOUND_NOTIFICATION_KIND_LABELS.get(kind, kind),
                "subject": row.get("subject") or "-",
                "recipient": row.get("recipient") or "-",
                "company_name": metadata.get("company_name") or "-",
                "segment_label": get_run_segment_label(run_row),
                "country_label": display_country(run_row.get("target_country")),
                "mode": metadata.get("mode") or "-",
                "attachments": [Path(str(path)).name for path in (metadata.get("attachments") or [])],
            }
        )

    return rows


def summarize_delivery_archive(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(rows),
        "sent": sum(1 for row in rows if row.get("status") == "sent"),
        "blocked": sum(1 for row in rows if row.get("status") == "blocked"),
        "failed": sum(1 for row in rows if row.get("status") == "failed"),
        "tests": sum(1 for row in rows if row.get("kind") == "test_outbound_email"),
    }


def build_daily_delivery_rollup(*, days: int = 14, limit: int = 600) -> list[dict[str, Any]]:
    rows = [row for row in list_notifications(limit=limit) if str(row.get("kind") or "") in OUTBOUND_NOTIFICATION_KIND_LABELS]
    daily: dict[str, dict[str, Any]] = {}
    cutoff = date.today() - timedelta(days=max(0, days - 1))
    for row in rows:
        row_date = parse_iso_date(row.get("created_at"))
        if not row_date or row_date < cutoff:
            continue
        key = row_date.isoformat()
        bucket = daily.setdefault(
            key,
            {"date": row_date, "total": 0, "sent": 0, "blocked": 0, "failed": 0, "tests": 0},
        )
        bucket["total"] += 1
        if row.get("status") == "sent":
            bucket["sent"] += 1
        if row.get("status") == "blocked":
            bucket["blocked"] += 1
        if row.get("status") == "failed":
            bucket["failed"] += 1
        if row.get("kind") == "test_outbound_email":
            bucket["tests"] += 1

    return [
        {
            "날짜": format_local_date(bucket["date"]),
            "발송 기록": bucket["total"],
            "sent": bucket["sent"],
            "blocked": bucket["blocked"],
            "failed": bucket["failed"],
            "test": bucket["tests"],
        }
        for bucket in sorted(daily.values(), key=lambda item: item["date"], reverse=True)
    ]


def build_approval_item_context(item: dict[str, Any]) -> dict[str, Any]:
    metadata = parse_json_field(item.get("metadata_json"), {})
    asset_rows = load_approval_assets(item)
    proposal_asset = next((row for row in asset_rows if row.get("asset_type") == "proposal"), None)
    quality = evaluate_proposal_asset(proposal_asset) if proposal_asset else None
    run_row = get_run(str(item.get("run_id") or "")) or {}
    downloadable_assets = [row for row in asset_rows if row.get("asset_type") in {"proposal_pdf", "proposal_docx"}]
    pdf_asset = next((row for row in downloadable_assets if row.get("asset_type") == "proposal_pdf"), None)
    return {
        "item": item,
        "metadata": metadata,
        "asset_rows": asset_rows,
        "proposal_asset": proposal_asset,
        "quality": quality,
        "run_row": run_row,
        "segment_label": get_run_segment_label(run_row),
        "country_label": display_country(run_row.get("target_country")),
        "email_preview": build_review_email_preview(asset_rows),
        "downloadable_assets": downloadable_assets,
        "pdf_asset": pdf_asset,
        "validation_issues": metadata.get("validation_issues") or [],
        "auto_delivery": parse_json_field(metadata.get("auto_delivery"), {}),
        "urgent": is_urgent_approval_item(item),
        "priority": int(item.get("priority", 0) or 0),
        "quality_score": int((quality or {}).get("score", 0) or 0),
    }


def render_review_asset_preview(context: dict[str, Any], *, key_prefix: str) -> None:
    asset_rows = context["asset_rows"]
    downloadable_assets = context["downloadable_assets"]
    email_preview = context["email_preview"]

    if not asset_rows:
        st.info("연결된 산출물이 없습니다.")
        return

    st.dataframe(
        [
            {
                "종류": display_asset_type(row["asset_type"]),
                "이름": row["title"],
                "파일": Path(str(row["path"])).name,
            }
            for row in asset_rows
        ],
        hide_index=True,
        use_container_width=True,
    )

    action_cols = st.columns(2)
    with action_cols[0]:
        st.markdown("**제안서 바로 확인**")
        if downloadable_assets:
            for asset_row in downloadable_assets:
                payload = build_downloadable_asset_payload(asset_row)
                if payload:
                    render_safe_download_button(
                        payload,
                        key=f"{key_prefix}_download_{asset_row['asset_type']}",
                        use_container_width=True,
                    )
        else:
            st.caption("다운로드 가능한 제안서 파일이 없습니다.")

    with action_cols[1]:
        st.markdown("**메일 첨부 안내**")
        if email_preview and email_preview["attachment_names"]:
            st.caption(", ".join(email_preview["attachment_names"]))
        else:
            st.caption("첨부 파일 정보가 아직 없습니다.")

    pdf_asset = context.get("pdf_asset")
    if pdf_asset:
        with st.expander("PDF 미리보기", expanded=False):
            render_pdf_preview(pdf_asset, key_prefix=f"{key_prefix}_pdf")

    if email_preview:
        st.markdown("**발송 메일 미리보기**")
        st.text_input(
            "메일 제목",
            value=email_preview["subject"],
            disabled=True,
            key=f"{key_prefix}_email_subject",
        )
        st.text_area(
            "메일 본문",
            value=email_preview["body"],
            height=240,
            disabled=True,
            key=f"{key_prefix}_email_body",
        )


def render_review_action_panel(
    context: dict[str, Any],
    *,
    test_recipient: str,
    note_key: str,
    action_prefix: str,
) -> None:
    item = context["item"]
    metadata = context["metadata"]
    asset_rows = context["asset_rows"]

    st.caption("빠른 메모 템플릿")
    template_columns = st.columns(len(REVIEW_NOTE_TEMPLATES))
    for index, (label, template_text) in enumerate(REVIEW_NOTE_TEMPLATES):
        if template_columns[index].button(label, key=f"{action_prefix}_template_{index}", use_container_width=True):
            st.session_state[note_key] = template_text
            st.rerun()

    reviewer_note = st.text_area(
        "보완 / 승인 메모",
        key=note_key,
        placeholder="예: 이대로 진행 가능 / 성과 근거 더 보강 / 메일 첫 문장 압축 필요",
    )
    c1, c2, c3 = st.columns(3)

    if c1.button("테스트 메일 보내기", key=f"{action_prefix}_send_test", use_container_width=True):
        try:
            send_test_outbound_email(
                run_id=item["run_id"],
                company_name=item.get("company_name") or "",
                asset_rows=asset_rows,
                recipient=test_recipient,
            )
            st.success(f"{test_recipient}로 테스트 메일을 보냈습니다.")
        except Exception as exc:
            record_notification(
                item["run_id"],
                "test_outbound_email",
                "failed",
                f"[TEST] {item['title']}",
                test_recipient,
                {"company_name": item.get("company_name"), "error": str(exc)},
            )
            st.error(str(exc))

    if c2.button("승인", key=f"{action_prefix}_approve", use_container_width=True):
        updated_metadata = {**metadata, "reviewer_note": reviewer_note.strip()}
        update_approval_item(
            item["id"],
            status="approved",
            decided_at=now_iso(),
            metadata_json=updated_metadata,
        )
        finalize_run_review_state(item["run_id"])
        set_ui_notice("success", "승인 처리했습니다.")
        st.rerun()

    if c3.button("반려 후 재작업", key=f"{action_prefix}_reject", use_container_width=True):
        reason = reviewer_note.strip()
        if not reason:
            st.warning("반려 사유를 먼저 적어주세요.")
        else:
            reroute = route_rejection(metadata.get("asset_type", "proposal_package"), reason)
            updated_metadata = {**metadata, "reviewer_note": reason}
            update_approval_item(
                item["id"],
                status="rejected",
                decided_at=now_iso(),
                rejection_reason=reason,
                reroute_targets_json=reroute,
                metadata_json=updated_metadata,
            )
            finalize_run_review_state(item["run_id"])
            launched, message = launch_rework_for_approval(item, reason)
            set_ui_notice("success" if launched else "warning", message)
            st.rerun()


def send_test_outbound_email(
    *,
    run_id: str,
    company_name: str,
    asset_rows: list[dict[str, Any]],
    recipient: str,
) -> None:
    subject, body, attachments = build_primary_email_payload(asset_rows)

    send_email_message(
        subject=f"[TEST] {subject}",
        body_text=body,
        to_email=recipient,
        attachment_paths=attachments,
    )
    record_notification(
        run_id,
        "test_outbound_email",
        "sent",
        f"[TEST] {subject}",
        recipient,
        {
            "company_name": company_name,
            "attachments": [str(path) for path in attachments],
        },
    )


def build_pipeline_stages(tasks: list[dict[str, Any]], latest_run: dict[str, Any]) -> list[dict[str, Any]]:
    stages: list[dict[str, Any]] = []

    for index, row in enumerate(tasks, start=1):
        config = DEPARTMENT_CONFIG.get(
            row.get("task_name") or "",
            {"department": display_task_name(row.get("task_name")), "summary": "", "support": []},
        )
        members = get_department_members(row.get("task_name"))
        primary_member = members[0] if members else {"name": "-", "role": "-"}
        member_count = len(members)
        owner_label = primary_member["name"]
        if member_count > 1:
            owner_label = f"{primary_member['name']} 외 {member_count - 1}명"

        status = str(row.get("status") or "pending")
        if status == "running":
            note = f"지금 작업 중 · 토큰 {int(row.get('total_tokens', 0) or 0):,}"
        elif status == "completed":
            note = "이 단계 완료"
        elif status == "failed":
            note = latest_run.get("error_message") or "이 단계에서 멈춤"
        elif status == "waiting_approval":
            note = "산출물 검토 대기"
        else:
            note = "이전 단계 완료 후 시작"

        stages.append(
            {
                "kind": "task",
                "task_name": row.get("task_name") or "",
                "index_label": f"{index:02d}",
                "department": config["department"],
                "task_label": display_task_name(row.get("task_name")),
                "owner_label": owner_label,
                "owner_role": primary_member.get("role", "-"),
                "summary": config.get("summary") or "",
                "support": config.get("support", []),
                "status": status,
                "status_label": display_status(status),
                "note": note,
                "started_at": row.get("started_at"),
                "finished_at": row.get("finished_at"),
            }
        )

    waiting_items = [item for item in list_approval_items("waiting_approval") if item.get("run_id") == latest_run.get("id")]
    run_status = str(latest_run.get("status") or "")
    should_include_review = bool(tasks) or bool(waiting_items) or run_status in {
        "waiting_approval",
        "rejected",
        "approved",
        "auto_sent",
        "completed",
        "failed",
    }

    if should_include_review:
        if run_status in {"approved", "auto_sent", "completed"}:
            review_status = "completed"
        elif run_status in {"waiting_approval", "rejected"} or waiting_items:
            review_status = "waiting_approval"
        elif run_status == "failed" and not any(stage["status"] == "failed" for stage in stages):
            review_status = "failed"
        else:
            review_status = "pending"

        if review_status == "completed":
            review_note = "검토 및 발송 판단 완료"
        elif review_status == "waiting_approval":
            review_note = f"검토 대기 {len(waiting_items)}건"
        elif review_status == "failed":
            review_note = latest_run.get("error_message") or "검토 단계에서 멈춤"
        else:
            review_note = "산출물 생성 후 최종 검토"

        stages.append(
            {
                "kind": "review",
                "task_name": "review_station",
                "index_label": "검토",
                "department": "검토 운영본부",
                "task_label": "승인 판단 / 재작업 조정",
                "owner_label": "오세훈 과장 외 1명",
                "owner_role": "승인 판단팀",
                "summary": "승인이 필요한 산출물을 확인하고, 필요하면 재작업 방향을 바로 지시합니다.",
                "support": ["승인 판단팀", "재작업 조정팀"],
                "status": review_status,
                "status_label": display_status(review_status),
                "note": review_note,
                "started_at": min((item.get("created_at") for item in waiting_items if item.get("created_at")), default=""),
                "finished_at": latest_run.get("finished_at") if review_status == "completed" else "",
            }
        )

    return stages


def build_pipeline_timing_summary(
    stages: list[dict[str, Any]],
    latest_run: dict[str, Any],
    *,
    reference_time: datetime | None = None,
    baselines: dict[str, int] | None = None,
) -> dict[str, Any]:
    now_dt = reference_time or datetime.now()
    configured_baselines = baselines or load_pipeline_baselines()

    def duration_seconds_for(stage: dict[str, Any]) -> int | None:
        started_at = parse_iso_datetime(stage.get("started_at"))
        finished_at = parse_iso_datetime(stage.get("finished_at"))
        if started_at and finished_at:
            return max(0, int((finished_at - started_at).total_seconds()))
        if started_at and stage.get("status") in {"running", "waiting_approval", "failed"}:
            return max(0, int((now_dt - started_at).total_seconds()))
        return None

    def baseline_seconds_for(stage: dict[str, Any]) -> int:
        key = str(stage.get("task_name") or "review_station")
        minutes = int(configured_baselines.get(key) or DEFAULT_PIPELINE_BASELINES_MINUTES.get(key) or 5)
        return max(1, minutes) * 60

    completed_durations = [
        duration
        for stage in stages
        if stage.get("status") == "completed"
        for duration in [duration_seconds_for(stage)]
        if duration is not None
    ]
    average_stage_seconds = int(sum(completed_durations) / len(completed_durations)) if completed_durations else 300

    for stage in stages:
        duration_seconds = duration_seconds_for(stage)
        baseline_seconds = baseline_seconds_for(stage)
        stage["baseline_seconds"] = baseline_seconds
        stage["duration_seconds"] = duration_seconds
        if duration_seconds is None:
            stage["duration_label"] = f"예상 {format_duration_compact(baseline_seconds)}"
        elif stage.get("status") == "completed":
            stage["duration_label"] = (
                f"소요 {format_duration_compact(duration_seconds)} · 기준 {format_duration_compact(baseline_seconds)}"
            )
        elif stage.get("status") in {"running", "waiting_approval"}:
            stage["duration_label"] = (
                f"체류 {format_duration_compact(duration_seconds)} · 기준 {format_duration_compact(baseline_seconds)}"
            )
        elif stage.get("status") == "failed":
            stage["duration_label"] = (
                f"멈춘 시점 {format_duration_compact(duration_seconds)} · 기준 {format_duration_compact(baseline_seconds)}"
            )
        else:
            stage["duration_label"] = "대기 중"

    started_at = parse_iso_datetime(latest_run.get("started_at"))
    finished_at = parse_iso_datetime(latest_run.get("finished_at"))
    if started_at:
        total_elapsed_seconds = int(((finished_at or now_dt) - started_at).total_seconds())
    else:
        total_elapsed_seconds = sum(duration for duration in completed_durations if duration is not None)

    run_status = str(latest_run.get("status") or "")
    if run_status in {"completed", "approved", "auto_sent"}:
        eta_label = "완료"
        estimated_finish_label = format_local_datetime(latest_run.get("finished_at"))
    elif run_status == "failed":
        eta_label = "중단됨"
        estimated_finish_label = "-"
    else:
        remaining_seconds = 0
        for stage in stages:
            stage_status = str(stage.get("status") or "pending")
            baseline_seconds = int(stage.get("baseline_seconds") or baseline_seconds_for(stage))
            if stage_status == "pending":
                remaining_seconds += baseline_seconds
                continue
            if stage_status in {"running", "waiting_approval"}:
                elapsed = int(stage.get("duration_seconds") or 0)
                target_seconds = max(60, baseline_seconds)
                remaining_seconds += max(60, target_seconds - elapsed)

        if remaining_seconds <= 0:
            eta_label = "곧 완료"
            estimated_finish_label = format_local_datetime(now_dt.isoformat(timespec="seconds"))
        else:
            estimated_finish = now_dt + timedelta(seconds=remaining_seconds)
            eta_label = format_duration_compact(remaining_seconds)
            estimated_finish_label = format_local_datetime(estimated_finish.isoformat(timespec="seconds"))

    return {
        "elapsed_label": format_duration_compact(total_elapsed_seconds),
        "eta_label": eta_label,
        "estimated_finish_label": estimated_finish_label,
        "average_stage_label": format_duration_compact(average_stage_seconds),
        "baseline_source": configured_baselines,
    }


def summarize_pipeline_progress(stages: list[dict[str, Any]]) -> dict[str, Any]:
    if not stages:
        return {
            "current_stage": None,
            "started_count": 0,
            "completed_count": 0,
            "total_count": 0,
            "progress_percent": 0,
        }

    active_stage = next((stage for stage in stages if stage["status"] in {"running", "waiting_approval", "failed"}), None)
    if active_stage is None:
        active_stage = next((stage for stage in stages if stage["status"] == "pending"), None) or stages[-1]

    started_count = sum(1 for stage in stages if stage["status"] in {"completed", "running", "waiting_approval", "failed"})
    completed_count = sum(1 for stage in stages if stage["status"] == "completed")
    progress_percent = int(round((started_count / len(stages)) * 100))

    return {
        "current_stage": active_stage,
        "started_count": started_count,
        "completed_count": completed_count,
        "total_count": len(stages),
        "progress_percent": progress_percent,
    }


def render_pipeline_timeline(tasks: list[dict[str, Any]], latest_run: dict[str, Any]) -> None:
    stages = build_pipeline_stages(tasks, latest_run)
    if not stages:
        return

    inputs = parse_json_field(latest_run.get("inputs_json"), {})
    progress = summarize_pipeline_progress(stages)
    timing = build_pipeline_timing_summary(stages, latest_run)
    current_stage = progress["current_stage"] or {}

    status_styles = {
        "completed": {
            "card_bg": "var(--sf-panel)",
            "border": "color-mix(in srgb, var(--sf-green) 30%, transparent)",
            "dot": "var(--sf-green)",
            "chip_bg": "var(--sf-green-soft)",
            "chip_text": "var(--sf-green)",
            "connector": "color-mix(in srgb, var(--sf-green) 38%, transparent)",
            "shadow": "none",
        },
        "running": {
            "card_bg": "var(--sf-panel)",
            "border": "color-mix(in srgb, var(--sf-accent) 34%, transparent)",
            "dot": "var(--sf-accent)",
            "chip_bg": "var(--sf-accent-soft)",
            "chip_text": "var(--sf-accent)",
            "connector": "color-mix(in srgb, var(--sf-accent) 45%, transparent)",
            "shadow": "0 0 0 1px color-mix(in srgb, var(--sf-accent) 18%, transparent) inset, 0 8px 24px color-mix(in srgb, var(--sf-accent) 10%, transparent)",
        },
        "waiting_approval": {
            "card_bg": "var(--sf-panel)",
            "border": "color-mix(in srgb, var(--sf-amber) 30%, transparent)",
            "dot": "var(--sf-amber)",
            "chip_bg": "var(--sf-amber-soft)",
            "chip_text": "var(--sf-amber)",
            "connector": "color-mix(in srgb, var(--sf-amber) 34%, transparent)",
            "shadow": "none",
        },
        "failed": {
            "card_bg": "var(--sf-panel)",
            "border": "color-mix(in srgb, var(--sf-red) 28%, transparent)",
            "dot": "var(--sf-red)",
            "chip_bg": "var(--sf-red-soft)",
            "chip_text": "var(--sf-red)",
            "connector": "color-mix(in srgb, var(--sf-red) 30%, transparent)",
            "shadow": "none",
        },
        "pending": {
            "card_bg": "var(--sf-panel)",
            "border": "var(--sf-border)",
            "dot": "var(--sf-dim)",
            "chip_bg": "var(--sf-chip-bg)",
            "chip_text": "var(--sf-chip-text)",
            "connector": "var(--sf-border-md)",
            "shadow": "none",
        },
    }

    def style_for(status: str | None) -> dict[str, str]:
        return status_styles.get(status or "pending", status_styles["pending"])

    def status_chip(label: str, status: str | None) -> str:
        style = style_for(status)
        return (
            f"<span style='display:inline-flex;align-items:center;padding:2px 8px;border-radius:4px;"
            f"font-family:\"Geist Mono\",monospace;"
            f"background:{style['chip_bg']};color:{style['chip_text']};font-size:10px;font-weight:500;letter-spacing:0.03em;'>"
            f"{html.escape(label)}</span>"
        )

    current_department = current_stage.get("department") or "-"
    current_task = current_stage.get("task_label") or "-"
    current_owner = current_stage.get("owner_label") or "-"
    segment_label = inputs.get("segment_label") or "수동/일반 실행"
    st.markdown("**실행 노선도**")
    st.caption("각 역은 사업부 단위입니다. 현재 파란/노란/빨간 역이 지금 멈춰 있는 위치이고, 오른쪽으로 갈수록 다음 단계입니다.")
    st.progress(
        min(1.0, max(0.0, float(progress["progress_percent"]) / 100.0)),
        text=(
            f"현재 위치: {current_department} · {current_task} · 담당 {current_owner} | "
            f"진행 {progress['started_count']}/{progress['total_count']} 단계"
        ),
    )
    info_columns = st.columns([2.2, 1.1, 1.1, 1.1])
    info_columns[0].metric("현재 세그먼트", str(segment_label))
    info_columns[1].metric("누적 체류", timing["elapsed_label"])
    info_columns[2].metric("남은 시간", timing["eta_label"])
    info_columns[3].metric("예상 종료", timing["estimated_finish_label"])
    st.caption(f"완료된 단계 평균 소요시간: {timing['average_stage_label']}")

    stage_blocks: list[str] = []
    for index, stage in enumerate(stages):
        style = style_for(stage.get("status"))
        support_html = ""
        if stage.get("support"):
            support_html = (
                "<div style='margin-top:10px;display:flex;flex-wrap:wrap;gap:6px;'>"
                + "".join(
                    f"<span style='display:inline-flex;align-items:center;padding:4px 8px;border-radius:999px;"
                    f"background:var(--sf-chip-bg);border:1px solid var(--sf-chip-border);"
                    f"font-size:11px;font-weight:700;'>{html.escape(item)}</span>"
                    for item in stage["support"]
                )
                + "</div>"
            )

        connector_html = ""
        if index < len(stages) - 1:
            connector_color = style["connector"] if stage.get("status") in {"completed", "running", "waiting_approval", "failed"} else "var(--sf-border)"
            connector_html = (
                f"<div style='width:48px;min-width:48px;height:1px;background:{connector_color};"
                "margin:30px 0 0 8px;'></div>"
            )

        stage_blocks.append(
            f"""
            <div style="display:flex;align-items:flex-start;min-width:220px;flex:0 0 220px;">
                <div style="display:flex;flex-direction:column;align-items:center;padding-top:20px;">
                    <div style="width:8px;height:8px;border-radius:50%;background:{style['dot']};
                    box-shadow:0 0 6px {style['dot']};border:1px solid var(--sf-bg);"></div>
                    <div style="margin-top:6px;font-family:'Geist Mono',monospace;font-size:9px;
                    font-weight:500;letter-spacing:0.05em;color:var(--sf-dim);">
                        {html.escape(stage.get('index_label', str(index + 1)))}
                    </div>
                </div>
                <div style="margin-left:10px;flex:1;background:{style['card_bg']};border:1px solid {style['border']};
                box-shadow:{style['shadow']};border-radius:8px;padding:12px 14px;min-height:160px;">
                    <div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start;margin-bottom:6px;">
                        <div style="font-family:'Geist Mono',monospace;font-size:9px;font-weight:500;
                        letter-spacing:0.07em;text-transform:uppercase;
                        color:{style['dot']};opacity:0.9;">{html.escape(stage['department'])}</div>
                        {status_chip(stage['status_label'], stage.get('status'))}
                    </div>
                    <div style="font-size:15px;font-weight:600;line-height:1.25;margin-bottom:6px;letter-spacing:-0.02em;">{html.escape(stage['task_label'])}</div>
                    <div style="font-size:11px;color:var(--sf-muted);margin-bottom:6px;">{html.escape(stage['owner_label'])}</div>
                    <div style="font-size:11px;color:var(--sf-muted);line-height:1.5;">{html.escape(stage['summary'])}</div>
                    <div style="font-family:'Geist Mono',monospace;font-size:10px;color:var(--sf-dim);margin-top:8px;">{html.escape(stage.get('duration_label') or '')}</div>
                    <div style="font-size:11px;color:var(--sf-muted);margin-top:6px;line-height:1.5;">{html.escape(stage['note'])}</div>
                    {support_html}
                </div>
                {connector_html}
            </div>
            """
        )

    st.markdown(
        "<div style='overflow-x:auto;padding:8px 0 14px 0;'>"
        "<div style='display:flex;align-items:flex-start;min-width:max-content;padding:2px 2px 10px 2px;'>"
        + "".join(stage_blocks)
        + "</div></div>",
        unsafe_allow_html=True,
    )


def render_dashboard(latest_run: dict[str, Any] | None) -> None:
    st.subheader("현재 현황")

    if not latest_run:
        if st.session_state.get("run_just_launched"):
            st.info("파이프라인을 초기화하고 있습니다. 잠시 후 자동으로 갱신됩니다...")
        else:
            st.info("아직 실행 기록이 없습니다.")
        return

    st.session_state.pop("run_just_launched", None)
    tasks = list_tasks(latest_run["id"])
    focus_task_name = infer_run_focus_task_name(latest_run, tasks)
    issue = summarize_run_issue(latest_run, tasks)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("상태", display_status(latest_run.get("status")))
    c2.metric("대상 국가", display_country(latest_run.get("target_country")))
    c3.metric("검토 대기", str(latest_run.get("approval_count", 0)))
    c4.metric("토큰 사용량", f"{latest_run.get('total_tokens', 0):,}")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("현재 작업", display_task_name(focus_task_name))
    current_members = get_department_members(focus_task_name)
    current_staff = current_members[0] if current_members else {"name": "-", "crew_label": "-"}
    c6.metric("현재 담당", current_staff["name"])
    c7.metric("예상 비용", f"${float(latest_run.get('estimated_cost_usd', 0) or 0):.4f}")
    c8.metric("마지막 갱신", format_local_datetime(latest_run.get("last_heartbeat_at")))

    auto_summary = summarize_run_auto_delivery(latest_run)
    if auto_summary:
        _mode_labels = {"shadow": "그림자 모드", "canary": "카나리 모드", "live": "실제 발송", "manual": "수동"}
        _mode = _mode_labels.get(auto_summary.get("mode", "manual"), auto_summary.get("mode", "수동"))
        _parts = [f"발송 모드: {_mode}"]
        if auto_summary.get("eligible_count"):
            _parts.append(f"발송 가능 {auto_summary['eligible_count']}건")
        if auto_summary.get("shadow_simulated_count"):
            _parts.append(f"시뮬레이션 {auto_summary['shadow_simulated_count']}건")
        if auto_summary.get("canary_sent_count"):
            _parts.append(f"카나리 발송 {auto_summary['canary_sent_count']}건")
        if auto_summary.get("live_sent_count"):
            _parts.append(f"실제 발송 {auto_summary['live_sent_count']}건")
        if auto_summary.get("blocked_count"):
            _parts.append(f"차단 {auto_summary['blocked_count']}건")
        st.caption(" · ".join(_parts))

    if issue:
        render_run_issue_banner(issue)
        if issue.get("raw_error"):
            with st.expander("원문 오류 보기", expanded=False):
                st.code(issue["raw_error"], language="text")
    elif latest_run.get("status") in {"completed", "auto_sent"}:
        success_title = "자동 발송 완료" if latest_run.get("status") == "auto_sent" else "실행 완료"
        success_summary = (
            f"{display_country(latest_run.get('target_country'))} 대상 실행이 끝났고 "
            f"산출물 {summarize_asset_rows(list_assets(latest_run.get('id'))).get('asset_count', 0)}건이 준비되었습니다."
        )
        success_action = "산출물 탭에서 결과를 확인하고, 필요하면 다음 세그먼트 일정으로 이어가세요."
        render_run_issue_banner(
            {
                "severity": "success",
                "title": success_title,
                "summary": success_summary,
                "action": success_action,
            }
        )

    if not tasks:
        with st.expander("실제 실행 로그", expanded=str(latest_run.get("status") or "") in {"running", "failed"}):
            render_run_log_panel(latest_run, key_prefix=f"latest_run_log_{latest_run.get('id', 'latest')}")
        if latest_run.get("status") == "running":
            st.info("파이프라인 시작 중... 첫 번째 에이전트가 준비되면 여기에 표시됩니다.")
        return

    render_pipeline_timeline(tasks, latest_run)

    running_tasks = [t for t in tasks if t.get("status") == "running"]
    if running_tasks:
        rt = running_tasks[0]
        rt_members = get_department_members(rt.get("task_name"))
        rt_agent = rt_members[0] if rt_members else None
        agent_name = rt_agent["name"] if rt_agent else display_task_name(rt.get("task_name"))
        agent_role = rt_agent.get("role", "") if rt_agent else ""
        st.markdown(
            f"""
            <div style="border:1px solid var(--sf-accent);border-radius:14px;background:var(--sf-panel);
            box-shadow:0 0 0 4px color-mix(in srgb, var(--sf-accent) 10%, transparent), 0 18px 38px color-mix(in srgb, var(--sf-accent) 8%, transparent);
            padding:16px 20px;margin-bottom:16px;display:flex;align-items:center;gap:16px;color:var(--sf-text);">
                <div style="width:12px;height:12px;border-radius:50%;background:var(--sf-accent);
                box-shadow:0 0 0 4px color-mix(in srgb, var(--sf-accent) 18%, transparent);flex-shrink:0;"></div>
                <div>
                    <div style="font-size:11px;font-weight:800;letter-spacing:0.06em;
                    text-transform:uppercase;color:var(--sf-accent);margin-bottom:4px;">지금 일하는 에이전트</div>
                    <div style="font-size:18px;font-weight:800;line-height:1.2;">{html.escape(agent_name)}</div>
                    {f'<div style="font-size:13px;color:var(--sf-muted);margin-top:3px;">{html.escape(agent_role)}</div>' if agent_role else ""}
                    <div style="font-size:12px;color:var(--sf-muted);margin-top:4px;">
                        작업: {html.escape(display_task_name(rt.get("task_name")))} &nbsp;·&nbsp;
                        토큰: {int(rt.get("total_tokens", 0) or 0):,}
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with st.expander("지금 일하는 부서 전체 보기", expanded=False):
        render_department_board(tasks, latest_run)

    with st.expander("작업 진행표", expanded=False):
        st.dataframe(
            [
                    {
                        "순서": row["task_order"],
                        "작업": display_task_name(row["task_name"]),
                        "담당": (
                            f"{get_department_members(row.get('task_name'))[0]['name']} "
                            f"({display_task_name(get_department_members(row.get('task_name'))[0]['crew_label'])})"
                            if get_department_members(row.get("task_name"))
                            else "-"
                        ),
                        "모델": row["model_name"],
                        "상태": display_status(row["status"]),
                        "토큰": row["total_tokens"],
                    "비용(USD)": row["estimated_cost_usd"],
                }
                for row in tasks
            ],
            hide_index=True,
            use_container_width=True,
        )
    with st.expander("실제 실행 로그", expanded=str(latest_run.get("status") or "") == "running"):
        render_run_log_panel(latest_run, key_prefix=f"latest_run_log_{latest_run.get('id', 'latest')}")


def render_department_board(tasks: list[dict[str, Any]], latest_run: dict[str, Any]) -> None:
    status_palette = {
        "completed": {"bg": "var(--sf-panel)", "border": "color-mix(in srgb, var(--sf-green) 28%, transparent)",  "badge_bg": "var(--sf-green-soft)",  "badge_text": "var(--sf-green)"},
        "running":   {"bg": "var(--sf-panel)", "border": "color-mix(in srgb, var(--sf-accent) 32%, transparent)",  "badge_bg": "var(--sf-accent-soft)",  "badge_text": "var(--sf-accent)"},
        "waiting_approval": {"bg": "var(--sf-panel)", "border": "color-mix(in srgb, var(--sf-amber) 28%, transparent)", "badge_bg": "var(--sf-amber-soft)", "badge_text": "var(--sf-amber)"},
        "pending":   {"bg": "var(--sf-panel)", "border": "var(--sf-border)", "badge_bg": "var(--sf-chip-bg)", "badge_text": "var(--sf-chip-text)"},
        "failed":    {"bg": "var(--sf-panel)", "border": "color-mix(in srgb, var(--sf-red) 28%, transparent)",   "badge_bg": "var(--sf-red-soft)",   "badge_text": "var(--sf-red)"},
    }

    def palette_for(status: str | None) -> dict[str, str]:
        return status_palette.get(status or "pending", status_palette["pending"])

    def status_badge(label: str, status: str | None) -> str:
        palette = palette_for(status)
        return (
            f"<span style='display:inline-flex;align-items:center;padding:4px 10px;border-radius:999px;"
            f"background:{palette['badge_bg']};color:{palette['badge_text']};font-size:12px;font-weight:800;'>"
            f"{html.escape(label)}</span>"
        )

    def support_badges(items: list[str]) -> str:
        if not items:
            return ""
        return "".join(
            f"<span style='display:inline-flex;align-items:center;padding:2px 7px;border-radius:4px;"
            f"background:var(--sf-chip-bg);border:1px solid var(--sf-chip-border);"
            f"font-size:11px;font-weight:500;margin:0 5px 5px 0;color:var(--sf-chip-text);'>{html.escape(item)}</span>"
            for item in items
        )

    def member_lines(members: list[dict[str, str]]) -> str:
        return "".join(
            f"<div style='margin-bottom:10px;'>"
            f"<div style='font-size:13px;font-weight:800;opacity:0.95;'>{html.escape(member['name'])} "
            f"<span style='opacity:0.7;font-weight:700;'>({html.escape(member['crew_label'])})</span></div>"
            f"<div style='font-size:12px;opacity:0.82;margin-top:2px;'>맡은 역할: {html.escape(member['role'])}</div>"
            f"<div style='font-size:12px;opacity:0.72;margin-top:2px;'>한 줄 비전: {html.escape(member['vision'])}</div>"
            f"</div>"
            for member in members
        )

    st.markdown("**부서별 실행 조직도**")
    st.caption("메인 파이프라인은 부서처럼 보이고, 지원 crew는 부서 안의 지원팀으로 표시됩니다.")

    for index, row in enumerate(tasks, start=1):
        config = DEPARTMENT_CONFIG.get(
            row.get("task_name") or "",
            {"department": display_task_name(row.get("task_name")), "summary": "", "support": []},
        )
        members = get_department_members(row.get("task_name"))
        palette = palette_for(row.get("status"))
        with st.container(border=True):
            left, center, right = st.columns([0.9, 6.3, 2.0])
            with left:
                st.markdown(
                    f"""
                    <div style="width:32px;height:32px;border-radius:6px;background:{palette['bg']};
                    border:1px solid {palette['border']};display:flex;align-items:center;justify-content:center;
                    font-family:'Geist Mono',monospace;font-weight:600;font-size:12px;color:var(--sf-muted);">{index}</div>
                    """,
                    unsafe_allow_html=True,
                )
            with center:
                st.markdown(
                    f"""
                    <div style="font-family:'Geist Mono',monospace;font-size:9px;font-weight:500;
                    letter-spacing:0.07em;text-transform:uppercase;
                    color:{palette['badge_text']};margin-bottom:5px;">{html.escape(config['department'])}</div>
                    <div style="font-size:17px;font-weight:600;line-height:1.2;margin-bottom:5px;letter-spacing:-0.02em;">{html.escape(display_task_name(row.get("task_name")))}</div>
                    <div style="font-size:12px;color:var(--sf-muted);margin-bottom:8px;">{html.escape(config.get("summary") or "")}</div>
                    <div style="font-size:11px;font-weight:600;color:var(--sf-muted);margin-bottom:5px;letter-spacing:0.03em;text-transform:uppercase;">참여 직원</div>
                    {member_lines(members)}
                    <div style="font-family:'Geist Mono',monospace;font-size:10px;color:var(--sf-dim);margin-top:4px;">모델: {html.escape(row.get("model_name") or "-")}</div>
                    <div style="margin-top:8px;">{support_badges(config.get("support", []))}</div>
                    """,
                    unsafe_allow_html=True,
                )
            with right:
                st.markdown(status_badge(display_status(row.get("status")), row.get("status")), unsafe_allow_html=True)
                st.caption(f"토큰 {int(row.get('total_tokens', 0) or 0):,}")
                st.caption(f"비용 ${float(row.get('estimated_cost_usd', 0) or 0):.4f}")

        if index < len(tasks):
            st.markdown("<div style='padding:4px 0 10px 22px;color:var(--sf-muted);'>↓</div>", unsafe_allow_html=True)

    waiting_items = [item for item in list_approval_items("waiting_approval") if item.get("run_id") == latest_run.get("id")]
    approval_status = latest_run.get("status")
    if approval_status in {"waiting_approval", "rejected"} or waiting_items:
        st.markdown("<div style='padding:4px 0 10px 22px;color:var(--sf-muted);'>↓</div>", unsafe_allow_html=True)
        palette = palette_for("waiting_approval" if approval_status == "waiting_approval" else "pending")
        with st.container(border=True):
            left, center, right = st.columns([0.9, 6.3, 2.0])
            with left:
                st.markdown(
                    f"""
                    <div style="width:32px;height:32px;border-radius:6px;background:{palette['bg']};
                    border:1px solid {palette['border']};display:flex;align-items:center;justify-content:center;
                    font-family:'Geist Mono',monospace;font-weight:600;font-size:12px;color:var(--sf-amber);">S</div>
                    """,
                    unsafe_allow_html=True,
                )
            with center:
                st.markdown(
                    """
                    <div style="font-family:'Geist Mono',monospace;font-size:9px;font-weight:500;
                    letter-spacing:0.07em;text-transform:uppercase;color:var(--sf-amber);margin-bottom:5px;">검토 운영본부</div>
                    <div style="font-size:17px;font-weight:600;line-height:1.2;margin-bottom:5px;letter-spacing:-0.02em;">승인 판단 / 반려 재작업 조정</div>
                    <div style="font-size:12px;color:var(--sf-muted);margin-bottom:8px;">승인이 필요한 산출물을 확인하고, 필요한 경우 재작업 방향을 바로 지시할 수 있습니다.</div>
                    <div style="font-size:11px;font-weight:600;color:var(--sf-muted);margin-bottom:4px;">담당 직원: 오세훈 과장, 남예린 대리</div>
                    <div style="font-size:11px;color:var(--sf-muted);margin-bottom:3px;">맡은 역할: 승인 필요 항목 선별, 반려 사유 분석, 재작업 라우팅</div>
                    <div style="font-size:11px;color:var(--sf-muted);">한 줄 비전: 사람이 꼭 봐야 할 결정만 남기고, 나머지는 흐름이 끊기지 않게 이어갑니다.</div>
                    <div style="margin-top:8px;">
                        <span style='display:inline-flex;align-items:center;padding:2px 7px;border-radius:4px;background:var(--sf-chip-bg);border:1px solid var(--sf-chip-border);font-size:11px;font-weight:500;margin:0 5px 5px 0;color:var(--sf-chip-text);'>승인 판단팀</span>
                        <span style='display:inline-flex;align-items:center;padding:2px 7px;border-radius:4px;background:var(--sf-chip-bg);border:1px solid var(--sf-chip-border);font-size:11px;font-weight:500;margin:0 5px 5px 0;color:var(--sf-chip-text);'>재작업 조정팀</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with right:
                st.markdown(status_badge(display_status(approval_status), approval_status), unsafe_allow_html=True)
                st.caption(f"검토 대기 {len(waiting_items)}건")

            if not waiting_items:
                st.info("현재 이 실행에 연결된 검토 대기 항목은 없습니다.")
                return

            st.markdown("#### 지금 바로 검토할 항목")
            for item in waiting_items:
                asset_rows = load_approval_assets(item)
                proposal_asset = next((row for row in asset_rows if row["asset_type"] == "proposal"), None)
                quality = evaluate_proposal_asset(proposal_asset) if proposal_asset else None
                metadata = parse_json_field(item.get("metadata_json"), {})
                validation_issues = metadata.get("validation_issues") or []
                prompt_text = "이 산출물을 바로 승인할지, 보완 방향이 있다면 메모를 남겨주세요."
                if quality and quality.get("missing_sections"):
                    prompt_text = (
                        f"빠진 섹션이 있습니다: {', '.join(quality['missing_sections'][:3])}. "
                        "이대로 진행할지, 보완이 필요한지 판단해주세요."
                    )

                with st.expander(f"{item.get('company_name') or '-'} | {item['title']}", expanded=True):
                    top_left, top_right = st.columns([4.8, 2.2])
                    with top_left:
                        st.markdown(f"**검토 질문**: {prompt_text}")
                        if quality:
                            summary = f"제안서 품질 {quality['score']}점 ({quality['label']})"
                            if quality["missing_sections"]:
                                summary += f" | 빠진 섹션: {', '.join(quality['missing_sections'][:3])}"
                            st.caption(summary)
                    with top_right:
                        st.caption(f"우선순위 {item.get('priority', 0)}")
                        st.caption(f"생성 시각 {item.get('created_at') or '-'}")

                    if validation_issues:
                        _issue_labels = [VALIDATION_ISSUE_LABELS.get(v, v) for v in validation_issues[:3]]
                        st.warning("검토 필요: " + " · ".join(_issue_labels))

                    if asset_rows:
                        st.dataframe(
                            [
                                {
                                    "종류": display_asset_type(row["asset_type"]),
                                    "이름": row["title"],
                                    "파일 위치": row["path"],
                                }
                                for row in asset_rows
                            ],
                            hide_index=True,
                            use_container_width=True,
                        )

                    note_key = f"inline_review_note_{item['id']}"
                    reviewer_note = st.text_area(
                        "답변 / 승인 메모 / 보완 지시",
                        key=note_key,
                        placeholder="예: 이대로 진행 가능 / 가격 표현은 더 완곡하게 / 경쟁사 비교를 한 줄 더 보강",
                    )
                    c1, c2, c3 = st.columns(3)
                    if c1.button("테스트 메일 보내기", key=f"inline_send_test_{item['id']}", use_container_width=True):
                        try:
                            send_test_outbound_email(
                                run_id=item["run_id"],
                                company_name=item.get("company_name") or "",
                                asset_rows=asset_rows,
                                recipient=st.session_state.get("alert_email_input", ALERT_EMAIL_DEFAULT),
                            )
                            st.success("테스트 메일을 보냈습니다.")
                        except Exception as exc:
                            record_notification(
                                item["run_id"],
                                "test_outbound_email",
                                "failed",
                                f"[TEST] {item['title']}",
                                st.session_state.get("alert_email_input", ALERT_EMAIL_DEFAULT),
                                {"company_name": item.get("company_name"), "error": str(exc)},
                            )
                            st.error(str(exc))
                    if c2.button("이 항목 승인", key=f"inline_approve_{item['id']}", use_container_width=True):
                        updated_metadata = {**metadata, "reviewer_note": reviewer_note.strip()}
                        update_approval_item(
                            item["id"],
                            status="approved",
                            decided_at=now_iso(),
                            metadata_json=updated_metadata,
                        )
                        finalize_run_review_state(item["run_id"])
                        set_ui_notice("success", "승인 처리했습니다.")
                        st.rerun()
                    if c3.button("보완 요청", key=f"inline_reject_{item['id']}", use_container_width=True):
                        reason = reviewer_note.strip()
                        if not reason:
                            st.warning("보완 요청 사유를 먼저 적어주세요.")
                        else:
                            reroute = route_rejection(metadata.get("asset_type", "proposal_package"), reason)
                            updated_metadata = {**metadata, "reviewer_note": reason}
                            update_approval_item(
                                item["id"],
                                status="rejected",
                                decided_at=now_iso(),
                                rejection_reason=reason,
                                reroute_targets_json=reroute,
                                metadata_json=updated_metadata,
                            )
                            finalize_run_review_state(item["run_id"])
                            launched, message = launch_rework_for_approval(item, reason)
                            set_ui_notice("success" if launched else "warning", message)
                            st.rerun()


def render_adjustable_dataframe(title: str, rows: list[dict[str, Any]], key_prefix: str) -> None:
    title_col, control_col = st.columns([12, 1])
    with title_col:
        st.markdown(f"**{title}**")
    with control_col:
        with st.popover("👁", use_container_width=True):
            st.caption("표시 항목")
            index_key = f"{key_prefix}_show_index"
            if index_key not in st.session_state:
                st.session_state[index_key] = False
            st.checkbox("(index)", key=index_key)

            if rows:
                columns = list(rows[0].keys())
                for index, column_name in enumerate(columns):
                    checkbox_key = f"{key_prefix}_column_{index}"
                    if checkbox_key not in st.session_state:
                        st.session_state[checkbox_key] = True
                    st.checkbox(column_name, key=checkbox_key)

    if not rows:
        st.info("표시할 데이터가 없습니다.")
        return

    visible_columns = []
    all_columns = list(rows[0].keys())
    for index, column_name in enumerate(all_columns):
        if st.session_state.get(f"{key_prefix}_column_{index}", True):
            visible_columns.append(column_name)

    if not visible_columns:
        visible_columns = all_columns[:1]

    filtered_rows = [{column_name: row.get(column_name) for column_name in visible_columns} for row in rows]
    st.dataframe(
        filtered_rows,
        hide_index=not st.session_state.get(f"{key_prefix}_show_index", False),
        use_container_width=True,
    )


def render_strategy_tab(
    *,
    preview_strategy: dict[str, Any],
    selected_country: str,
    latest_run: dict[str, Any] | None,
) -> None:
    st.subheader("오늘의 전략")
    today_value = date.today()
    selected_patterns = preview_strategy.get("selected_patterns", [])
    latest_inputs = parse_json_field(latest_run.get("inputs_json"), {}) if latest_run else {}
    current_segment = latest_inputs.get("segment_label") or ("자동 패턴 추천" if preview_strategy.get("auto_mode") else "수동 타겟팅")
    execution_mode = "자동 모드" if preview_strategy.get("auto_mode") else "수동 모드"

    top_left, top_center, top_right = st.columns([1.1, 1.1, 1.6])
    with top_left:
        with st.container(border=True):
            st.markdown("##### 실행 요약")
            st.caption("오늘 바로 보는 핵심 설정")
            st.metric("대상 국가", f"{display_country(selected_country)} ({selected_country})")
            st.caption(f"기준 날짜: {format_local_date(today_value)}")
            st.caption(f"실행 방식: {execution_mode}")
    with top_center:
        with st.container(border=True):
            st.markdown("##### 공략 방향")
            st.metric("세그먼트/바이어스", str(current_segment))
            st.caption(f"전략 편향: {display_strategy_bias(preview_strategy.get('strategy_bias'))}")
            st.caption(f"선택 패턴: {len(selected_patterns)}개")
    with top_right:
        with st.container(border=True):
            st.markdown("##### 이번 실행 한 줄 해석")
            if preview_strategy.get("auto_mode"):
                st.write(
                    "탐색 조건이 비어 있어 시스템이 자동으로 공략 패턴을 고른 상태입니다. "
                    "이번 런은 아래 쿼리를 기준으로 첫 리드 풀을 만드는 데 집중합니다."
                )
            else:
                st.write(
                    "직접 입력한 탐색 조건을 우선으로 사용합니다. "
                    "아래 쿼리를 그대로 기준 삼아 같은 결의 회사만 찾도록 움직입니다."
                )
            st.markdown(f"**실제 탐색 기준**  \n`{preview_strategy.get('resolved_query', '-')}`")

    if selected_patterns:
        with st.expander("자동으로 선택된 공략 패턴", expanded=False):
            render_adjustable_dataframe(
                "자동으로 선택된 공략 패턴",
                [
                    {
                        "패턴": row["pattern_name"],
                        "추천 업종": ", ".join(row["target_industries"]),
                        "우리가 유리한 이유": row["why_we_can_win"],
                        "추천 오퍼": row["offer_fit"],
                        "우선순위": row["priority_score"],
                    }
                    for row in selected_patterns
                ],
                "strategy_patterns",
            )

    if not latest_run:
        return

    if latest_inputs.get("segment_label"):
        st.info(
            f"최근 실행 세그먼트: **{latest_inputs.get('segment_label')}** | "
            f"국가: **{display_country(latest_run.get('target_country'))}**"
        )

    strategy_snapshot = get_run_strategy_snapshot(latest_run)
    quality_rows = build_quality_rows(latest_run["id"])

    st.caption(
        f"최근 실행 기준 쿼리: `{strategy_snapshot.get('resolved_query') or latest_run.get('lead_query') or '-'}`"
    )
    st.caption(quality_summary_text(quality_rows))

    if quality_rows:
        with st.expander("최근 실행 전략 로그", expanded=False):
            render_adjustable_dataframe(
                "최근 실행 전략 로그",
                [
                    {
                        "회사명": row["company_name"],
                        "점수": row["score"],
                        "등급": row["label"],
                        "빠진 섹션": ", ".join(row["missing_sections"][:3]) if row["missing_sections"] else "-",
                    }
                    for row in quality_rows
                ],
                "strategy_quality",
            )


def render_segment_calendar_tab(*, notify_email: str, test_mode: bool) -> None:
    st.subheader("세그먼트 캘린더")
    st.caption("세그먼트별 발송 계획을 날짜에 배치하고, 그 일정으로 바로 런을 시작할 수 있습니다.")

    presets = list_segment_presets()
    preset_lookup = {preset["id"]: preset for preset in presets}

    for preset in presets:
        preset_title = (
            f"{preset['label']} | "
            f"{', '.join(display_country(code) for code in preset['recommended_countries'])} | "
            f"리드 목표 {preset.get('default_max_companies', '-')}"
        )
        with st.expander(preset_title, expanded=False):
            st.write(preset["description"])
            st.write(f"오퍼: `{preset['offer']}`")
            st.write(f"추천 국가: {', '.join(display_country(code) for code in preset['recommended_countries'])}")
            st.write(f"대상 직책: {', '.join(preset['target_roles'])}")
            st.write("대표 포트폴리오")
            for portfolio_row in preset["portfolio"]:
                st.markdown(f"- {portfolio_row}")

    st.markdown("#### 일정 추가")
    with st.form("segment_calendar_form", clear_on_submit=False):
        schedule_date = st.date_input("캘린더 날짜", value=date.today(), key="segment_calendar_form_date")
        segment_id = st.selectbox(
            "세그먼트",
            options=[preset["id"] for preset in presets],
            format_func=lambda value: preset_lookup[value]["label"],
            key="segment_calendar_form_segment",
        )
        selected_preset = preset_lookup[segment_id]
        recommended_countries = selected_preset.get("recommended_countries") or COUNTRIES
        default_country = selected_preset.get("default_country") or recommended_countries[0]
        target_country = st.selectbox(
            "대상 국가",
            options=recommended_countries,
            index=max(0, recommended_countries.index(default_country)) if default_country in recommended_countries else 0,
            format_func=lambda code: f"{display_country(code)} ({code})",
            key="segment_calendar_form_country",
        )
        send_window = st.selectbox("발송 슬롯", options=["오전", "오후", "종일"], key="segment_calendar_form_window")
        max_companies = st.number_input(
            "신규 리드 목표",
            min_value=1,
            max_value=50,
            value=int(selected_preset.get("default_max_companies") or 10),
            step=1,
            key="segment_calendar_form_max_companies",
        )
        notes = st.text_area("운영 메모", height=90, key="segment_calendar_form_notes")
        preview_query = selected_preset.get("country_queries", {}).get(target_country) or selected_preset.get("country_queries", {}).get("default") or ""
        st.caption(f"이 세그먼트로 실행할 탐색 쿼리: `{preview_query}`")
        submitted = st.form_submit_button("일정 저장", use_container_width=True)

    if submitted:
        entry = create_segment_calendar_entry(
            schedule_date=schedule_date,
            segment_id=segment_id,
            target_country=target_country,
            send_window=send_window,
            max_companies=int(max_companies),
            notes=notes,
        )
        add_segment_calendar_entry(entry)
        set_ui_notice("success", f"{format_local_date(schedule_date)} 일정에 `{entry['segment_label']}` 세그먼트를 추가했습니다.")
        st.rerun()

    st.markdown("#### 일정 보기")
    selected_date = st.date_input("일정 확인 날짜", value=date.today(), key="segment_calendar_view_date")
    selected_rows = list_segment_calendar_entries_for_date(selected_date)
    if not selected_rows:
        st.caption(f"{format_local_date(selected_date)}에는 등록된 세그먼트 일정이 없습니다.")
    else:
        for row in selected_rows:
            preset = get_segment_preset(str(row.get("segment_id") or ""))
            row_title = (
                f"{row.get('segment_label', '-')} | "
                f"{display_country(row.get('target_country'))} ({row.get('target_country')}) | "
                f"{row.get('send_window')} | 목표 {row.get('max_companies')}"
            )
            with st.expander(row_title, expanded=False):
                if preset:
                    st.write(f"오퍼: `{preset['offer']}`")
                st.write(f"신규 리드 목표: `{row.get('max_companies')}`")
                st.write(f"탐색 쿼리: `{row.get('lead_query') or '-'}`")
                if row.get("notes"):
                    st.write(f"메모: {row['notes']}")
                if row.get("last_launched_at"):
                    st.caption(f"마지막 실행: {format_local_datetime(row.get('last_launched_at'))}")

                action_left, action_right = st.columns([1.4, 1.0])
                with action_left:
                    if st.button("이 일정으로 실행", key=f"segment_calendar_launch_{row['id']}", use_container_width=True):
                        launch_background_run(
                            target_country=str(row.get("target_country") or "US"),
                            lead_query=str(row.get("lead_query") or ""),
                            lead_mode="region_or_industry",
                            max_companies=int(row.get("max_companies") or 10),
                            notify_email=notify_email,
                            test_mode=test_mode,
                            trigger_source="segment_calendar",
                            segment_id=str(row.get("segment_id") or ""),
                            segment_label=str(row.get("segment_label") or ""),
                            segment_brief=str(row.get("segment_brief") or ""),
                        )
                        mark_segment_calendar_entry_launched(str(row["id"]))
                        set_ui_notice("success", f"`{row.get('segment_label')}` 일정으로 런을 시작했습니다.")
                        st.rerun()
                with action_right:
                    if st.button("일정 삭제", key=f"segment_calendar_delete_{row['id']}", use_container_width=True):
                        delete_segment_calendar_entry(str(row["id"]))
                        set_ui_notice("success", "세그먼트 일정을 삭제했습니다.")
                        st.rerun()

    upcoming_rows = list_upcoming_segment_calendar_entries(days=14)
    if upcoming_rows:
        render_adjustable_dataframe(
            "앞으로 14일 일정",
            [
                {
                    "날짜": format_local_date(date.fromisoformat(str(row["schedule_date"]))),
                    "슬롯": row.get("send_window"),
                    "세그먼트": row.get("segment_label"),
                    "국가": display_country(row.get("target_country")),
                    "리드 목표": row.get("max_companies"),
                    "탐색 쿼리": row.get("lead_query"),
                    "마지막 실행": format_local_datetime(row.get("last_launched_at")) if row.get("last_launched_at") else "-",
                }
                for row in upcoming_rows
            ],
            "segment_calendar_upcoming",
        )


def render_copilot_panel(latest_run: dict[str, Any] | None) -> None:
    st.caption("운영 현황 요약과 다음 액션 추천만 제공합니다. 아직 실행은 하지 않습니다.")

    waiting_approvals = list_approval_items("waiting_approval")
    recent_notifications = list_notifications()
    quality_rows = build_quality_rows(latest_run["id"] if latest_run else None)
    history = st.session_state.setdefault("copilot_messages", [])
    prompt_key = "copilot_prompt_input"
    clear_key = "copilot_prompt_should_clear"

    if st.session_state.pop(clear_key, False):
        st.session_state[prompt_key] = ""

    st.markdown("**빠른 질문**")
    quick_columns = st.columns(2)
    for index, (label, prompt) in enumerate(COPILOT_QUICK_QUESTIONS.items()):
        if quick_columns[index % 2].button(label, key=f"copilot_quick_{index}", use_container_width=True):
            history.append({"role": "user", "content": prompt})
            history.append(
                {
                    "role": "assistant",
                    "content": answer_ops_question(
                        prompt,
                        latest_run=latest_run,
                        waiting_approvals=waiting_approvals,
                        recent_notifications=recent_notifications,
                        quality_rows=quality_rows,
                    ),
                }
            )

    prompt_key = "copilot_prompt_input"
    prompt = st.text_input(
        "질문",
        key=prompt_key,
        placeholder="예: 오늘 성과 알려줘 / 승인 대기 뭐 있어? / 다음에는 뭘 하는 게 좋아?",
    )

    if st.button("질문 보내기", key="copilot_send", use_container_width=True):
        cleaned = (prompt or "").strip()
        if cleaned:
            history.append({"role": "user", "content": cleaned})
            history.append(
                {
                    "role": "assistant",
                    "content": answer_ops_question(
                        cleaned,
                        latest_run=latest_run,
                        waiting_approvals=waiting_approvals,
                        recent_notifications=recent_notifications,
                        quality_rows=quality_rows,
                    ),
                }
            )
            st.session_state[clear_key] = True
            st.rerun()

    if st.button("대화 지우기", key="copilot_clear", use_container_width=True):
        st.session_state["copilot_messages"] = []
        st.rerun()

    if not history:
        st.info("오늘 성과, 승인 대기, 제안서 품질, 다음 추천 액션 등을 물어보면 바로 요약해드립니다.")
        return

    for message in history[-8:]:
        with st.chat_message("user" if message["role"] == "user" else "assistant"):
            st.write(message["content"])


def render_runs(key_prefix: str = "runs") -> dict[str, Any] | None:
    runs = list_runs()
    st.subheader("실행 기록")
    if not runs:
        st.info("실행 기록이 아직 없습니다.")
        return None

    selected_date = st.date_input("기준 날짜", value=date.today(), key=f"{key_prefix}_date")
    filtered_runs = filter_rows_by_date(runs, "started_at", selected_date)
    st.caption(f"선택 날짜: {format_local_date(selected_date)}")
    if not filtered_runs:
        st.info("선택한 날짜의 실행 기록이 없습니다.")
        return None

    selection_key = f"{key_prefix}_selected_run_id"
    valid_run_ids = {row["id"] for row in filtered_runs}
    if st.session_state.get(selection_key) not in valid_run_ids:
        st.session_state[selection_key] = filtered_runs[0]["id"]

    st.caption("최근 실행 5개를 카드로 먼저 보고, 자세한 표는 아래에서 펼쳐보세요.")
    for row in filtered_runs[:5]:
        asset_rows = list_assets(row["id"])
        asset_summary = summarize_asset_rows(asset_rows)
        issue = summarize_run_issue(row)
        is_selected = st.session_state.get(selection_key) == row["id"]
        with st.container(border=True):
            top_left, top_mid, top_right = st.columns([2.7, 1.1, 1.1])
            with top_left:
                st.markdown(f"**{display_status(row.get('status'))} · {format_local_datetime(row.get('started_at'))}**")
                st.caption(f"{get_run_segment_label(row)} | {display_country(row.get('target_country'))}")
            with top_mid:
                st.metric("생성 수", str(asset_summary["asset_count"]))
            with top_right:
                st.metric("회사 수", str(asset_summary["company_count"]))

            detail_left, detail_mid, detail_right = st.columns([1.2, 1.2, 3.0])
            detail_left.caption(f"검토 대기 {int(row.get('approval_count', 0) or 0)}건")
            detail_mid.caption(f"비용 ${float(row.get('estimated_cost_usd', 0) or 0):.4f}")
            if issue:
                detail_right.caption(f"{issue['title']} | {issue['action']}")
            else:
                detail_right.caption((row.get("lead_query") or "-")[:120])

            action_label = "선택됨" if is_selected else "이 실행 보기"
            if st.button(action_label, key=f"{key_prefix}_pick_{row['id']}", use_container_width=True, disabled=is_selected):
                st.session_state[selection_key] = row["id"]
                st.rerun()

    selected_run = next((row for row in filtered_runs if row["id"] == st.session_state.get(selection_key)), filtered_runs[0])

    with st.expander("전체 실행 기록 표", expanded=False):
        selected_run_id = st.selectbox(
            "확인할 실행",
            options=[row["id"] for row in filtered_runs],
            index=max(0, [row["id"] for row in filtered_runs].index(selected_run["id"])),
            key=f"{key_prefix}_select_run",
            format_func=lambda run_id: next(
                (
                    f"{format_local_datetime(row['started_at'])} | "
                    f"{display_country(row['target_country'])} | "
                    f"{display_status(row['status'])} | "
                    f"{get_run_segment_label(row)}"
                    for row in filtered_runs
                    if row["id"] == run_id
                ),
                str(run_id),
            ),
        )
        selected_run = next((row for row in filtered_runs if row["id"] == selected_run_id), filtered_runs[0])

        st.dataframe(
            [
                {
                    "시작 시각": row["started_at"],
                    "국가": display_country(row["target_country"]),
                    "상태": display_status(row["status"]),
                    "세그먼트": get_run_segment_label(row),
                    "실행 방식": "자동 추천" if get_run_metadata(row).get("auto_mode") else "직접 지정",
                    "탐색 기준": row["lead_query"],
                    "검토 대기": row["approval_count"],
                    "토큰": row["total_tokens"],
                    "비용(USD)": row["estimated_cost_usd"],
                }
                for row in filtered_runs
            ],
            hide_index=True,
            use_container_width=True,
        )

    st.session_state[selection_key] = selected_run["id"]
    return selected_run


def render_approval_queue(test_recipient: str) -> None:
    waiting = list_approval_items("waiting_approval")
    recent = list_approval_items()

    st.subheader("검토 대기")
    selected_date = st.date_input("생성 날짜", value=date.today(), key="approval_queue_date")
    st.caption(f"선택 날짜: {format_local_date(selected_date)}")
    waiting = filter_rows_by_date(waiting, "created_at", selected_date)
    recent = [
        row for row in recent
        if (parse_iso_date(row.get("decided_at")) or parse_iso_date(row.get("created_at"))) == selected_date
    ]
    urgent_waiting = [row for row in waiting if is_urgent_approval_item(row)]
    completed_today = [row for row in recent if row.get("status") in {"approved", "rejected"}]

    summary_cols = st.columns(3)
    summary_cols[0].metric("오늘 검토 건수", str(len(waiting)))
    summary_cols[1].metric("긴급 처리", str(len(urgent_waiting)))
    summary_cols[2].metric("오늘 처리 완료", str(len(completed_today)))

    if not waiting:
        st.info("검토 대기 중인 항목이 없습니다.")
    else:
        ordered_waiting = sorted(waiting, key=lambda row: (0 if is_urgent_approval_item(row) else 1, -int(row.get("priority", 0) or 0)))
        for item in ordered_waiting:
            with st.expander(f"{item.get('company_name') or '-'} | {item['title']}"):
                metadata = parse_json_field(item.get("metadata_json"), {})
                bundle_ids = parse_json_field(item.get("asset_bundle_json"), [])
                asset_rows = list_assets_by_ids(bundle_ids)
                st.caption(f"자동발송 판정: {summarize_auto_delivery(metadata)}")
                auto_delivery = parse_json_field(metadata.get("auto_delivery"), {})
                blocked_reasons = auto_delivery.get("blocked_reasons") or []
                if blocked_reasons:
                    st.warning("자동발송 차단 이유: " + " | ".join(blocked_reasons[:3]))
                if is_urgent_approval_item(item):
                    st.error("긴급 확인이 필요한 항목입니다. 차단 사유 또는 품질 이슈가 함께 잡혔습니다.")

                if asset_rows:
                    proposal_asset = next((row for row in asset_rows if row["asset_type"] == "proposal"), None)
                    email_preview = build_review_email_preview(asset_rows)
                    downloadable_assets = [
                        row for row in asset_rows if row.get("asset_type") in {"proposal_pdf", "proposal_docx"}
                    ]
                    if proposal_asset:
                        quality = evaluate_proposal_asset(proposal_asset)
                        summary = f"제안서 품질: {quality['score']}점 ({quality['label']})"
                        if quality["missing_sections"]:
                            summary += f" | 빠진 섹션: {', '.join(quality['missing_sections'][:3])}"
                        st.caption(summary)

                    st.dataframe(
                        [
                            {
                                "회사명": row["company_name"],
                                "종류": display_asset_type(row["asset_type"]),
                                "이름": row["title"],
                                "파일명": Path(str(row["path"])).name,
                            }
                            for row in asset_rows
                        ],
                        hide_index=True,
                        use_container_width=True,
                    )

                    action_cols = st.columns(2)
                    with action_cols[0]:
                        st.markdown("**제안서 바로 확인**")
                        if downloadable_assets:
                            for asset_row in downloadable_assets:
                                payload = build_downloadable_asset_payload(asset_row)
                                if payload:
                                    st.download_button(
                                        label=payload["label"],
                                        data=payload["data"],
                                        file_name=payload["file_name"],
                                        mime=payload["mime"],
                                        key=f"review_download_{item['id']}_{asset_row['asset_type']}",
                                        use_container_width=True,
                                    )
                        else:
                            st.caption("다운로드 가능한 제안서 파일이 없습니다.")

                    with action_cols[1]:
                        st.markdown("**메일 첨부 안내**")
                        if email_preview and email_preview["attachment_names"]:
                            st.caption(", ".join(email_preview["attachment_names"]))
                        else:
                            st.caption("첨부 파일 정보가 아직 없습니다.")

                    if email_preview:
                        st.markdown("**발송 메일 미리보기**")
                        st.text_input(
                            "메일 제목",
                            value=email_preview["subject"],
                            disabled=True,
                            key=f"review_email_subject_{item['id']}",
                        )
                        st.text_area(
                            "메일 본문",
                            value=email_preview["body"],
                            height=240,
                            disabled=True,
                            key=f"review_email_body_{item['id']}",
                        )

                rejection_reason = st.text_area(
                    "반려 사유",
                    key=f"reject_reason_{item['id']}",
                    placeholder="어떤 점을 보완하면 좋을지 적어주세요.",
                )
                c1, c2, c3 = st.columns(3)

                if c1.button("테스트 메일 보내기", key=f"send_test_{item['id']}", use_container_width=True):
                    try:
                        send_test_outbound_email(
                            run_id=item["run_id"],
                            company_name=item.get("company_name") or "",
                            asset_rows=asset_rows,
                            recipient=test_recipient,
                        )
                        st.success(f"{test_recipient}로 테스트 메일을 보냈습니다.")
                    except Exception as exc:
                        record_notification(
                            item["run_id"],
                            "test_outbound_email",
                            "failed",
                            f"[TEST] {item['title']}",
                            test_recipient,
                            {
                                "company_name": item.get("company_name"),
                                "error": str(exc),
                            },
                        )
                        st.error(str(exc))

                if c2.button("승인", key=f"approve_{item['id']}", use_container_width=True):
                    update_approval_item(item["id"], status="approved", decided_at=now_iso())
                    finalize_run_review_state(item["run_id"])
                    set_ui_notice("success", "승인 처리했습니다.")
                    st.rerun()

                if c3.button("반려 후 재작업", key=f"reject_{item['id']}", use_container_width=True):
                    reroute = route_rejection(metadata.get("asset_type", "proposal_package"), rejection_reason)
                    update_approval_item(
                        item["id"],
                        status="rejected",
                        decided_at=now_iso(),
                        rejection_reason=rejection_reason,
                        reroute_targets_json=reroute,
                    )
                    finalize_run_review_state(item["run_id"])
                    launched, message = launch_rework_for_approval(item, rejection_reason)
                    set_ui_notice("success" if launched else "warning", message)
                    st.rerun()

    st.markdown("**최근 처리 이력**")
    st.dataframe(
        [
            {
                "회사명": row["company_name"],
                "항목": row["title"],
                "상태": display_status(row["status"]),
                "재작업 대상": format_reroute_targets(row.get("reroute_targets_json")),
                "메모": (row.get("rejection_reason") or "-")[:120],
                "처리 시각": row["decided_at"],
            }
            for row in recent[:20]
        ],
        hide_index=True,
        use_container_width=True,
    )


def render_assets(selected_run: dict[str, Any] | None, *, show_subheader: bool = True, show_summary: bool = True) -> None:
    if show_subheader:
        st.subheader("산출물")
    assets = list_assets(selected_run["id"] if selected_run else None)
    if not assets:
        if show_summary:
            summary_cols = st.columns(4)
            summary_cols[0].metric("최근 생성 산출물", "0")
            summary_cols[1].metric("전체 산출물", "0")
            summary_cols[2].metric("제안서 원본", "0")
            summary_cols[3].metric("PDF 완료", "0")
        st.info("산출물이 아직 없습니다.")
        return

    asset_summary = summarize_asset_rows(assets)
    if show_summary:
        summary_cols = st.columns(4)
        summary_cols[0].metric("최근 생성 산출물", str(asset_summary["today_count"]))
        summary_cols[1].metric("전체 산출물", str(asset_summary["asset_count"]))
        summary_cols[2].metric("제안서 원본", str(asset_summary["proposal_count"]))
        summary_cols[3].metric("PDF 완료", str(asset_summary["pdf_count"]))

    companies = sorted({row["company_name"] for row in assets if row.get("company_name")})
    company_filter = st.selectbox("회사 선택", ["전체"] + companies, index=0)
    filtered_assets = assets if company_filter == "전체" else [row for row in assets if row.get("company_name") == company_filter]

    st.dataframe(
        [
            {
                "회사명": row["company_name"],
                "종류": display_asset_type(row["asset_type"]),
                "이름": row["title"],
                "상태": display_status(row["status"]),
                "생성 시각": row["created_at"],
                "파일명": Path(str(row["path"])).name,
            }
            for row in filtered_assets
        ],
        hide_index=True,
        use_container_width=True,
    )

    labels = [f"{row['company_name']} | {display_asset_type(row['asset_type'])} | {row['title']}" for row in filtered_assets]
    if not labels:
        return

    selected_label = st.selectbox("미리 볼 산출물", labels, index=0)
    selected_asset = filtered_assets[labels.index(selected_label)]
    asset_path = Path(selected_asset["path"])
    asset_metadata = parse_json_field(selected_asset.get("metadata_json"), {})

    st.caption(f"저장 파일: {asset_path.name}")
    if selected_asset["asset_type"] == "proposal":
        quality = evaluate_proposal_asset(selected_asset)
        summary = f"제안서 품질: {quality['score']}점 ({quality['label']})"
        if quality["missing_sections"]:
            summary += f" | 빠진 섹션: {', '.join(quality['missing_sections'][:4])}"
        st.caption(summary)

    with st.expander("기술 정보", expanded=False):
        st.caption(f"실행 세그먼트: {get_run_segment_label(selected_run)}" if selected_run else "실행 세그먼트 정보 없음")
        st.code(str(asset_path), language="text")

    if asset_path.suffix.lower() == ".pdf":
        data = read_asset_bytes(asset_path, asset_metadata)
        if data:
            st.download_button(
                label="PDF 내려받기",
                data=data,
                file_name=asset_path.name,
                mime="application/pdf",
                use_container_width=True,
            )
        else:
            st.warning("PDF 파일을 찾지 못했습니다.")
    elif asset_path.suffix.lower() == ".docx":
        data = read_asset_bytes(asset_path, asset_metadata)
        if data:
            st.download_button(
                label="Word 내려받기",
                data=data,
                file_name=asset_path.name,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
        else:
            st.warning("Word 파일을 찾지 못했습니다.")
    else:
        st.code(read_asset_content(asset_path, asset_metadata), language="markdown")


def render_notifications() -> None:
    st.subheader("알림 기록")
    rows = list_notifications()
    if not rows:
        st.info("알림 기록이 아직 없습니다.")
        return

    selected_date = st.date_input("알림 날짜", value=date.today(), key="notifications_date")
    st.caption(f"선택 날짜: {format_local_date(selected_date)}")
    rows = filter_rows_by_date(rows, "created_at", selected_date)
    if not rows:
        st.info("선택한 날짜의 알림 기록이 없습니다.")
        return

    st.dataframe(
        [
            {
                "시각": row["created_at"],
                "종류": row.get("kind", "-"),
                "상태": display_status(row["status"]),
                "제목": row["subject"],
                "수신자": row["recipient"],
            }
            for row in rows
        ],
        hide_index=True,
        use_container_width=True,
    )


def render_settings() -> None:
    backend_info = describe_runtime_backend()
    auto_send_settings = get_auto_send_settings()
    pipeline_baselines = load_pipeline_baselines()
    baseline_task_names = [
        "lead_research_task",
        "identity_disambiguation_task",
        "lead_verification_task",
        "website_audit_task",
        "competitor_analysis_task",
        "landing_page_task",
        "marketing_recommendation_task",
        "proposal_task",
        "proposal_localization_task",
        "email_outreach_task",
        "email_localization_task",
        "review_station",
    ]
    overview_task_names = [
        "lead_research_task",
        "identity_disambiguation_task",
        "lead_verification_task",
        "website_audit_task",
        "competitor_analysis_task",
        "landing_page_task",
        "marketing_recommendation_task",
        "proposal_task",
        "proposal_localization_task",
        "email_outreach_task",
        "email_localization_task",
    ]
    log_files = list_recent_runtime_logs(limit=5)
    average_baseline = round(
        sum(int(pipeline_baselines.get(task_name, DEFAULT_PIPELINE_BASELINES_MINUTES.get(task_name, 5))) for task_name in baseline_task_names)
        / len(baseline_task_names),
        1,
    )

    st.subheader("운영 설정")
    st.caption("기본 화면에는 핵심 운영값만 남기고, 세부 환경과 기준값은 아래 섹션에서 확인하도록 정리했습니다.")

    summary_cols = st.columns(4)
    summary_cols[0].metric("저장 상태", display_storage_status(backend_info))
    summary_cols[1].metric("자동 발송 모드", display_delivery_mode(auto_send_settings.mode))
    summary_cols[2].metric("부서 기준 평균", f"{average_baseline}분")
    summary_cols[3].metric("최근 로그", f"{len(log_files)}개")

    with st.container(border=True):
        left, right = st.columns([1.2, 1.0])
        with left:
            st.markdown("**현재 운영 요약**")
            st.caption(
                f"자동 발송 최소 제안서 점수 {auto_send_settings.min_proposal_score}점, "
                f"실행당 최대 {auto_send_settings.max_items_per_run}건까지 처리합니다."
            )
            st.caption(
                f"PDF 첨부는 {'필수' if auto_send_settings.require_pdf else '선택'}이며, "
                f"기본 알림 메일은 `{os.environ.get('ALERT_EMAIL_TO', ALERT_EMAIL_DEFAULT)}` 입니다."
            )
        with right:
            st.markdown("**조직 및 감시 상태**")
            st.caption(f"메인 운영 부서 {len(overview_task_names)}개, 지원 조직 {len(SUPPORT_TEAM_CONFIG)}개가 연결되어 있습니다.")
            if auto_send_settings.canary_email:
                st.caption(f"카나리 수신 메일: `{auto_send_settings.canary_email}`")
            else:
                st.caption("카나리 수신 메일은 아직 비어 있습니다.")

    with st.expander("운영 환경", expanded=False):
        st.write(f"프로젝트 위치: `{PROJECT_ROOT}`")
        st.write(f"운영 DB: `{DB_PATH}`")
        st.write(f"파이썬 실행 파일: `{resolve_python_executable()}`")
        st.write(f"현재 데이터 백엔드: `{backend_info['label']}`")
        if backend_info.get("remote_url"):
            st.write(f"Supabase URL: `{backend_info['remote_url']}`")
        if backend_info.get("storage_bucket"):
            st.write(f"Supabase Storage 버킷: `{backend_info['storage_bucket']}`")
        if backend_info["backend"] == "supabase":
            st.info("Notion 매핑이 없어도 현재는 Supabase를 운영 저장소로 사용합니다.")
        else:
            st.info("Notion 매핑이 없어도 현재는 로컬 SQLite를 운영 저장소로 사용합니다.")

    with st.expander("부서별 예상 소요시간 기준", expanded=False):
        st.caption("실행 노선도의 ETA 계산에 사용하는 기준값입니다. 실제 운영 흐름에 맞게 분 단위로 조정하세요.")
        with st.form("pipeline_baseline_form"):
            inputs: dict[str, int] = {}
            columns = st.columns(2)
            for index, task_name in enumerate(baseline_task_names):
                with columns[index % 2]:
                    if task_name == "review_station":
                        department_label = "검토 운영본부"
                        task_label = "확인 판단 / 시작 전 조정"
                    else:
                        department_label = DEPARTMENT_CONFIG.get(task_name, {}).get("department", display_task_name(task_name))
                        task_label = display_task_name(task_name)
                    inputs[task_name] = int(
                        st.number_input(
                            f"{department_label} · {task_label}",
                            min_value=1,
                            max_value=180,
                            value=int(pipeline_baselines.get(task_name, DEFAULT_PIPELINE_BASELINES_MINUTES.get(task_name, 5))),
                            step=1,
                            key=f"baseline_{task_name}",
                        )
                    )
            save_submitted = st.form_submit_button("기준 시간 저장", use_container_width=True)
        if save_submitted:
            save_pipeline_baselines(inputs)
            set_ui_notice("success", "부서별 예상 소요시간 기준을 저장했습니다.")
            st.rerun()
        if st.button("기본 기준으로 되돌리기", use_container_width=True):
            save_pipeline_baselines(DEFAULT_PIPELINE_BASELINES_MINUTES)
            set_ui_notice("success", "부서별 예상 소요시간 기준을 기본값으로 되돌렸습니다.")
            st.rerun()

    with st.expander("최근 실행 로그", expanded=False):
        if log_files:
            selected_log = st.selectbox("로그 파일", [f.name for f in log_files], key="settings_recent_log")
            log_path = next((path for path in log_files if path.name == selected_log), log_files[0])
            try:
                content = read_log_tail(log_path, max_chars=4000)
                st.code(content or "(비어 있음)", language="text")
            except Exception as e:
                st.warning(f"로그 읽기 실패: {e}")
        else:
            if PIPELINE_LOG_DIR.exists():
                st.info("로그 파일이 아직 없습니다.")
            else:
                st.info(f"로그 디렉터리가 없습니다: {PIPELINE_LOG_DIR}")

    with st.expander("구성현황", expanded=False):
        st.caption("메인 파이프라인 부서가 어떤 역할과 참여 인원으로 구성되어 있는지 정리해둔 영역입니다.")
        for task_name in overview_task_names:
            department = DEPARTMENT_CONFIG.get(task_name, {})
            members = get_department_members(task_name)
            support = department.get("support") or []
            with st.container(border=True):
                left, right = st.columns([1.4, 1.0])
                with left:
                    st.markdown(f"**{department.get('department', display_task_name(task_name))}**")
                    st.caption(display_task_name(task_name))
                    st.write(department.get("summary") or "-")
                with right:
                    st.markdown("**참여 인원**")
                    for member in members:
                        st.markdown(f"- **{member['name']}** (`{display_task_name(member['crew_label'])}`)")
                        st.caption(f"맡은 역할: {member['role']}")
                        st.caption(f"집중 비전: {member['vision']}")
                    if support:
                        st.markdown(f"**지원팀**: {', '.join(support)}")
                    else:
                        st.caption("지원팀 없음")

    with st.expander("지원 조직", expanded=False):
        for team in SUPPORT_TEAM_CONFIG:
            with st.expander(f"{team['department']} | {team['status']}", expanded=False):
                for member_name, member_role in team["members"]:
                    st.markdown(f"- **{member_name}**: {member_role}")
    return


def render_segment_calendar_tab(*, notify_email: str, test_mode: bool) -> None:
    st.subheader("세그먼트 캘린더")
    st.caption("세그먼트별 발송 일정을 관리하고, 지난 날짜에는 실제 무엇을 보냈는지 아카이브로 바로 확인합니다.")

    presets = list_segment_presets()
    preset_lookup = {preset["id"]: preset for preset in presets}

    for preset in presets:
        preset_title = (
            f"{preset['label']} | "
            f"{', '.join(display_country(code) for code in preset['recommended_countries'])} | "
            f"리드 목표 {preset.get('default_max_companies', '-')}"
        )
        with st.expander(preset_title, expanded=False):
            st.write(preset["description"])
            st.write(f"오퍼: `{preset['offer']}`")
            st.write(f"추천 국가: {', '.join(display_country(code) for code in preset['recommended_countries'])}")
            st.write(f"대상 직책: {', '.join(preset['target_roles'])}")
            st.write("대표 포트폴리오")
            for portfolio_row in preset["portfolio"]:
                st.markdown(f"- {portfolio_row}")

    st.markdown("#### 일정 추가")
    with st.form("segment_calendar_form", clear_on_submit=False):
        schedule_date = st.date_input("캘린더 날짜", value=date.today(), key="segment_calendar_form_date")
        segment_id = st.selectbox(
            "세그먼트",
            options=[preset["id"] for preset in presets],
            format_func=lambda value: preset_lookup[value]["label"],
            key="segment_calendar_form_segment",
        )
        selected_preset = preset_lookup[segment_id]
        recommended_countries = selected_preset.get("recommended_countries") or COUNTRIES
        default_country = selected_preset.get("default_country") or recommended_countries[0]
        target_country = st.selectbox(
            "대상 국가",
            options=recommended_countries,
            index=max(0, recommended_countries.index(default_country)) if default_country in recommended_countries else 0,
            format_func=lambda code: f"{display_country(code)} ({code})",
            key="segment_calendar_form_country",
        )
        send_window = st.selectbox("발송 시간대", options=["오전", "오후", "종일"], key="segment_calendar_form_window")
        max_companies = st.number_input(
            "타깃 리드 수",
            min_value=1,
            max_value=50,
            value=int(selected_preset.get("default_max_companies") or 10),
            step=1,
            key="segment_calendar_form_max_companies",
        )
        notes = st.text_area("운영 메모", height=90, key="segment_calendar_form_notes")
        preview_query = (
            selected_preset.get("country_queries", {}).get(target_country)
            or selected_preset.get("country_queries", {}).get("default")
            or ""
        )
        st.caption(f"이 일정으로 실행될 기본 탐색 쿼리: `{preview_query}`")
        submitted = st.form_submit_button("일정 저장", use_container_width=True)

    if submitted:
        entry = create_segment_calendar_entry(
            schedule_date=schedule_date,
            segment_id=segment_id,
            target_country=target_country,
            send_window=send_window,
            max_companies=int(max_companies),
            notes=notes,
        )
        add_segment_calendar_entry(entry)
        set_ui_notice("success", f"{format_local_date(schedule_date)} 일정에 `{entry['segment_label']}` 세그먼트를 추가했습니다.")
        st.rerun()

    st.markdown("#### 일정 / 발송 아카이브")
    selected_date = st.date_input("확인 날짜", value=date.today(), key="segment_calendar_view_date")
    selected_rows = list_segment_calendar_entries_for_date(selected_date)
    archive_rows = build_delivery_archive_rows(selected_date)
    archive_summary = summarize_delivery_archive(archive_rows)

    summary_cols = st.columns(4)
    summary_cols[0].metric("등록 일정", str(len(selected_rows)))
    summary_cols[1].metric("발송 완료", str(archive_summary["sent"]))
    summary_cols[2].metric("차단 / 실패", str(archive_summary["blocked"] + archive_summary["failed"]))
    summary_cols[3].metric("테스트 발송", str(archive_summary["tests"]))

    if not selected_rows:
        st.caption(f"{format_local_date(selected_date)}에는 등록된 세그먼트 일정이 없습니다.")
    else:
        for row in selected_rows:
            preset = get_segment_preset(str(row.get("segment_id") or ""))
            row_title = (
                f"{row.get('segment_label', '-')} | "
                f"{display_country(row.get('target_country'))} ({row.get('target_country')}) | "
                f"{row.get('send_window')} | 목표 {row.get('max_companies')}"
            )
            with st.expander(row_title, expanded=False):
                if preset:
                    st.write(f"오퍼: `{preset['offer']}`")
                st.write(f"타깃 리드 목표: `{row.get('max_companies')}`")
                st.write(f"탐색 쿼리: `{row.get('lead_query') or '-'}`")
                if row.get("notes"):
                    st.write(f"메모: {row['notes']}")
                if row.get("last_launched_at"):
                    st.caption(f"마지막 실행: {format_local_datetime(row.get('last_launched_at'))}")

                action_left, action_right = st.columns([1.4, 1.0])
                with action_left:
                    if st.button("이 일정으로 실행", key=f"segment_calendar_launch_{row['id']}", use_container_width=True):
                        launch_background_run(
                            target_country=str(row.get("target_country") or "US"),
                            lead_query=str(row.get("lead_query") or ""),
                            lead_mode="region_or_industry",
                            max_companies=int(row.get("max_companies") or 10),
                            notify_email=notify_email,
                            test_mode=test_mode,
                            trigger_source="segment_calendar",
                            segment_id=str(row.get("segment_id") or ""),
                            segment_label=str(row.get("segment_label") or ""),
                            segment_brief=str(row.get("segment_brief") or ""),
                        )
                        mark_segment_calendar_entry_launched(str(row["id"]))
                        set_ui_notice("success", f"`{row.get('segment_label')}` 일정으로 런을 시작했습니다.")
                        st.rerun()
                with action_right:
                    if st.button("일정 삭제", key=f"segment_calendar_delete_{row['id']}", use_container_width=True):
                        delete_segment_calendar_entry(str(row["id"]))
                        set_ui_notice("success", "세그먼트 일정을 삭제했습니다.")
                        st.rerun()

    st.markdown("#### 날짜별 발송 아카이브")
    if archive_rows:
        st.dataframe(
            [
                {
                    "시각": format_local_datetime(row.get("created_at")),
                    "종류": row.get("kind_label"),
                    "상태": row.get("status_label"),
                    "회사명": row.get("company_name"),
                    "세그먼트": row.get("segment_label"),
                    "국가": row.get("country_label"),
                    "수신자": row.get("recipient"),
                    "제목": row.get("subject"),
                    "첨부": ", ".join(row.get("attachments") or []) or "-",
                }
                for row in archive_rows
            ],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("선택한 날짜의 아웃바운드 발송 기록이 아직 없습니다.")

    daily_rollup = build_daily_delivery_rollup(days=14)
    if daily_rollup:
        with st.expander("지난 14일 발송 요약", expanded=False):
            render_adjustable_dataframe("지난 14일 발송 요약", daily_rollup, "segment_calendar_archive_rollup")

    upcoming_rows = list_upcoming_segment_calendar_entries(days=14)
    if upcoming_rows:
        render_adjustable_dataframe(
            "앞으로 14일 일정",
            [
                {
                    "날짜": format_local_date(date.fromisoformat(str(row["schedule_date"]))),
                    "시간대": row.get("send_window"),
                    "세그먼트": row.get("segment_label"),
                    "국가": display_country(row.get("target_country")),
                    "리드 목표": row.get("max_companies"),
                    "탐색 쿼리": row.get("lead_query"),
                    "마지막 실행": format_local_datetime(row.get("last_launched_at")) if row.get("last_launched_at") else "-",
                }
                for row in upcoming_rows
            ],
            "segment_calendar_upcoming",
        )


def render_approval_queue(test_recipient: str) -> None:
    st.subheader("검토 대기")
    selected_date = st.date_input("생성 날짜", value=date.today(), key="approval_queue_date")
    st.caption(f"선택 날짜: {format_local_date(selected_date)}")

    waiting = filter_rows_by_date(list_approval_items("waiting_approval"), "created_at", selected_date)
    recent = [
        row
        for row in list_approval_items()
        if (parse_iso_date(row.get("decided_at")) or parse_iso_date(row.get("created_at"))) == selected_date
    ]
    contexts = [build_approval_item_context(item) for item in waiting]
    urgent_waiting = [context for context in contexts if context["urgent"]]
    completed_today = [row for row in recent if row.get("status") in {"approved", "rejected"}]
    high_quality = [context for context in contexts if context["quality_score"] >= 90]

    summary_cols = st.columns(4)
    summary_cols[0].metric("오늘 검토 건수", str(len(contexts)))
    summary_cols[1].metric("긴급 처리", str(len(urgent_waiting)))
    summary_cols[2].metric("오늘 처리 완료", str(len(completed_today)))
    summary_cols[3].metric("90점 이상 제안서", str(len(high_quality)))

    if not contexts:
        st.info("검토 대기 중인 항목이 없습니다.")
        if recent:
            st.markdown("**최근 처리 이력**")
            st.dataframe(
                [
                    {
                        "회사명": row.get("company_name") or "-",
                        "항목": row.get("title") or "-",
                        "상태": display_status(row.get("status")),
                        "재작업 대상": format_reroute_targets(row.get("reroute_targets_json")),
                        "검토 메모": (row.get("rejection_reason") or parse_json_field(row.get("metadata_json"), {}).get("reviewer_note") or "-")[:120],
                        "처리 시각": format_local_datetime(row.get("decided_at") or row.get("created_at")),
                    }
                    for row in recent[:20]
                ],
                hide_index=True,
                use_container_width=True,
            )
        return

    countries = ["전체"] + sorted({context["country_label"] for context in contexts if context["country_label"]})
    segments = ["전체"] + sorted({context["segment_label"] for context in contexts if context["segment_label"]})

    filter_cols = st.columns([1.2, 1.7, 1.1, 1.3])
    selected_country = filter_cols[0].selectbox("국가", countries, key="approval_filter_country")
    selected_segment = filter_cols[1].selectbox("세그먼트", segments, key="approval_filter_segment")
    urgent_only = filter_cols[2].toggle("긴급만", value=False, key="approval_filter_urgent")
    quality_floor = filter_cols[3].slider("품질 하한", min_value=0, max_value=100, value=0, step=5, key="approval_filter_quality")
    quick_mode = st.toggle("빠른 처리 모드", value=True, key="approval_quick_mode")

    filtered_contexts: list[dict[str, Any]] = []
    for context in contexts:
        if selected_country != "전체" and context["country_label"] != selected_country:
            continue
        if selected_segment != "전체" and context["segment_label"] != selected_segment:
            continue
        if urgent_only and not context["urgent"]:
            continue
        if context["quality_score"] < quality_floor:
            continue
        filtered_contexts.append(context)

    filtered_contexts.sort(
        key=lambda context: (
            0 if context["urgent"] else 1,
            -context["priority"],
            -context["quality_score"],
            context["item"].get("created_at") or "",
        )
    )

    if not filtered_contexts:
        st.info("현재 필터에 맞는 검토 항목이 없습니다.")
        return

    if quick_mode:
        quick_ids = [str(context["item"]["id"]) for context in filtered_contexts]
        quick_state_key = "approval_quick_selected_id"
        if st.session_state.get(quick_state_key) not in quick_ids:
            st.session_state[quick_state_key] = quick_ids[0]
        current_index = quick_ids.index(st.session_state[quick_state_key])
        selected_context = filtered_contexts[current_index]
        selected_item = selected_context["item"]

        nav_left, nav_mid, nav_right = st.columns([1.0, 1.6, 1.0])
        with nav_left:
            if st.button("이전 항목", key="approval_quick_prev", use_container_width=True, disabled=current_index == 0):
                st.session_state[quick_state_key] = quick_ids[current_index - 1]
                st.rerun()
        with nav_mid:
            st.caption(
                f"빠른 처리 {current_index + 1} / {len(filtered_contexts)} | "
                f"{selected_item.get('company_name') or '-'} | {selected_item.get('title')}"
            )
        with nav_right:
            if st.button("다음 항목", key="approval_quick_next", use_container_width=True, disabled=current_index == len(quick_ids) - 1):
                st.session_state[quick_state_key] = quick_ids[current_index + 1]
                st.rerun()

        with st.container(border=True):
            header_left, header_right = st.columns([2.6, 1.0])
            with header_left:
                st.markdown(f"**{selected_item.get('company_name') or '-'}**")
                st.caption(f"{selected_context['segment_label']} | {selected_context['country_label']}")
                st.caption(f"자동 발송 상태: {summarize_auto_delivery(selected_context['metadata'])}")
            with header_right:
                st.caption(f"우선순위 {selected_context['priority']}")
                st.caption(f"생성 시각 {format_local_datetime(selected_item.get('created_at'))}")

            if selected_context["quality"]:
                quality = selected_context["quality"]
                quality_text = f"제안서 점수 {quality['score']}점 ({quality['label']})"
                if quality["missing_sections"]:
                    quality_text += f" | 빈 섹션: {', '.join(quality['missing_sections'][:3])}"
                st.caption(quality_text)

            if selected_context["validation_issues"]:
                issue_labels = [VALIDATION_ISSUE_LABELS.get(value, value) for value in selected_context["validation_issues"][:3]]
                st.warning("검토 포인트: " + " | ".join(issue_labels))

            blocked_reasons = selected_context["auto_delivery"].get("blocked_reasons") or []
            if blocked_reasons:
                st.warning("자동 발송 차단 사유: " + " | ".join(blocked_reasons[:3]))

            if selected_context["urgent"]:
                st.error("긴급 확인이 필요한 항목입니다. 발송 차단 사유 또는 제안서 이슈를 먼저 확인하세요.")

            render_review_asset_preview(selected_context, key_prefix=f"approval_quick_{selected_item['id']}")
            render_review_action_panel(
                selected_context,
                test_recipient=test_recipient,
                note_key=f"approval_quick_note_{selected_item['id']}",
                action_prefix=f"approval_quick_{selected_item['id']}",
            )

    with st.expander("전체 항목 보기", expanded=not quick_mode):
        for context in filtered_contexts:
            item = context["item"]
            title = f"{item.get('company_name') or '-'} | {item['title']}"
            with st.container(border=True):
                top_left, top_right = st.columns([2.6, 1.0])
                with top_left:
                    st.markdown(f"**{title}**")
                    st.caption(f"{context['segment_label']} | {context['country_label']}")
                    st.caption(f"자동 발송 상태: {summarize_auto_delivery(context['metadata'])}")
                with top_right:
                    st.caption(f"우선순위 {context['priority']}")
                    st.caption(f"품질 {context['quality_score']}점")

                info_line = []
                if context["urgent"]:
                    info_line.append("긴급")
                if context["validation_issues"]:
                    issue_labels = [VALIDATION_ISSUE_LABELS.get(value, value) for value in context["validation_issues"][:2]]
                    info_line.append("검토 포인트: " + ", ".join(issue_labels))
                blocked_reasons = context["auto_delivery"].get("blocked_reasons") or []
                if blocked_reasons:
                    info_line.append("차단: " + ", ".join(blocked_reasons[:2]))
                st.caption(" | ".join(info_line) if info_line else "바로 검토 가능")

                if st.button("빠른 처리로 열기", key=f"approval_focus_{item['id']}", use_container_width=True):
                    st.session_state["approval_quick_selected_id"] = str(item["id"])
                    st.session_state["approval_quick_mode"] = True
                    st.rerun()

    st.markdown("**최근 처리 이력**")
    st.dataframe(
        [
            {
                "회사명": row.get("company_name") or "-",
                "항목": row.get("title") or "-",
                "상태": display_status(row.get("status")),
                "재작업 대상": format_reroute_targets(row.get("reroute_targets_json")),
                "검토 메모": (row.get("rejection_reason") or parse_json_field(row.get("metadata_json"), {}).get("reviewer_note") or "-")[:120],
                "처리 시각": format_local_datetime(row.get("decided_at") or row.get("created_at")),
            }
            for row in recent[:20]
        ],
        hide_index=True,
        use_container_width=True,
    )


def render_assets(selected_run: dict[str, Any] | None, *, show_subheader: bool = True, show_summary: bool = True) -> None:
    if show_subheader:
        st.subheader("산출물")
    assets = list_assets(selected_run["id"] if selected_run else None)
    if not assets:
        if show_summary:
            summary_cols = st.columns(4)
            summary_cols[0].metric("오늘 생성 산출물", "0")
            summary_cols[1].metric("전체 산출물", "0")
            summary_cols[2].metric("제안서 원본", "0")
            summary_cols[3].metric("PDF 완료", "0")
        st.info("산출물이 아직 없습니다.")
        return

    asset_summary = summarize_asset_rows(assets)
    if show_summary:
        summary_cols = st.columns(4)
        summary_cols[0].metric("오늘 생성 산출물", str(asset_summary["today_count"]))
        summary_cols[1].metric("전체 산출물", str(asset_summary["asset_count"]))
        summary_cols[2].metric("제안서 원본", str(asset_summary["proposal_count"]))
        summary_cols[3].metric("PDF 완료", str(asset_summary["pdf_count"]))

    companies = sorted({row["company_name"] for row in assets if row.get("company_name")})
    company_filter = st.selectbox("회사 선택", ["전체"] + companies, index=0)
    filtered_assets = assets if company_filter == "전체" else [row for row in assets if row.get("company_name") == company_filter]

    st.dataframe(
        [
            {
                "회사명": row["company_name"],
                "종류": display_asset_type(row["asset_type"]),
                "이름": row["title"],
                "상태": display_status(row["status"]),
                "생성 시각": format_local_datetime(row["created_at"]),
                "파일명": Path(str(row["path"])).name,
            }
            for row in filtered_assets
        ],
        hide_index=True,
        use_container_width=True,
    )

    labels = [f"{row['company_name']} | {display_asset_type(row['asset_type'])} | {row['title']}" for row in filtered_assets]
    if not labels:
        return

    selected_label = st.selectbox("미리 볼 산출물", labels, index=0)
    selected_asset = filtered_assets[labels.index(selected_label)]
    asset_path = Path(selected_asset["path"])
    asset_metadata = parse_json_field(selected_asset.get("metadata_json"), {})

    st.caption(f"선택 파일: {asset_path.name}")
    if selected_asset["asset_type"] == "proposal":
        quality = evaluate_proposal_asset(selected_asset)
        quality_text = f"제안서 점수: {quality['score']}점 ({quality['label']})"
        if quality["missing_sections"]:
            quality_text += f" | 빈 섹션: {', '.join(quality['missing_sections'][:4])}"
        st.caption(quality_text)

    with st.expander("기술 정보", expanded=False):
        st.caption(f"실행 세그먼트: {get_run_segment_label(selected_run)}" if selected_run else "실행 세그먼트 정보 없음")
        st.code(str(asset_path), language="text")

    if asset_path.suffix.lower() == ".pdf":
        data = read_asset_bytes(asset_path, asset_metadata)
        if data:
            st.download_button(
                label="PDF 내려받기",
                data=data,
                file_name=asset_path.name,
                mime="application/pdf",
                use_container_width=True,
            )
            with st.expander("PDF 미리보기", expanded=False):
                render_pdf_preview(selected_asset, key_prefix=f"asset_preview_{selected_asset['id']}")
        else:
            st.warning("PDF 파일을 찾지 못했습니다.")
    elif asset_path.suffix.lower() == ".docx":
        data = read_asset_bytes(asset_path, asset_metadata)
        if data:
            st.download_button(
                label="Word 내려받기",
                data=data,
                file_name=asset_path.name,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
        else:
            st.warning("Word 파일을 찾지 못했습니다.")
    else:
        st.code(read_asset_content(asset_path, asset_metadata), language="markdown")


def render_notifications() -> None:
    st.subheader("알림 기록")
    rows = list_notifications()
    if not rows:
        st.info("알림 기록이 아직 없습니다.")
        return

    selected_date = st.date_input("알림 날짜", value=date.today(), key="notifications_date")
    st.caption(f"선택 날짜: {format_local_date(selected_date)}")
    rows = filter_rows_by_date(rows, "created_at", selected_date)
    outbound_rows = build_delivery_archive_rows(selected_date)
    outbound_summary = summarize_delivery_archive(outbound_rows)

    summary_cols = st.columns(4)
    summary_cols[0].metric("아웃바운드 이벤트", str(outbound_summary["total"]))
    summary_cols[1].metric("발송 완료", str(outbound_summary["sent"]))
    summary_cols[2].metric("차단 / 실패", str(outbound_summary["blocked"] + outbound_summary["failed"]))
    summary_cols[3].metric("테스트 발송", str(outbound_summary["tests"]))

    if outbound_rows:
        st.markdown("**오늘의 발송 추적**")
        st.dataframe(
            [
                {
                    "시각": format_local_datetime(row.get("created_at")),
                    "종류": row.get("kind_label"),
                    "상태": row.get("status_label"),
                    "회사명": row.get("company_name"),
                    "세그먼트": row.get("segment_label"),
                    "국가": row.get("country_label"),
                    "수신자": row.get("recipient"),
                    "제목": row.get("subject"),
                }
                for row in outbound_rows
            ],
            hide_index=True,
            use_container_width=True,
        )

    if not rows:
        st.info("선택한 날짜의 알림 기록이 없습니다.")
        return

    with st.expander("전체 알림 기록", expanded=False):
        st.dataframe(
            [
                {
                    "시각": format_local_datetime(row["created_at"]),
                    "종류": OUTBOUND_NOTIFICATION_KIND_LABELS.get(str(row.get("kind") or ""), row.get("kind", "-")),
                    "상태": display_status(row["status"]),
                    "제목": row["subject"],
                    "수신자": row["recipient"],
                }
                for row in rows
            ],
            hide_index=True,
            use_container_width=True,
        )


def render_settings() -> None:
    backend_info = describe_runtime_backend()
    auto_send_settings = get_auto_send_settings()
    pipeline_baselines = load_pipeline_baselines()
    version_info = build_runtime_version_info()
    baseline_task_names = [
        "lead_research_task",
        "identity_disambiguation_task",
        "lead_verification_task",
        "website_audit_task",
        "competitor_analysis_task",
        "landing_page_task",
        "marketing_recommendation_task",
        "proposal_task",
        "proposal_localization_task",
        "email_outreach_task",
        "email_localization_task",
        "review_station",
    ]
    overview_task_names = [
        "lead_research_task",
        "identity_disambiguation_task",
        "lead_verification_task",
        "website_audit_task",
        "competitor_analysis_task",
        "landing_page_task",
        "marketing_recommendation_task",
        "proposal_task",
        "proposal_localization_task",
        "email_outreach_task",
        "email_localization_task",
    ]
    log_files = list_recent_runtime_logs(limit=5)
    average_baseline = round(
        sum(int(pipeline_baselines.get(task_name, DEFAULT_PIPELINE_BASELINES_MINUTES.get(task_name, 5))) for task_name in baseline_task_names)
        / len(baseline_task_names),
        1,
    )

    st.subheader("운영 설정")
    st.caption("기본 화면에서는 운영에 필요한 값만 보이고, 자세한 환경 정보와 기준값은 아래 섹션에서 조정합니다.")

    with st.container(border=True):
        version_left, version_mid, version_right = st.columns([1.0, 1.0, 1.8])
        version_left.markdown("**배포 버전**")
        version_left.caption(f"{version_info['environment']} | {version_info['service']}")
        version_mid.metric("커밋", version_info["commit"])
        version_right.caption(f"브랜치: {version_info['branch']}")
        version_right.caption(f"빌드 시각: {version_info['build_time']}")

    summary_cols = st.columns(4)
    summary_cols[0].metric("저장 상태", display_storage_status(backend_info))
    summary_cols[1].metric("자동 발송 모드", display_delivery_mode(auto_send_settings.mode))
    summary_cols[2].metric("부서 기준 평균", f"{average_baseline}분")
    summary_cols[3].metric("최근 로그", f"{len(log_files)}개")

    with st.container(border=True):
        left, right = st.columns([1.2, 1.0])
        with left:
            st.markdown("**현재 운영 요약**")
            st.caption(
                f"자동 발송 최소 제안서 점수는 {auto_send_settings.min_proposal_score}점, "
                f"실행당 최대 {auto_send_settings.max_items_per_run}건까지 처리합니다."
            )
            st.caption(
                f"PDF 첨부는 {'필수' if auto_send_settings.require_pdf else '선택'}이고, "
                f"기본 알림 메일은 `{os.environ.get('ALERT_EMAIL_TO', ALERT_EMAIL_DEFAULT)}` 입니다."
            )
        with right:
            st.markdown("**조직 / 감시 상태**")
            st.caption(f"메인 운영 부서는 {len(overview_task_names)}개, 지원 조직은 {len(SUPPORT_TEAM_CONFIG)}개가 연결되어 있습니다.")
            if auto_send_settings.canary_email:
                st.caption(f"카나리 수신 메일: `{auto_send_settings.canary_email}`")
            else:
                st.caption("카나리 수신 메일은 아직 비어 있습니다.")

    with st.expander("운영 환경", expanded=False):
        st.write(f"프로젝트 위치: `{PROJECT_ROOT}`")
        st.write(f"운영 DB: `{DB_PATH}`")
        st.write(f"파이썬 실행 파일: `{resolve_python_executable()}`")
        st.write(f"현재 데이터 백엔드: `{backend_info['label']}`")
        if backend_info.get("remote_url"):
            st.write(f"Supabase URL: `{backend_info['remote_url']}`")
        if backend_info.get("storage_bucket"):
            st.write(f"Supabase Storage 버킷: `{backend_info['storage_bucket']}`")
        if backend_info["backend"] == "supabase":
            st.info("현재는 Supabase를 운영 저장소로 사용합니다.")
        else:
            st.info("현재는 로컬 SQLite를 운영 저장소로 사용합니다.")

    with st.expander("부서별 예상 소요시간 기준", expanded=False):
        st.caption("실행 노선도의 ETA 계산에 쓰는 기준값입니다. 실제 운영 흐름에 맞게 분 단위로 조정하세요.")
        with st.form("pipeline_baseline_form"):
            inputs: dict[str, int] = {}
            columns = st.columns(2)
            for index, task_name in enumerate(baseline_task_names):
                with columns[index % 2]:
                    if task_name == "review_station":
                        department_label = "검토 운영본부"
                        task_label = "검토 판단 / 재작업 조정"
                    else:
                        department_label = DEPARTMENT_CONFIG.get(task_name, {}).get("department", display_task_name(task_name))
                        task_label = display_task_name(task_name)
                    inputs[task_name] = int(
                        st.number_input(
                            f"{department_label} | {task_label}",
                            min_value=1,
                            max_value=180,
                            value=int(pipeline_baselines.get(task_name, DEFAULT_PIPELINE_BASELINES_MINUTES.get(task_name, 5))),
                            step=1,
                            key=f"baseline_{task_name}",
                        )
                    )
            save_submitted = st.form_submit_button("기준 시간 저장", use_container_width=True)
        if save_submitted:
            save_pipeline_baselines(inputs)
            set_ui_notice("success", "부서별 예상 소요시간 기준을 저장했습니다.")
            st.rerun()
        if st.button("기본 기준으로 되돌리기", use_container_width=True):
            save_pipeline_baselines(DEFAULT_PIPELINE_BASELINES_MINUTES)
            set_ui_notice("success", "부서별 예상 소요시간 기준을 기본값으로 되돌렸습니다.")
            st.rerun()

    with st.expander("최근 실행 로그", expanded=False):
        if log_files:
            selected_log = st.selectbox("로그 파일", [f.name for f in log_files], key="settings_recent_log")
            log_path = next((path for path in log_files if path.name == selected_log), log_files[0])
            try:
                content = read_log_tail(log_path, max_chars=4000)
                st.code(content or "(비어 있음)", language="text")
            except Exception as exc:
                st.warning(f"로그 읽기 실패: {exc}")
        else:
            if PIPELINE_LOG_DIR.exists():
                st.info("로그 파일이 아직 없습니다.")
            else:
                st.info(f"로그 디렉터리가 없습니다: {PIPELINE_LOG_DIR}")

    with st.expander("구성현황", expanded=False):
        st.caption("메인 파이프라인 부서가 어떤 역할과 참여 인원으로 구성되어 있는지 정리한 영역입니다.")
        for task_name in overview_task_names:
            department = DEPARTMENT_CONFIG.get(task_name, {})
            members = get_department_members(task_name)
            support = department.get("support") or []
            with st.container(border=True):
                left, right = st.columns([1.4, 1.0])
                with left:
                    st.markdown(f"**{department.get('department', display_task_name(task_name))}**")
                    st.caption(display_task_name(task_name))
                    st.write(department.get("summary") or "-")
                with right:
                    st.markdown("**참여 인원**")
                    for member in members:
                        st.markdown(f"- **{member['name']}** (`{display_task_name(member['crew_label'])}`)")
                        st.caption(f"맡은 역할: {member['role']}")
                        st.caption(f"직무 비전: {member['vision']}")
                    if support:
                        st.markdown(f"**지원팀**: {', '.join(support)}")
                    else:
                        st.caption("지원팀 없음")

    with st.expander("지원 조직", expanded=False):
        for team in SUPPORT_TEAM_CONFIG:
            with st.expander(f"{team['department']} | {team['status']}", expanded=False):
                for member_name, member_role in team["members"]:
                    st.markdown(f"- **{member_name}**: {member_role}")


def render_review_asset_preview(context: dict[str, Any], *, key_prefix: str) -> None:
    asset_rows = context["asset_rows"]
    downloadable_assets = context["downloadable_assets"]
    email_preview = context["email_preview"]

    if not asset_rows:
        st.info("연결된 산출물이 없습니다.")
        return

    st.markdown("**생성된 파일**")
    for row in asset_rows:
        render_compact_row(
            title=row["title"],
            subtitle=display_asset_type(row["asset_type"]),
            meta=Path(str(row["path"])).name,
            pill_html=build_status_pill_html(display_status(row.get("status")), tone=tone_for_status(row.get("status"))),
            accent_tone=tone_for_status(row.get("status")),
        )

    action_cols = st.columns(2)
    with action_cols[0]:
        st.markdown("**제안서 파일 확인**")
        if downloadable_assets:
            for asset_row in downloadable_assets:
                payload = build_downloadable_asset_payload(asset_row)
                if payload:
                    render_safe_download_button(
                        payload,
                        key=f"{key_prefix}_download_{asset_row['asset_type']}",
                        use_container_width=True,
                    )
        else:
            st.caption("다운로드 가능한 제안서 파일이 없습니다.")

    with action_cols[1]:
        st.markdown("**메일 첨부 안내**")
        if email_preview and email_preview["attachment_names"]:
            st.caption(", ".join(email_preview["attachment_names"]))
        else:
            st.caption("첨부 파일 정보가 아직 없습니다.")

    pdf_asset = context.get("pdf_asset")
    if pdf_asset:
        with st.expander("PDF 미리보기", expanded=False):
            render_pdf_preview(pdf_asset, key_prefix=f"{key_prefix}_pdf")

    proposal_asset = context.get("proposal_asset")
    if proposal_asset:
        proposal_path = Path(str(proposal_asset["path"]))
        proposal_metadata = parse_json_field(proposal_asset.get("metadata_json"), {})
        with st.expander("제안서 원문 보기", expanded=False):
            st.code(read_asset_content(proposal_path, proposal_metadata), language="markdown")

    if email_preview:
        st.markdown("**발송 메일 미리보기**")
        st.text_input(
            "메일 제목",
            value=email_preview["subject"],
            disabled=True,
            key=f"{key_prefix}_email_subject",
        )
        st.text_area(
            "메일 본문",
            value=email_preview["body"],
            height=240,
            disabled=True,
            key=f"{key_prefix}_email_body",
        )


def render_assets(selected_run: dict[str, Any] | None, *, show_subheader: bool = True, show_summary: bool = True) -> None:
    if show_subheader:
        st.subheader("산출물")
    assets = list_assets(selected_run["id"] if selected_run else None)
    if not assets:
        if show_summary:
            summary_cols = st.columns(4)
            summary_cols[0].metric("오늘 생성 산출물", "0")
            summary_cols[1].metric("전체 산출물", "0")
            summary_cols[2].metric("제안서 원본", "0")
            summary_cols[3].metric("PDF 완료", "0")
        st.info("산출물이 아직 없습니다.")
        return

    asset_summary = summarize_asset_rows(assets)
    if show_summary:
        summary_cols = st.columns(4)
        summary_cols[0].metric("오늘 생성 산출물", str(asset_summary["today_count"]))
        summary_cols[1].metric("전체 산출물", str(asset_summary["asset_count"]))
        summary_cols[2].metric("제안서 원본", str(asset_summary["proposal_count"]))
        summary_cols[3].metric("PDF 완료", str(asset_summary["pdf_count"]))

    companies = sorted({row["company_name"] for row in assets if row.get("company_name")})
    company_filter = st.selectbox("회사 선택", ["전체"] + companies, index=0)
    filtered_assets = assets if company_filter == "전체" else [row for row in assets if row.get("company_name") == company_filter]

    st.markdown("**파일 목록**")
    for row in filtered_assets:
        render_compact_row(
            title=row["title"],
            subtitle=f"{row['company_name']} | {display_asset_type(row['asset_type'])}",
            meta=f"{format_local_datetime(row['created_at'])} | {Path(str(row['path'])).name}",
            pill_html=build_status_pill_html(display_status(row.get("status")), tone=tone_for_status(row.get("status"))),
            accent_tone=tone_for_status(row.get("status")),
        )

    labels = [f"{row['company_name']} | {display_asset_type(row['asset_type'])} | {row['title']}" for row in filtered_assets]
    if not labels:
        return

    selected_label = st.selectbox("미리 볼 산출물", labels, index=0)
    selected_asset = filtered_assets[labels.index(selected_label)]
    asset_path = Path(selected_asset["path"])
    asset_metadata = parse_json_field(selected_asset.get("metadata_json"), {})

    st.caption(f"선택 파일: {asset_path.name}")
    if selected_asset["asset_type"] == "proposal":
        quality = evaluate_proposal_asset(selected_asset)
        quality_text = f"제안서 점수: {quality['score']}점 ({quality['label']})"
        if quality["missing_sections"]:
            quality_text += f" | 빈 섹션: {', '.join(quality['missing_sections'][:4])}"
        st.caption(quality_text)

    if asset_path.suffix.lower() == ".pdf":
        data = read_asset_bytes(asset_path, asset_metadata)
        if data:
            render_safe_download_button(
                {
                    "label": "PDF 내려받기",
                    "data": data,
                    "file_name": asset_path.name,
                    "mime": "application/pdf",
                },
                key=f"asset_pdf_download_{selected_asset['id']}",
                use_container_width=True,
            )
            with st.expander("PDF 미리보기", expanded=False):
                render_pdf_preview(selected_asset, key_prefix=f"asset_preview_{selected_asset['id']}")
        else:
            st.warning("PDF 파일을 찾지 못했습니다.")
    elif asset_path.suffix.lower() == ".docx":
        data = read_asset_bytes(asset_path, asset_metadata)
        if data:
            render_safe_download_button(
                {
                    "label": "Word 내려받기",
                    "data": data,
                    "file_name": asset_path.name,
                    "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                },
                key=f"asset_docx_download_{selected_asset['id']}",
                use_container_width=True,
            )
        else:
            st.warning("Word 파일을 찾지 못했습니다.")

        preview_source = next(
            (
                row
                for row in filtered_assets
                if row.get("company_name") == selected_asset.get("company_name") and row.get("asset_type") == "proposal"
            ),
            None,
        )
        if preview_source:
            preview_path = Path(str(preview_source["path"]))
            preview_metadata = parse_json_field(preview_source.get("metadata_json"), {})
            with st.expander("제안서 원문 보기", expanded=False):
                st.code(read_asset_content(preview_path, preview_metadata), language="markdown")
    else:
        st.code(read_asset_content(asset_path, asset_metadata), language="markdown")

    with st.expander("기술 정보", expanded=False):
        st.caption(f"실행 세그먼트: {get_run_segment_label(selected_run)}" if selected_run else "실행 세그먼트 정보 없음")
        st.code(str(asset_path), language="text")


def render_segment_calendar_tab(*, notify_email: str, test_mode: bool) -> None:
    st.subheader("세그먼트 캘린더")
    st.caption("세그먼트별 발송 일정과 실제 발송 기록을 같은 캘린더 문맥에서 관리합니다.")

    presets = list_segment_presets()
    preset_lookup = {preset["id"]: preset for preset in presets}

    for preset in presets:
        preset_title = (
            f"{preset['label']} | "
            f"{', '.join(display_country(code) for code in preset['recommended_countries'])} | "
            f"리드 목표 {preset.get('default_max_companies', '-')}"
        )
        with st.expander(preset_title, expanded=False):
            st.write(preset["description"])
            st.write(f"오퍼: `{preset['offer']}`")
            st.write(f"추천 국가: {', '.join(display_country(code) for code in preset['recommended_countries'])}")
            st.write(f"대상 직책: {', '.join(preset['target_roles'])}")
            st.write("대표 포트폴리오")
            for portfolio_row in preset["portfolio"]:
                st.markdown(f"- {portfolio_row}")

    st.markdown("#### 일정 추가")
    with st.form("segment_calendar_form", clear_on_submit=False):
        schedule_date = st.date_input("캘린더 날짜", value=date.today(), key="segment_calendar_form_date")
        segment_id = st.selectbox(
            "세그먼트",
            options=[preset["id"] for preset in presets],
            format_func=lambda value: preset_lookup[value]["label"],
            key="segment_calendar_form_segment",
        )
        selected_preset = preset_lookup[segment_id]
        recommended_countries = selected_preset.get("recommended_countries") or COUNTRIES
        default_country = selected_preset.get("default_country") or recommended_countries[0]
        target_country = st.selectbox(
            "대상 국가",
            options=recommended_countries,
            index=max(0, recommended_countries.index(default_country)) if default_country in recommended_countries else 0,
            format_func=lambda code: f"{display_country(code)} ({code})",
            key="segment_calendar_form_country",
        )
        send_window = st.selectbox("발송 시간대", options=["오전", "오후", "종일"], key="segment_calendar_form_window")
        max_companies = st.number_input("타깃 리드 수", min_value=1, max_value=50, value=int(selected_preset.get("default_max_companies") or 10), step=1, key="segment_calendar_form_max_companies")
        notes = st.text_area("운영 메모", height=90, key="segment_calendar_form_notes")
        preview_query = (
            selected_preset.get("country_queries", {}).get(target_country)
            or selected_preset.get("country_queries", {}).get("default")
            or ""
        )
        st.caption(f"이 일정으로 실행될 기본 탐색 쿼리: `{preview_query}`")
        submitted = st.form_submit_button("일정 저장", use_container_width=True)

    if submitted:
        entry = create_segment_calendar_entry(
            schedule_date=schedule_date,
            segment_id=segment_id,
            target_country=target_country,
            send_window=send_window,
            max_companies=int(max_companies),
            notes=notes,
        )
        add_segment_calendar_entry(entry)
        set_ui_notice("success", f"{format_local_date(schedule_date)} 일정에 `{entry['segment_label']}` 세그먼트를 추가했습니다.")
        st.rerun()

    st.markdown("#### 일정 / 발송 아카이브")
    selected_date = st.date_input("확인 날짜", value=date.today(), key="segment_calendar_view_date")
    selected_rows = list_segment_calendar_entries_for_date(selected_date)
    archive_rows = build_delivery_archive_rows(selected_date)
    archive_summary = summarize_delivery_archive(archive_rows)

    summary_cols = st.columns(4)
    summary_cols[0].metric("등록 일정", str(len(selected_rows)))
    summary_cols[1].metric("발송 완료", str(archive_summary["sent"]))
    summary_cols[2].metric("차단 / 실패", str(archive_summary["blocked"] + archive_summary["failed"]))
    summary_cols[3].metric("테스트 발송", str(archive_summary["tests"]))

    if not selected_rows:
        st.caption(f"{format_local_date(selected_date)}에는 등록된 세그먼트 일정이 없습니다.")
    else:
        for row in selected_rows:
            preset = get_segment_preset(str(row.get("segment_id") or ""))
            row_title = (
                f"{row.get('segment_label', '-')} | "
                f"{display_country(row.get('target_country'))} ({row.get('target_country')}) | "
                f"{row.get('send_window')} | 목표 {row.get('max_companies')}"
            )
            with st.expander(row_title, expanded=False):
                if preset:
                    st.write(f"오퍼: `{preset['offer']}`")
                st.write(f"타깃 리드 목표: `{row.get('max_companies')}`")
                st.write(f"탐색 쿼리: `{row.get('lead_query') or '-'}`")
                if row.get("notes"):
                    st.write(f"메모: {row['notes']}")
                if row.get("last_launched_at"):
                    st.caption(f"마지막 실행: {format_local_datetime(row.get('last_launched_at'))}")

                action_left, action_right = st.columns([1.4, 1.0])
                with action_left:
                    if st.button("이 일정으로 실행", key=f"segment_calendar_launch_{row['id']}", use_container_width=True):
                        launch_background_run(
                            target_country=str(row.get("target_country") or "US"),
                            lead_query=str(row.get("lead_query") or ""),
                            lead_mode="region_or_industry",
                            max_companies=int(row.get("max_companies") or 10),
                            notify_email=notify_email,
                            test_mode=test_mode,
                            trigger_source="segment_calendar",
                            segment_id=str(row.get("segment_id") or ""),
                            segment_label=str(row.get("segment_label") or ""),
                            segment_brief=str(row.get("segment_brief") or ""),
                        )
                        mark_segment_calendar_entry_launched(str(row["id"]))
                        set_ui_notice("success", f"`{row.get('segment_label')}` 일정으로 런을 시작했습니다.")
                        st.rerun()
                with action_right:
                    if st.button("일정 삭제", key=f"segment_calendar_delete_{row['id']}", use_container_width=True):
                        delete_segment_calendar_entry(str(row["id"]))
                        set_ui_notice("success", "세그먼트 일정을 삭제했습니다.")
                        st.rerun()

    st.markdown("#### 날짜별 발송 아카이브")
    if archive_rows:
        for row in archive_rows:
            render_compact_row(
                title=row.get("subject") or "-",
                subtitle=f"{row.get('company_name')} | {row.get('segment_label')} | {row.get('country_label')}",
                meta=f"{format_local_datetime(row.get('created_at'))} | {row.get('recipient')} | {', '.join(row.get('attachments') or []) or '-'}",
                pill_html=build_status_pill_html(row.get("status_label") or "-", tone=tone_for_status(row.get("status"))),
                accent_tone=tone_for_status(row.get("status")),
            )
    else:
        st.info("선택한 날짜의 아웃바운드 발송 기록이 아직 없습니다.")

    daily_rollup = build_daily_delivery_rollup(days=14)
    if daily_rollup:
        with st.expander("지난 14일 발송 요약", expanded=False):
            render_adjustable_dataframe("지난 14일 발송 요약", daily_rollup, "segment_calendar_archive_rollup")


def render_approval_queue(test_recipient: str) -> None:
    st.subheader("검토 대기")
    selected_date = st.date_input("생성 날짜", value=date.today(), key="approval_queue_date")
    st.caption(f"선택 날짜: {format_local_date(selected_date)}")

    waiting = filter_rows_by_date(list_approval_items("waiting_approval"), "created_at", selected_date)
    recent = [
        row
        for row in list_approval_items()
        if (parse_iso_date(row.get("decided_at")) or parse_iso_date(row.get("created_at"))) == selected_date
    ]
    contexts = [build_approval_item_context(item) for item in waiting]
    urgent_waiting = [context for context in contexts if context["urgent"]]
    completed_today = [row for row in recent if row.get("status") in {"approved", "rejected"}]
    high_quality = [context for context in contexts if context["quality_score"] >= 90]

    summary_cols = st.columns(4)
    summary_cols[0].metric("오늘 검토 건수", str(len(contexts)))
    summary_cols[1].metric("긴급 처리", str(len(urgent_waiting)))
    summary_cols[2].metric("오늘 처리 완료", str(len(completed_today)))
    summary_cols[3].metric("90점 이상 제안서", str(len(high_quality)))

    countries = ["전체"] + sorted({context["country_label"] for context in contexts if context["country_label"]})
    segments = ["전체"] + sorted({context["segment_label"] for context in contexts if context["segment_label"]})
    filter_cols = st.columns([1.2, 1.7, 1.1, 1.3])
    selected_country = filter_cols[0].selectbox("국가", countries, key="approval_filter_country")
    selected_segment = filter_cols[1].selectbox("세그먼트", segments, key="approval_filter_segment")
    urgent_only = filter_cols[2].toggle("긴급만", value=False, key="approval_filter_urgent")
    quality_floor = filter_cols[3].slider("품질 하한", min_value=0, max_value=100, value=0, step=5, key="approval_filter_quality")
    quick_mode = st.toggle("빠른 처리 모드", value=True, key="approval_quick_mode")

    filtered_contexts: list[dict[str, Any]] = []
    for context in contexts:
        if selected_country != "전체" and context["country_label"] != selected_country:
            continue
        if selected_segment != "전체" and context["segment_label"] != selected_segment:
            continue
        if urgent_only and not context["urgent"]:
            continue
        if context["quality_score"] < quality_floor:
            continue
        filtered_contexts.append(context)

    filtered_contexts.sort(
        key=lambda context: (
            0 if context["urgent"] else 1,
            -context["priority"],
            -context["quality_score"],
            context["item"].get("created_at") or "",
        )
    )

    if not filtered_contexts:
        st.info("현재 필터에 맞는 검토 항목이 없습니다.")
    else:
        if quick_mode:
            quick_ids = [str(context["item"]["id"]) for context in filtered_contexts]
            quick_state_key = "approval_quick_selected_id"
            if st.session_state.get(quick_state_key) not in quick_ids:
                st.session_state[quick_state_key] = quick_ids[0]
            current_index = quick_ids.index(st.session_state[quick_state_key])
            selected_context = filtered_contexts[current_index]
            selected_item = selected_context["item"]

            nav_left, nav_mid, nav_right = st.columns([1.0, 1.6, 1.0])
            with nav_left:
                if st.button("이전 항목", key="approval_quick_prev", use_container_width=True, disabled=current_index == 0):
                    st.session_state[quick_state_key] = quick_ids[current_index - 1]
                    st.rerun()
            with nav_mid:
                st.caption(
                    f"빠른 처리 {current_index + 1} / {len(filtered_contexts)} | "
                    f"{selected_item.get('company_name') or '-'} | {selected_item.get('title')}"
                )
            with nav_right:
                if st.button("다음 항목", key="approval_quick_next", use_container_width=True, disabled=current_index == len(quick_ids) - 1):
                    st.session_state[quick_state_key] = quick_ids[current_index + 1]
                    st.rerun()

            with st.container(border=True):
                header_left, header_right = st.columns([2.6, 1.0])
                with header_left:
                    st.markdown(f"**{selected_item.get('company_name') or '-'}**")
                    st.caption(f"{selected_context['segment_label']} | {selected_context['country_label']}")
                    st.caption(f"자동 발송 상태: {summarize_auto_delivery(selected_context['metadata'])}")
                with header_right:
                    st.caption(f"우선순위 {selected_context['priority']}")
                    st.caption(f"생성 시각 {format_local_datetime(selected_item.get('created_at'))}")

                if selected_context["quality"]:
                    quality = selected_context["quality"]
                    quality_text = f"제안서 점수 {quality['score']}점 ({quality['label']})"
                    if quality["missing_sections"]:
                        quality_text += f" | 빈 섹션: {', '.join(quality['missing_sections'][:3])}"
                    st.caption(quality_text)

                if selected_context["validation_issues"]:
                    issue_labels = [VALIDATION_ISSUE_LABELS.get(value, value) for value in selected_context["validation_issues"][:3]]
                    st.warning("검토 포인트: " + " | ".join(issue_labels))

                blocked_reasons = selected_context["auto_delivery"].get("blocked_reasons") or []
                if blocked_reasons:
                    st.warning("자동 발송 차단 사유: " + " | ".join(blocked_reasons[:3]))

                if selected_context["urgent"]:
                    st.error("긴급 확인이 필요한 항목입니다. 발송 차단 사유 또는 제안서 이슈를 먼저 확인하세요.")

                render_review_asset_preview(selected_context, key_prefix=f"approval_quick_{selected_item['id']}")
                render_review_action_panel(
                    selected_context,
                    test_recipient=test_recipient,
                    note_key=f"approval_quick_note_{selected_item['id']}",
                    action_prefix=f"approval_quick_{selected_item['id']}",
                )

        with st.expander("전체 항목 보기", expanded=not quick_mode):
            for context in filtered_contexts:
                item = context["item"]
                render_compact_row(
                    title=f"{item.get('company_name') or '-'} | {item['title']}",
                    subtitle=f"{context['segment_label']} | {context['country_label']}",
                    meta=f"우선순위 {context['priority']} | 품질 {context['quality_score']}점",
                    pill_html=build_status_pill_html("검토 대기", tone="amber"),
                    accent_tone="amber",
                )
                if st.button("빠른 처리로 열기", key=f"approval_focus_{item['id']}", use_container_width=True):
                    st.session_state["approval_quick_selected_id"] = str(item["id"])
                    st.session_state["approval_quick_mode"] = True
                    st.rerun()

    st.markdown("**최근 처리 이력**")
    rework_lookup = build_rework_state_lookup(recent)
    if not recent:
        st.caption("오늘 처리한 검토 이력이 아직 없습니다.")
    else:
        for row in recent[:20]:
            item_id = str(row.get("id") or "")
            state = rework_lookup.get(item_id)
            if state:
                pill_html = build_status_pill_html(state["label"], tone=state["tone"], spinning=bool(state.get("spinning")))
                accent_tone = state["tone"]
            else:
                pill_html = build_status_pill_html(display_status(row.get("status")), tone=tone_for_status(row.get("status")))
                accent_tone = tone_for_status(row.get("status"))
            render_compact_row(
                title=f"{row.get('company_name') or '-'} | {row.get('title') or '-'}",
                subtitle=format_reroute_targets(row.get("reroute_targets_json")),
                meta=f"{format_local_datetime(row.get('decided_at') or row.get('created_at'))} | {(row.get('rejection_reason') or parse_json_field(row.get('metadata_json'), {}).get('reviewer_note') or '-')[:120]}",
                pill_html=pill_html,
                accent_tone=accent_tone,
            )


def render_notifications() -> None:
    st.subheader("알림 기록")
    rows = list_notifications()
    if not rows:
        st.info("알림 기록이 아직 없습니다.")
        return

    selected_date = st.date_input("알림 날짜", value=date.today(), key="notifications_date")
    st.caption(f"선택 날짜: {format_local_date(selected_date)}")
    rows = filter_rows_by_date(rows, "created_at", selected_date)
    outbound_rows = build_delivery_archive_rows(selected_date)
    outbound_summary = summarize_delivery_archive(outbound_rows)

    summary_cols = st.columns(4)
    summary_cols[0].metric("아웃바운드 이벤트", str(outbound_summary["total"]))
    summary_cols[1].metric("발송 완료", str(outbound_summary["sent"]))
    summary_cols[2].metric("차단 / 실패", str(outbound_summary["blocked"] + outbound_summary["failed"]))
    summary_cols[3].metric("테스트 발송", str(outbound_summary["tests"]))

    if outbound_rows:
        st.markdown("**오늘의 발송 추적**")
        for row in outbound_rows:
            render_compact_row(
                title=row.get("subject") or "-",
                subtitle=f"{row.get('company_name')} | {row.get('segment_label')} | {row.get('country_label')}",
                meta=f"{format_local_datetime(row.get('created_at'))} | {row.get('recipient')}",
                pill_html=build_status_pill_html(row.get("status_label") or "-", tone=tone_for_status(row.get("status"))),
                accent_tone=tone_for_status(row.get("status")),
            )

    if rows:
        with st.expander("전체 알림 기록", expanded=False):
            st.dataframe(
                [
                    {
                        "시각": format_local_datetime(row["created_at"]),
                        "종류": OUTBOUND_NOTIFICATION_KIND_LABELS.get(str(row.get("kind") or ""), row.get("kind", "-")),
                        "상태": display_status(row["status"]),
                        "제목": row["subject"],
                        "수신자": row["recipient"],
                    }
                    for row in rows
                ],
                hide_index=True,
                use_container_width=True,
            )


def main() -> None:
    load_runtime()
    st.set_page_config(page_title="세일즈 운영 콘솔", layout="wide")
    inject_app_shell_styles()
    st.title("세일즈 운영 콘솔")
    st.caption(f"오늘 날짜: {format_local_date(date.today())} | 웹에서 실행과 검토를 관리하고, 메일은 알림 용도로만 사용합니다.")
    render_ui_notice()

    running_run = query_running_run()
    latest_run = list_runs(limit=1)
    latest_run = latest_run[0] if latest_run else None
    if st.session_state.pop("dashboard_auto_refresh_enable_pending", False):
        st.session_state["dashboard_auto_refresh_enabled"] = True
    elif "dashboard_auto_refresh_enabled" not in st.session_state:
        st.session_state["dashboard_auto_refresh_enabled"] = bool(running_run)

    with st.sidebar:
        st.header("실행 시작")
        with st.container(border=True):
            with st.expander("1. 기본 조건", expanded=True):
                target_country = st.selectbox(
                    "대상 국가",
                    COUNTRIES,
                    index=0,
                    format_func=lambda code: f"{COUNTRY_LABELS[code]} ({code})",
                )
                country_defaults = COUNTRY_DEFAULTS[target_country]

                lead_mode = st.selectbox(
                    "탐색 방식",
                    ["region_or_industry", "company_name"],
                    index=0,
                    format_func=lambda value: LEAD_MODE_LABELS.get(value, value),
                )
                lead_query = st.text_area(
                    "탐색 조건",
                    value="",
                    height=100,
                    placeholder=(
                        "비워두면 자동 모드로 실행됩니다. "
                        f"예시 기준: `{country_defaults['lead_query']}`"
                    ),
                )
                max_companies = st.slider("최대 회사 수", min_value=1, max_value=10, value=2)

            preview_strategy = build_strategy_snapshot(
                target_country=target_country,
                lead_mode=lead_mode,
                lead_query=lead_query,
            )
            preview_patterns = preview_strategy.get("selected_patterns", [])
            preview_pattern_text = ", ".join(pattern.get("pattern_name", "-") for pattern in preview_patterns[:2]) if preview_patterns else "직접 지정 조건"

            with st.expander("2. 실행 프리뷰 · 시작", expanded=True):
                preview_segment = "자동 패턴 추천" if preview_strategy.get("auto_mode") else "직접 지정 타깃"
                with st.container(border=True):
                    st.markdown(f"**{'자동 모드' if preview_strategy.get('auto_mode') else '수동 모드'}**")
                    st.caption(f"세그먼트: {preview_segment}")
                    st.caption(f"탐색 기준: {preview_strategy.get('resolved_query', '-')}")
                    st.caption(f"대표 패턴: {preview_pattern_text}")

                notify_email = st.text_input(
                    "알림 받을 메일",
                    value=os.environ.get("ALERT_EMAIL_TO", ALERT_EMAIL_DEFAULT),
                    key="alert_email_input",
                )
                auto_refresh_enabled = st.checkbox(
                    "실행 중 자동 갱신",
                    key="dashboard_auto_refresh_enabled",
                    help="실행 중일 때만 4초마다 갱신합니다. 검토 화면을 읽을 때는 끄는 편이 안전합니다.",
                )
                test_mode = st.checkbox("테스트 모드", value=True)

                if running_run:
                    st.warning(
                        f"현재 {display_task_name(infer_run_focus_task_name(running_run))} 단계가 진행 중입니다. "
                        "실행 현황 탭이 4초마다 자동 갱신됩니다."
                    )

                if st.button("시작", type="primary", use_container_width=True):
                    if running_run:
                        st.error("이미 실행 중인 작업이 있습니다. 끝난 뒤 다시 시작해주세요.")
                    elif lead_mode == "company_name" and not lead_query.strip():
                        st.error("회사명 지정 모드에서는 탐색 조건을 비워둘 수 없습니다. 회사명을 입력해주세요.")
                    else:
                        launch_background_run(
                            target_country=target_country,
                            lead_query=lead_query.strip(),
                            lead_mode=lead_mode,
                            max_companies=max_companies,
                            notify_email=notify_email.strip(),
                            test_mode=test_mode,
                        )
                        st.session_state["dashboard_auto_refresh_enable_pending"] = True
                        st.session_state["run_just_launched"] = True
                        set_ui_notice("success", "실행을 시작했습니다. 실행 현황 탭에서 진행 상태를 확인하세요.")
                        st.rerun()

                if st.button("새로고침", use_container_width=True):
                    st.rerun()

    top_left, top_right = st.columns([5.2, 1.2])
    with top_right:
        with st.popover("총괄 비서", use_container_width=True):
            render_copilot_panel(latest_run)

    tabs = st.tabs(
        [
            "오늘의 전략",
            "세그먼트 캘린더",
            "실행 현황",
            "검토 대기",
            "산출물",
            "알림",
            "설정",
        ]
    )

    with tabs[0]:
        render_strategy_tab(
            preview_strategy=preview_strategy,
            selected_country=target_country,
            latest_run=latest_run,
        )

    with tabs[1]:
        render_segment_calendar_tab(
            notify_email=notify_email.strip(),
            test_mode=test_mode,
        )

    with tabs[2]:
        render_dashboard(latest_run)
        st.divider()
        with st.expander("이전 실행 기록 보기", expanded=False):
            selected_run = render_runs("runs_tab")
            if selected_run:
                st.markdown("**선택한 실행의 작업 목록**")
                st.dataframe(
                    [
                        {
                            "순서": row["task_order"],
                            "작업": display_task_name(row["task_name"]),
                            "담당": (
                                f"{get_department_members(row.get('task_name'))[0]['name']} "
                                f"({display_task_name(get_department_members(row.get('task_name'))[0]['crew_label'])})"
                                if get_department_members(row.get("task_name"))
                                else "-"
                            ),
                            "모델": row["model_name"],
                            "상태": display_status(row["status"]),
                            "토큰": row["total_tokens"],
                            "비용(USD)": row["estimated_cost_usd"],
                        }
                        for row in list_tasks(selected_run["id"])
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
                with st.expander("선택한 실행의 로그", expanded=False):
                    render_run_log_panel(selected_run, key_prefix=f"selected_run_log_{selected_run.get('id', 'run')}")

    with tabs[3]:
        render_approval_queue(st.session_state.get("alert_email_input", ALERT_EMAIL_DEFAULT))

    with tabs[4]:
        st.subheader("산출물")
        overview_assets = list_assets(latest_run["id"]) if latest_run else []
        overview_summary = summarize_asset_rows(overview_assets)
        overview_cols = st.columns(4)
        overview_cols[0].metric("최근 생성 산출물", str(overview_summary["today_count"]))
        overview_cols[1].metric("전체 산출물", str(overview_summary["asset_count"]))
        overview_cols[2].metric("제안서 원본", str(overview_summary["proposal_count"]))
        overview_cols[3].metric("PDF 완료", str(overview_summary["pdf_count"]))
        if latest_run:
            st.caption(f"최근 실행 기준: {get_run_segment_label(latest_run)} | {display_country(latest_run.get('target_country'))}")
        else:
            st.caption("아직 실행 이력이 없어 최근 산출물 요약은 0건으로 표시됩니다.")

        render_assets(latest_run, show_subheader=False, show_summary=False)
        with st.expander("다른 실행 산출물 보기", expanded=False):
            selected_run = render_runs("assets_tab")
            if selected_run and (not latest_run or selected_run.get("id") != latest_run.get("id")):
                render_assets(selected_run, show_subheader=False, show_summary=False)

    with tabs[5]:
        render_notifications()

    with tabs[6]:
        render_settings()

    refresh_interval = get_auto_refresh_interval_seconds(
        running_run=running_run,
        latest_run=latest_run,
        enabled=bool(st.session_state.get("dashboard_auto_refresh_enabled", False)),
    )
    if refresh_interval:
        time.sleep(refresh_interval)
        st.rerun()


if __name__ == "__main__":
    main()
