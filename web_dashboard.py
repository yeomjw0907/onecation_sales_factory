from __future__ import annotations

import html
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime
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
from sales_factory.auto_delivery import get_auto_send_settings
from sales_factory.runtime_assets import route_rejection
from sales_factory.runtime_copilot import answer_ops_question
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
from sales_factory.runtime_supabase import materialize_local_asset, read_asset_bytes, read_asset_text
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
    if eligible:
        return f"{mode} eligible"
    if reasons:
        return f"{mode} blocked: {reasons[0]}"
    return f"{mode} blocked"


def summarize_run_auto_delivery(run_row: dict[str, Any] | None) -> dict[str, Any]:
    metadata = parse_json_field(run_row.get("metadata_json") if run_row else None, {})
    return parse_json_field(metadata.get("auto_delivery_summary"), {})


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


def launch_background_run(
    *,
    target_country: str,
    lead_query: str,
    lead_mode: str,
    max_companies: int,
    notify_email: str,
    test_mode: bool,
    trigger_source: str = "dashboard",
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
    ]
    if test_mode:
        args.append("--test-mode")

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


def send_test_outbound_email(
    *,
    run_id: str,
    company_name: str,
    asset_rows: list[dict[str, Any]],
    recipient: str,
) -> None:
    email_asset = next((row for row in asset_rows if row["asset_type"] == "email_sequence"), None)
    proposal_pdf_asset = next((row for row in asset_rows if row["asset_type"] == "proposal_pdf"), None)
    if not email_asset:
        raise RuntimeError("이 패키지에는 메일 시퀀스 산출물이 없습니다.")

    email_metadata = parse_json_field(email_asset.get("metadata_json"), {})
    subject, body = parse_primary_email_asset(Path(email_asset["path"]), email_metadata)
    attachments: list[Path] = []
    if proposal_pdf_asset:
        attachment_metadata = parse_json_field(proposal_pdf_asset.get("metadata_json"), {})
        attachment_path = materialize_local_asset(Path(proposal_pdf_asset["path"]), attachment_metadata)
        if attachment_path:
            attachments.append(attachment_path)

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


def render_dashboard(latest_run: dict[str, Any] | None) -> None:
    st.subheader("현재 현황")

    if not latest_run:
        st.info("아직 실행 기록이 없습니다.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("상태", display_status(latest_run.get("status")))
    c2.metric("대상 국가", display_country(latest_run.get("target_country")))
    c3.metric("검토 대기", str(latest_run.get("approval_count", 0)))
    c4.metric("토큰 사용량", f"{latest_run.get('total_tokens', 0):,}")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("현재 작업", display_task_name(latest_run.get("current_task")))
    current_members = get_department_members(latest_run.get("current_task"))
    current_staff = current_members[0] if current_members else {"name": "-", "crew_label": "-"}
    c6.metric("현재 담당", f"{current_staff['name']} ({display_task_name(current_staff['crew_label'])})")
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

    if latest_run.get("error_message"):
        st.error(latest_run["error_message"])

    tasks = list_tasks(latest_run["id"])
    if not tasks:
        return

    render_department_board(tasks, latest_run)

    st.markdown("**작업 진행표**")
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


def render_department_board(tasks: list[dict[str, Any]], latest_run: dict[str, Any]) -> None:
    status_palette = {
        "completed": {"bg": "#0f2b25", "border": "#34d399", "badge_bg": "#dcfce7", "badge_text": "#166534"},
        "running": {"bg": "#10233d", "border": "#60a5fa", "badge_bg": "#dbeafe", "badge_text": "#1d4ed8"},
        "waiting_approval": {"bg": "#302510", "border": "#facc15", "badge_bg": "#fef3c7", "badge_text": "#92400e"},
        "pending": {"bg": "#1c2330", "border": "#94a3b8", "badge_bg": "#e2e8f0", "badge_text": "#334155"},
        "failed": {"bg": "#32161a", "border": "#f87171", "badge_bg": "#fee2e2", "badge_text": "#b91c1c"},
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
            f"<span style='display:inline-flex;align-items:center;padding:4px 8px;border-radius:999px;"
            f"background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.08);"
            f"font-size:12px;font-weight:700;margin:0 6px 6px 0;'>{html.escape(item)}</span>"
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
                    <div style="width:40px;height:40px;border-radius:999px;background:{palette['bg']};
                    border:1px solid {palette['border']};display:flex;align-items:center;justify-content:center;
                    font-weight:800;font-size:16px;">{index}</div>
                    """,
                    unsafe_allow_html=True,
                )
            with center:
                st.markdown(
                    f"""
                    <div style="font-size:12px;font-weight:800;letter-spacing:0.04em;text-transform:uppercase;
                    color:{palette['border']};margin-bottom:6px;">{html.escape(config['department'])}</div>
                    <div style="font-size:22px;font-weight:800;line-height:1.2;margin-bottom:6px;">{html.escape(display_task_name(row.get("task_name")))}</div>
                    <div style="font-size:14px;opacity:0.9;margin-bottom:8px;">{html.escape(config.get("summary") or "")}</div>
                    <div style="font-size:13px;font-weight:800;opacity:0.95;margin-bottom:6px;">참여 직원</div>
                    {member_lines(members)}
                    <div style="font-size:12px;opacity:0.7;margin-top:4px;">실행 모델: {html.escape(row.get("model_name") or "-")}</div>
                    <div style="margin-top:10px;">{support_badges(config.get("support", []))}</div>
                    """,
                    unsafe_allow_html=True,
                )
            with right:
                st.markdown(status_badge(display_status(row.get("status")), row.get("status")), unsafe_allow_html=True)
                st.caption(f"토큰 {int(row.get('total_tokens', 0) or 0):,}")
                st.caption(f"비용 ${float(row.get('estimated_cost_usd', 0) or 0):.4f}")

        if index < len(tasks):
            st.markdown("<div style='padding:4px 0 10px 22px;color:#64748b;'>↓</div>", unsafe_allow_html=True)

    waiting_items = [item for item in list_approval_items("waiting_approval") if item.get("run_id") == latest_run.get("id")]
    approval_status = latest_run.get("status")
    if approval_status in {"waiting_approval", "rejected"} or waiting_items:
        st.markdown("<div style='padding:4px 0 10px 22px;color:#64748b;'>↓</div>", unsafe_allow_html=True)
        palette = palette_for("waiting_approval" if approval_status == "waiting_approval" else "pending")
        with st.container(border=True):
            left, center, right = st.columns([0.9, 6.3, 2.0])
            with left:
                st.markdown(
                    f"""
                    <div style="width:40px;height:40px;border-radius:999px;background:{palette['bg']};
                    border:1px solid {palette['border']};display:flex;align-items:center;justify-content:center;
                    font-weight:800;font-size:16px;">S</div>
                    """,
                    unsafe_allow_html=True,
                )
            with center:
                st.markdown(
                    """
                    <div style="font-size:12px;font-weight:800;letter-spacing:0.04em;text-transform:uppercase;
                    color:#facc15;margin-bottom:6px;">검토 운영본부</div>
                    <div style="font-size:22px;font-weight:800;line-height:1.2;margin-bottom:6px;">승인 판단 / 반려 재작업 조정</div>
                    <div style="font-size:14px;opacity:0.9;margin-bottom:8px;">승인이 필요한 산출물을 확인하고, 필요한 경우 재작업 방향을 바로 지시할 수 있습니다.</div>
                    <div style="font-size:13px;font-weight:800;opacity:0.95;margin-bottom:4px;">담당 직원: 오세훈 과장, 남예린 대리</div>
                    <div style="font-size:13px;opacity:0.85;margin-bottom:4px;">맡은 역할: 승인 필요 항목 선별, 반려 사유 분석, 재작업 라우팅</div>
                    <div style="font-size:13px;opacity:0.85;">한 줄 비전: 사람이 꼭 봐야 할 결정만 남기고, 나머지는 흐름이 끊기지 않게 이어갑니다.</div>
                    <div style="margin-top:10px;">
                        <span style='display:inline-flex;align-items:center;padding:4px 8px;border-radius:999px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.08);font-size:12px;font-weight:700;margin:0 6px 6px 0;'>승인 판단팀</span>
                        <span style='display:inline-flex;align-items:center;padding:4px 8px;border-radius:999px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.08);font-size:12px;font-weight:700;margin:0 6px 6px 0;'>재작업 조정팀</span>
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
    summary_left, summary_right = st.columns([1.35, 1.0])
    with summary_left:
        with st.container(border=True):
            st.markdown("##### 오늘 브리핑")
            st.markdown(
                f"""
                - 기준 날짜: **{format_local_date(today_value)}**
                - 대상 국가: **{display_country(selected_country)} ({selected_country})**
                - 실행 방식: **{"자동 모드" if preview_strategy.get("auto_mode") else "수동 모드"}**
                - 기본 공략 방향: **{display_strategy_bias(preview_strategy.get("strategy_bias"))}**
                """
            )
    with summary_right:
        with st.container(border=True):
            st.markdown("##### 이번 실행 해석")
            if preview_strategy.get("auto_mode"):
                st.write(
                    f"탐색 조건을 비워둬서 시스템이 자동으로 공략 패턴을 골랐습니다. "
                    f"이번에는 **{len(preview_strategy.get('selected_patterns', []))}개 패턴**을 우선 검토하고, "
                    f"실제 탐색 문장은 **`{preview_strategy.get('resolved_query', '-')}`** 입니다."
                )
            else:
                st.write(
                    f"직접 입력한 탐색 조건을 기준으로 실행합니다. "
                    f"이번 탐색 문장은 **`{preview_strategy.get('resolved_query', '-')}`** 입니다."
                )

    if preview_strategy.get("auto_mode"):
        st.markdown("**자동 탐색 기준**")
        st.write(
            "탐색 조건이 비어 있어 자동 모드가 켜졌습니다. "
            f"이번 실행에서는 `{preview_strategy.get('resolved_query', '-')}` 기준으로 회사를 찾습니다."
        )
    else:
        st.caption("탐색 조건을 직접 입력한 수동 모드입니다.")

    selected_patterns = preview_strategy.get("selected_patterns", [])
    if selected_patterns:
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

    strategy_snapshot = get_run_strategy_snapshot(latest_run)
    quality_rows = build_quality_rows(latest_run["id"])

    st.write(
        f"실제 사용된 탐색 기준: `{strategy_snapshot.get('resolved_query') or latest_run.get('lead_query') or '-'}`"
    )
    st.caption(quality_summary_text(quality_rows))

    if quality_rows:
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

    labels = [
        f"{row['started_at']} | {display_country(row['target_country'])} | {display_status(row['status'])} | {row['id'][:8]}"
        for row in filtered_runs
    ]
    selected_label = st.selectbox("확인할 실행", labels, index=0, key=f"{key_prefix}_select_run")
    selected_run = filtered_runs[labels.index(selected_label)]

    st.dataframe(
        [
            {
                "시작 시각": row["started_at"],
                "국가": display_country(row["target_country"]),
                "상태": display_status(row["status"]),
                "탐색 모드": "자동" if parse_json_field(row.get("metadata_json"), {}).get("auto_mode") else "수동",
                "탐색 기준": row["lead_query"],
                "검토 대기": row["approval_count"],
                "토큰": row["total_tokens"],
                "비용(USD)": row["estimated_cost_usd"],
                "실행 ID": row["id"],
            }
            for row in filtered_runs
        ],
        hide_index=True,
        use_container_width=True,
    )
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
    if not waiting:
        st.info("검토 대기 중인 항목이 없습니다.")
    else:
        for item in waiting:
            with st.expander(f"{item.get('company_name') or '-'} | {item['title']}"):
                metadata = parse_json_field(item.get("metadata_json"), {})
                bundle_ids = parse_json_field(item.get("asset_bundle_json"), [])
                asset_rows = list_assets_by_ids(bundle_ids)
                st.caption(f"자동발송 판정: {summarize_auto_delivery(metadata)}")
                auto_delivery = parse_json_field(metadata.get("auto_delivery"), {})
                blocked_reasons = auto_delivery.get("blocked_reasons") or []
                if blocked_reasons:
                    st.warning("자동발송 차단 이유: " + " | ".join(blocked_reasons[:3]))

                if asset_rows:
                    proposal_asset = next((row for row in asset_rows if row["asset_type"] == "proposal"), None)
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
                                "파일 위치": row["path"],
                            }
                            for row in asset_rows
                        ],
                        hide_index=True,
                        use_container_width=True,
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
                "재작업 대상": row["reroute_targets_json"],
                "처리 시각": row["decided_at"],
            }
            for row in recent[:20]
        ],
        hide_index=True,
        use_container_width=True,
    )


def render_assets(selected_run: dict[str, Any] | None) -> None:
    st.subheader("산출물")
    assets = list_assets(selected_run["id"] if selected_run else None)
    if not assets:
        st.info("산출물이 아직 없습니다.")
        return

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
                "파일 위치": row["path"],
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

    st.caption(str(asset_path))
    if selected_asset["asset_type"] == "proposal":
        quality = evaluate_proposal_asset(selected_asset)
        summary = f"제안서 품질: {quality['score']}점 ({quality['label']})"
        if quality["missing_sections"]:
            summary += f" | 빠진 섹션: {', '.join(quality['missing_sections'][:4])}"
        st.caption(summary)

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
    st.subheader("운영 설정")
    st.write(f"프로젝트 위치: `{PROJECT_ROOT}`")
    st.write(f"운영 DB: `{DB_PATH}`")
    st.write(f"파이썬 실행 파일: `{resolve_python_executable()}`")
    st.write(f"기본 알림 메일: `{os.environ.get('ALERT_EMAIL_TO', ALERT_EMAIL_DEFAULT)}`")
    st.write(f"현재 저장소 백엔드: `{backend_info['label']}`")
    if backend_info.get("remote_url"):
        st.write(f"Supabase URL: `{backend_info['remote_url']}`")
    if backend_info.get("storage_bucket"):
        st.write(f"Supabase Storage 버킷: `{backend_info['storage_bucket']}`")
    if backend_info["backend"] == "supabase":
        st.info("Notion 매핑은 아직 연결하지 않았습니다. 현재는 Supabase를 운영 원본으로 사용합니다.")
    else:
        st.info("Notion 매핑은 아직 연결하지 않았습니다. 현재는 로컬 SQLite를 운영 원본으로 사용합니다.")
    st.write(f"자동발송 모드: `{auto_send_settings.mode}`")
    st.write(f"자동발송 최소 제안서 점수: `{auto_send_settings.min_proposal_score}`")
    st.write(f"자동발송 PDF 필수 여부: `{auto_send_settings.require_pdf}`")
    st.write(f"자동발송 최대 건수/실행: `{auto_send_settings.max_items_per_run}`")
    if auto_send_settings.canary_email:
        st.write(f"카나리 수신 메일: `{auto_send_settings.canary_email}`")
    st.divider()
    st.markdown("### 구성현황")
    st.caption("메인 파이프라인 부서와 지원 조직이 어떤 역할을 맡는지 정리한 표입니다.")

    for task_name in [
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
    ]:
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
                st.markdown("**참여 직원**")
                for member in members:
                    st.markdown(f"- **{member['name']}** (`{member['crew_label']}`)")
                    st.caption(f"맡은 역할: {member['role']}")
                    st.caption(f"한 줄 비전: {member['vision']}")
                if support:
                    st.markdown(f"**지원팀**: {', '.join(support)}")
                else:
                    st.caption("지원팀 없음")

    st.markdown("### 지원 조직")
    for team in SUPPORT_TEAM_CONFIG:
        with st.expander(f"{team['department']} | {team['status']}", expanded=False):
            for member_name, member_role in team["members"]:
                st.markdown(f"- **{member_name}**: {member_role}")


def main() -> None:
    load_runtime()
    st.set_page_config(page_title="세일즈 운영 콘솔", layout="wide")
    st.title("세일즈 운영 콘솔")
    st.caption(f"오늘 날짜: {format_local_date(date.today())} | 웹에서 실행과 검토를 관리하고, 메일은 알림 용도로만 사용합니다.")
    render_ui_notice()

    running_run = query_running_run()
    latest_run = list_runs(limit=1)
    latest_run = latest_run[0] if latest_run else None

    with st.sidebar:
        st.header("실행 시작")
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
        preview_strategy = build_strategy_snapshot(
            target_country=target_country,
            lead_mode=lead_mode,
            lead_query=lead_query,
        )

        max_companies = st.slider("최대 회사 수", min_value=1, max_value=10, value=2)
        notify_email = st.text_input(
            "알림 받을 메일",
            value=os.environ.get("ALERT_EMAIL_TO", ALERT_EMAIL_DEFAULT),
            key="alert_email_input",
        )
        test_mode = st.checkbox("테스트 모드", value=True)

        if running_run:
            st.warning(
                f"실행 중: {running_run['id'][:8]} | {display_task_name(running_run.get('current_task'))}"
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
                st.success("백그라운드에서 실행을 시작했습니다.")
                st.rerun()

        if st.button("새로고침", use_container_width=True):
            st.rerun()

    top_left, top_right = st.columns([5.2, 1.2])
    with top_right:
        with st.popover("총괄 비서", use_container_width=True):
            render_copilot_panel(latest_run)

    tabs = st.tabs(["오늘의 전략", "실행 현황", "검토 대기", "산출물", "알림", "설정"])

    with tabs[0]:
        render_strategy_tab(
            preview_strategy=preview_strategy,
            selected_country=target_country,
            latest_run=latest_run,
        )

    with tabs[1]:
        render_dashboard(latest_run)
        st.divider()
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
                            f"({get_department_members(row.get('task_name'))[0]['crew_label']})"
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

    with tabs[2]:
        render_approval_queue(st.session_state.get("alert_email_input", ALERT_EMAIL_DEFAULT))

    with tabs[3]:
        selected_run = render_runs("assets_tab")
        render_assets(selected_run or latest_run)

    with tabs[4]:
        render_notifications()

    with tabs[5]:
        render_settings()

    if running_run:
        time.sleep(5)
        st.rerun()


if __name__ == "__main__":
    main()
