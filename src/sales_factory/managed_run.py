from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from sales_factory.crew import SalesFactory
from sales_factory.brand_proof import load_onecation_proof_points
from sales_factory.proposal_quality import evaluate_proposal_path, evaluate_proposal_text
from sales_factory.runtime_assets import build_company_assets, create_approval_queue
from sales_factory.auto_delivery import (
    assess_company_sendability,
    execute_auto_send,
    get_auto_send_settings,
    load_verified_recipients,
)
from sales_factory.output_validation import resolve_sender_name
from sales_factory.runtime_db import (
    PROJECT_ROOT,
    create_run,
    get_run_output_dir,
    get_run,
    get_run_workspace,
    init_db,
    list_assets_by_ids,
    list_approval_items_for_run,
    list_assets,
    list_pending_tasks,
    list_task_costs,
    now_iso,
    record_notification,
    register_tasks,
    summarize_approval_items,
    update_approval_item,
    update_run,
    update_task,
)
from sales_factory.runtime_notifications import send_alert_email, send_slack_message
from sales_factory.slack_review import build_review_ready_slack_blocks
from sales_factory.runtime_supabase import read_asset_text
from sales_factory.strategy_runtime import build_strategy_snapshot

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

MODEL_PRICING_USD_PER_MILLION: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.15, 0.60),
    "gemini-2.5-pro": (1.25, 10.00),
    "gpt-4o": (5.00, 15.00),
    "gpt-4o-mini": (0.15, 0.60),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-opus-4-5": (15.00, 75.00),
    "claude-haiku-4-5": (0.80, 4.00),
}

LLM_RETRY_ATTEMPTS = 3
LLM_RETRY_BASE_DELAY_SECONDS = 5
RETRYABLE_LLM_ERROR_PATTERNS = (
    "503",
    "429",
    "service unavailable",
    "temporarily unavailable",
    "temporarily overloaded",
    "model is overloaded",
    "resource exhausted",
    "resourceexhausted",
    "too many requests",
    "try again later",
)
LLM_OVERLOAD_FALLBACKS: dict[str, tuple[str, ...]] = {
    "gemini-2.5-pro": ("gemini/gemini-2.5-flash", "gemini/gemini-2.5-flash-lite", "openai/gpt-4o-mini"),
    "gemini-2.5-flash": ("gemini/gemini-2.5-flash-lite", "openai/gpt-4o-mini"),
    "gemini-2.5-flash-lite": ("openai/gpt-4o-mini",),
    "claude-sonnet-4-5": ("gemini/gemini-2.5-pro", "openai/gpt-4o-mini"),
    "claude-sonnet-4-20250514": ("gemini/gemini-2.5-pro", "openai/gpt-4o-mini"),
    "claude-3-5-sonnet-20241022": ("gemini/gemini-2.5-pro", "openai/gpt-4o-mini"),
}
LLM_PROVIDER_ENV_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
}

ASSET_TYPE_LABELS = {
    "proposal": "제안서 원본",
    "proposal_docx": "제안서 Word",
    "proposal_pdf": "제안서 PDF",
    "email_sequence": "아웃바운드 메일",
    "marketing_plan": "실행안",
    "competitor_analysis": "시장/경쟁 분석",
}


def parse_json_value(value: Any, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def evaluate_proposal_asset(asset_row: dict[str, Any]) -> dict[str, Any]:
    asset_path = Path(asset_row["path"])
    metadata = parse_json_value(asset_row.get("metadata_json"), {})
    text = read_asset_text(asset_path, metadata)
    if text == "(file missing)":
        return evaluate_proposal_path(asset_path)
    return evaluate_proposal_text(text)


def normalize_model_name(model_name: str | None) -> str | None:
    if not model_name:
        return None
    normalized = model_name.strip()
    if "/" in normalized:
        normalized = normalized.split("/", 1)[1]
    return normalized


def estimate_cost_usd(model_name: str | None, prompt_tokens: int, completion_tokens: int) -> float:
    normalized_name = normalize_model_name(model_name)
    if not normalized_name:
        return 0.0
    pricing = MODEL_PRICING_USD_PER_MILLION.get(normalized_name)
    if not pricing:
        return 0.0
    input_rate, output_rate = pricing
    return round((prompt_tokens / 1_000_000 * input_rate) + (completion_tokens / 1_000_000 * output_rate), 6)


def infer_llm_provider(model_name: str | None) -> str:
    if not model_name:
        return ""
    lowered = model_name.strip().lower()
    if "/" in lowered:
        return lowered.split("/", 1)[0]
    if lowered.startswith("gemini"):
        return "gemini"
    if lowered.startswith("gpt"):
        return "openai"
    if lowered.startswith("claude"):
        return "anthropic"
    return ""


def has_llm_provider(provider_name: str) -> bool:
    if not provider_name:
        return False
    env_key = LLM_PROVIDER_ENV_KEYS.get(provider_name)
    if not env_key:
        return True
    return bool(os.environ.get(env_key, "").strip())


def is_retryable_llm_error(exc: Exception) -> bool:
    lowered = str(exc).lower()
    return any(pattern in lowered for pattern in RETRYABLE_LLM_ERROR_PATTERNS)


def choose_llm_fallback(model_name: str | None) -> str | None:
    normalized_name = normalize_model_name(model_name)
    if not normalized_name:
        return None
    for candidate in LLM_OVERLOAD_FALLBACKS.get(normalized_name, ()):
        provider_name = infer_llm_provider(candidate)
        if has_llm_provider(provider_name):
            return candidate
    return None


def build_llm_retry_overrides(task_plan: list[dict[str, Any]]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for task in task_plan:
        model_name = task.get("model_name")
        fallback = choose_llm_fallback(model_name)
        if not fallback:
            continue
        if normalize_model_name(fallback) == normalize_model_name(model_name):
            continue
        overrides[str(model_name)] = fallback
    return overrides


@contextmanager
def temporary_llm_model_overrides(overrides: dict[str, str]):
    original = os.environ.get("SALES_FACTORY_LLM_MODEL_OVERRIDES")
    if overrides:
        os.environ["SALES_FACTORY_LLM_MODEL_OVERRIDES"] = json.dumps(overrides, ensure_ascii=False)
    else:
        os.environ.pop("SALES_FACTORY_LLM_MODEL_OVERRIDES", None)
    try:
        yield
    finally:
        if original is None:
            os.environ.pop("SALES_FACTORY_LLM_MODEL_OVERRIDES", None)
        else:
            os.environ["SALES_FACTORY_LLM_MODEL_OVERRIDES"] = original


def resolve_python_executable() -> str:
    local_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if local_python.exists():
        return str(local_python)
    return sys.executable


@contextmanager
def working_directory(path: Path):
    original = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original)


def run_pdf_generation(*, workspace_dir: Path, output_dir: Path, proposal_language: str | None = None) -> None:
    script_path = PROJECT_ROOT / "generate_pdf_playwright.py"
    if not script_path.exists():
        return
    proposal_path = workspace_dir / "proposal.md"
    if not proposal_path.exists():
        return
    command = [
        resolve_python_executable(),
        str(script_path),
        "--proposal",
        str(proposal_path),
        "--out",
        str(output_dir),
    ]
    if proposal_language:
        command.extend(["--language", proposal_language])
    require_pdf = os.environ.get("SALES_FACTORY_REQUIRE_PDF", "").strip().lower() in {"1", "true", "yes"}
    if require_pdf:
        command.append("--require-pdf")
    subprocess.run(command, cwd=str(PROJECT_ROOT), check=False)


def build_inputs(args: argparse.Namespace) -> dict[str, Any]:
    strategy_snapshot = build_strategy_snapshot(
        target_country=args.target_country,
        lead_mode=args.lead_mode or "region_or_industry",
        lead_query=args.lead_query or "",
    )
    payload: dict[str, Any] = {
        "lead_mode": args.lead_mode or "region_or_industry",
        "lead_query": strategy_snapshot["resolved_query"],
        "lead_query_input": args.lead_query or "",
        "max_companies": str(args.max_companies or 1),
        "current_year": str(datetime.now().year),
        "sender_name": resolve_sender_name(),
        "target_country": args.target_country,
        "proposal_language": args.proposal_language,
        "currency": args.currency,
        "onecation_proof_points": load_onecation_proof_points(),
        "segment_id": getattr(args, "segment_id", "") or "",
        "segment_label": getattr(args, "segment_label", "") or "",
        "segment_brief": getattr(args, "segment_brief", "") or "",
        "alert_email_to": args.notify_email,
        "test_mode": args.test_mode,
        "auto_mode": strategy_snapshot["auto_mode"],
        "strategy_snapshot": strategy_snapshot,
    }
    return payload


def _split_pipe_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    cells = re.split(r"(?<!\\)\|", stripped)
    return [cell.replace("\\|", "|").strip() for cell in cells]


def _read_markdown_table_rows(path: Path) -> tuple[list[str], list[list[str]], int]:
    if not path.exists():
        return [], [], -1

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header_index = next((index for index, line in enumerate(lines) if line.strip().startswith("| company_name |")), -1)
    if header_index < 0 or header_index + 1 >= len(lines):
        return [], [], -1

    headers = _split_pipe_row(lines[header_index])
    rows: list[list[str]] = []
    for line in lines[header_index + 2 :]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = _split_pipe_row(line)
        if len(cells) != len(headers):
            continue
        rows.append(cells)
    return headers, rows, header_index


def sanitize_identity_disambiguation_output(workspace_dir: Path) -> tuple[int, int]:
    disambiguation_path = workspace_dir / "identity_disambiguation.md"
    headers, rows, header_index = _read_markdown_table_rows(disambiguation_path)
    if header_index < 0 or "disambiguation_status" not in headers:
        return 0, 0

    status_index = headers.index("disambiguation_status")
    retained_rows = [row for row in rows if row[status_index].lower() == "selected"]
    lines = disambiguation_path.read_text(encoding="utf-8", errors="replace").splitlines()
    rewritten = [
        f"TOTAL_COMPANIES: {len(retained_rows)}",
        lines[header_index],
        lines[header_index + 1],
        *[f"| {' | '.join(row)} |" for row in retained_rows],
        "",
    ]
    disambiguation_path.write_text("\n".join(rewritten), encoding="utf-8")
    return len(rows), len(retained_rows)


def _normalize_identity_blank(value: str) -> bool:
    return value.strip().lower() in {"", "-", "n/a", "na", "none", "none found", "no conflict"}


def enforce_identity_disambiguation_guard(workspace_dir: Path, *, lead_mode: str) -> None:
    disambiguation_path = workspace_dir / "identity_disambiguation.md"
    headers, rows, _ = _read_markdown_table_rows(disambiguation_path)
    if not rows:
        raise RuntimeError("Identity disambiguation did not retain any company. Manual review is required before proposal generation.")

    if lead_mode != "company_name":
        return

    if len(rows) != 1:
        raise RuntimeError("Exact-company mode requires exactly one disambiguated company. Manual review is required before proposal generation.")

    row = dict(zip(headers, rows[0]))
    if row.get("disambiguation_status", "").strip().lower() != "selected":
        raise RuntimeError("Exact-company mode did not produce a selected identity record.")

    if row.get("identity_confidence", "").strip().lower() != "high":
        raise RuntimeError("Exact-company mode requires high identity confidence before proposal generation.")

    corroboration_fields = [
        row.get("official_address", ""),
        row.get("official_phone", ""),
        row.get("official_email_domain", ""),
        row.get("homepage_url_if_any", ""),
    ]
    corroboration_count = sum(0 if _normalize_identity_blank(value) else 1 for value in corroboration_fields)
    if corroboration_count < 2:
        raise RuntimeError("Identity disambiguation did not produce enough corroborating address/contact evidence.")

    has_digital_anchor = not _normalize_identity_blank(row.get("official_email_domain", "")) or not _normalize_identity_blank(
        row.get("homepage_url_if_any", "")
    )
    if not has_digital_anchor:
        raise RuntimeError("Exact-company mode requires an official homepage or email-domain anchor before proposal generation.")

    if _normalize_identity_blank(row.get("identity_match_basis", "")):
        raise RuntimeError("Identity disambiguation did not explain why this company was selected.")

    if not _normalize_identity_blank(row.get("conflict_notes", "")):
        raise RuntimeError("Identity disambiguation detected unresolved conflicts. Manual review is required before proposal generation.")


def validate_identity_disambiguation_output(workspace_dir: Path, *, lead_mode: str) -> None:
    raw_rows, retained_rows = sanitize_identity_disambiguation_output(workspace_dir)
    if raw_rows and retained_rows == 0:
        raise RuntimeError("Identity disambiguation rejected every company. Manual review is required before proposal generation.")
    enforce_identity_disambiguation_guard(workspace_dir, lead_mode=lead_mode)


def sanitize_lead_verification_output(workspace_dir: Path) -> tuple[int, int]:
    verification_path = workspace_dir / "lead_verification.md"
    headers, rows, header_index = _read_markdown_table_rows(verification_path)
    if header_index < 0:
        return 0, 0

    if "verification_status" not in headers:
        return 0, 0
    status_index = headers.index("verification_status")

    retained_rows = [cells for cells in rows if cells[status_index].lower() in {"verified", "corrected"}]
    lines = verification_path.read_text(encoding="utf-8", errors="replace").splitlines()

    rewritten = [
        f"TOTAL_COMPANIES: {len(retained_rows)}",
        lines[header_index],
        lines[header_index + 1],
        *[f"| {' | '.join(row)} |" for row in retained_rows],
        "",
    ]
    verification_path.write_text("\n".join(rewritten), encoding="utf-8")
    return len(rows), len(retained_rows)


def materialize_task_output_snapshot(output_path: str, raw_text: str) -> None:
    if not output_path or not raw_text.strip():
        return
    path = Path(output_path)
    if path.exists() and path.read_text(encoding="utf-8", errors="replace").strip():
        return
    path.write_text(raw_text, encoding="utf-8")


def parse_task_plan(crew: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, task in enumerate(crew.tasks, start=1):
        agent = task.agent
        llm = getattr(agent, "llm", None)
        model_name = getattr(llm, "model", None)
        rows.append(
            {
                "task_name": task.name or f"task_{idx}",
                "task_order": idx,
                "agent_role": getattr(agent, "role", None),
                "model_name": normalize_model_name(model_name),
                "status": "pending",
            }
        )
    return rows


def send_runtime_notification(run_id: str, recipient: str, subject: str, body: str) -> None:
    if not recipient:
        return
    try:
        send_alert_email(subject=subject, body_text=body, to_email=recipient)
        record_notification(run_id, "email", "sent", subject, recipient, {"body": body})
    except Exception as exc:  # pragma: no cover
        record_notification(
            run_id,
            "email",
            "failed",
            subject,
            recipient,
            {"body": body, "error": str(exc)},
        )


def build_review_ready_email(
    *,
    run_id: str,
    target_country: str,
    inputs: dict[str, Any],
    approval_count: int,
    total_tokens: int,
    estimated_cost: float,
) -> tuple[str, str]:
    approval_items = sorted(
        list_approval_items_for_run(run_id, status="waiting_approval"),
        key=lambda row: (-int(row.get("priority") or 0), row.get("created_at") or ""),
    )
    asset_rows = sorted(list_assets(run_id), key=lambda row: row.get("created_at") or "")
    assets_by_id = {row["id"]: row for row in asset_rows}
    selected_patterns = (inputs.get("strategy_snapshot") or {}).get("selected_patterns") or []
    focus_names = ", ".join(pattern.get("pattern_name", "") for pattern in selected_patterns[:2] if pattern.get("pattern_name"))
    subject_target = approval_items[0]["company_name"] if approval_count == 1 and approval_items else target_country
    subject = f"[세일즈 운영 콘솔] 검토 요청 {approval_count}건 | {subject_target}"

    lines = [
        "검토가 필요한 산출물이 준비되었습니다.",
        "",
        "오늘 실행 요약",
        f"- 실행 ID: {run_id}",
        f"- 대상 국가: {target_country}",
        f"- 실행 방식: {'자동 모드' if inputs.get('auto_mode') else '직접 지정 모드'}",
        f"- 실제 탐색 기준: {inputs.get('lead_query', '-')}",
        f"- 현재 검토 대기: {approval_count}건",
        f"- 사용 토큰: {total_tokens:,}",
        f"- 예상 비용: ${estimated_cost:.6f}",
    ]
    if focus_names:
        lines.append(f"- 이번에 우선 본 공략 패턴: {focus_names}")

    lines.extend(
        [
            "",
            "누가 검토를 요청했나",
            "- 제안서 작성부와 아웃바운드 메일부가 초안을 만들었고, 검토 운영본부가 최종 판단을 요청합니다.",
            "",
            "지금 확인할 항목",
        ]
    )

    for index, item in enumerate(approval_items, start=1):
        related_ids = parse_json_value(item.get("asset_bundle_json"), [])
        related_assets = [assets_by_id[asset_id] for asset_id in related_ids if asset_id in assets_by_id]
        asset_names = [ASSET_TYPE_LABELS.get(asset["asset_type"], asset["asset_type"]) for asset in related_assets]

        review_reason = "외부 발송 전 최종 검토가 필요합니다."
        proposal_asset = next((asset for asset in related_assets if asset["asset_type"] == "proposal"), None)
        if proposal_asset:
            quality = evaluate_proposal_asset(proposal_asset)
            review_reason = f"제안서 품질 {quality['score']}점 ({quality['label']})"
            if quality["missing_sections"]:
                review_reason += f", 빠진 섹션: {', '.join(quality['missing_sections'][:3])}"

        lines.extend(
            [
                f"{index}. {item.get('company_name') or item['title']}",
                f"   - 검토 이유: {review_reason}",
                f"   - 준비된 산출물: {', '.join(asset_names) if asset_names else '산출물 확인 필요'}",
                "   - 지금 결정할 것: 승인 / 보완 요청",
            ]
        )

    lines.extend(
        [
            "",
            "확인 위치",
            "- 세일즈 운영 콘솔 > 검토 대기",
            "- 같은 내용은 실행 현황의 검토 운영본부 카드에서도 바로 처리할 수 있습니다.",
            "",
            "권장 순서",
            "1. 회사별 제안서와 메일 초안 확인",
            "2. 빠진 내용이 있으면 보완 요청",
            "3. 문제 없으면 승인",
        ]
    )
    return subject, "\n".join(lines)


def build_review_ready_email_v2(
    *,
    run_id: str,
    target_country: str,
    inputs: dict[str, Any],
    trigger_source: str,
    approval_count: int,
    total_tokens: int,
    estimated_cost: float,
) -> tuple[str, str]:
    approval_items = sorted(
        list_approval_items_for_run(run_id, status="waiting_approval"),
        key=lambda row: (-int(row.get("priority") or 0), row.get("created_at") or ""),
    )
    asset_rows = sorted(list_assets(run_id), key=lambda row: row.get("created_at") or "")
    assets_by_id = {row["id"]: row for row in asset_rows}
    selected_patterns = (inputs.get("strategy_snapshot") or {}).get("selected_patterns") or []
    focus_names = ", ".join(
        pattern.get("pattern_name", "") for pattern in selected_patterns[:2] if pattern.get("pattern_name")
    )
    subject_target = approval_items[0]["company_name"] if approval_count == 1 and approval_items else (
        inputs.get("lead_query") or target_country
    )
    subject = f"[세일즈 운영 콘솔] 검토 요청 {approval_count}건 | {subject_target}"

    if trigger_source.startswith("approval_rework"):
        request_context = "보완 요청 후 다시 올라온 재작업 결과입니다."
    elif inputs.get("auto_mode"):
        request_context = "자동 탐색 결과 중 외부 발송 전에 확인이 필요한 산출물이 준비되었습니다."
    else:
        request_context = "외부 발송 전에 확인이 필요한 산출물이 준비되었습니다."

    lines = [
        "검토 운영본부 보고",
        request_context,
        "",
        "이번 실행 요약",
        f"- 실행 ID: {run_id}",
        f"- 대상 국가: {target_country}",
        f"- 실행 방식: {'자동 모드' if inputs.get('auto_mode') else '직접 지정 모드'}",
        f"- 실제 탐색 기준: {inputs.get('lead_query', '-')}",
        f"- 현재 검토 대기: {approval_count}건",
        f"- 사용 토큰: {total_tokens:,}",
        f"- 예상 비용: ${estimated_cost:.6f}",
    ]
    if focus_names:
        lines.append(f"- 이번에 우선 본 공략 패턴: {focus_names}")

    lines.extend(
        [
            "",
            "왜 이 메일이 왔나",
            "- 제안서 작성부와 아웃바운드 메일부가 초안을 만들었고, 검토 운영본부가 최종 판단을 요청합니다.",
            "",
            "지금 확인할 항목",
        ]
    )

    review_items = approval_items or [
        {
            "title": inputs.get("lead_query") or target_country,
            "company_name": inputs.get("lead_query") or target_country,
            "asset_bundle_json": "[]",
        }
    ]

    for index, item in enumerate(review_items, start=1):
        related_ids = parse_json_value(item.get("asset_bundle_json"), [])
        metadata = parse_json_value(item.get("metadata_json"), {})
        validation_issues = parse_json_value(metadata.get("validation_issues"), [])

        related_assets = [assets_by_id[asset_id] for asset_id in related_ids if asset_id in assets_by_id]
        asset_names = [ASSET_TYPE_LABELS.get(asset["asset_type"], asset["asset_type"]) for asset in related_assets]
        review_reason = "외부 발송 전 최종 검토가 필요합니다."
        check_points = [
            "제안서와 메일 초안이 현재 회사 상황에 맞는지 확인",
            "빠진 내용이나 어색한 표현이 없는지 확인",
            "문제 없으면 승인, 부족하면 보완 요청",
        ]

        proposal_asset = next((asset for asset in related_assets if asset["asset_type"] == "proposal"), None)
        if proposal_asset:
            quality = evaluate_proposal_asset(proposal_asset)
            review_reason = f"제안서 점수 {quality['score']}점 ({quality['label']})"
            if quality["missing_sections"]:
                missing_text = ", ".join(quality["missing_sections"][:3])
                review_reason += f", 빠진 섹션: {missing_text}"
                check_points.insert(1, f"빠진 섹션({missing_text})이 실제로 보완됐는지 확인")
        if validation_issues:
            issue_text = "; ".join(validation_issues[:2])
            review_reason += f", validation 경고: {issue_text}"
            check_points.insert(1, f"placeholder/언어 경고({issue_text})가 실제 수정됐는지 확인")

        primary_name = item.get("company_name") or item["title"]
        asset_summary = ", ".join(asset_names) if asset_names else "산출물 확인 필요"
        lines.extend(
            [
                f"{index}. {primary_name}",
                f"   - 검토 이유: {review_reason}",
                f"   - 준비한 산출물: {asset_summary}",
                "   - 이번에 판단해주면 되는 것:",
            ]
        )
        for point_index, point in enumerate(check_points, start=1):
            lines.append(f"     {point_index}) {point}")
        lines.append("   - 콘솔에서 바로 누를 버튼: 승인 / 보완 요청 / 테스트 메일 보내기")

    lines.extend(
        [
            "",
            "어디에서 처리하면 되나",
            "- 세일즈 운영 콘솔 > 검토 대기",
            "- 같은 내용은 실행 현황 > 검토 운영본부 카드에서도 바로 처리할 수 있습니다.",
            "",
            "권장 순서",
            "1. 회사별 제안서와 메일 초안을 확인합니다.",
            "2. 빠진 내용이 있으면 보완 요청으로 메모를 남깁니다.",
            "3. 문제 없으면 승인합니다.",
        ]
    )
    return subject, "\n".join(lines)


def build_failure_email(
    *,
    run_id: str,
    target_country: str,
    inputs: dict[str, Any],
    trigger_source: str,
    error_message: str,
) -> tuple[str, str]:
    subject_target = inputs.get("lead_query") or target_country
    subject = f"[세일즈 운영 콘솔] 실행 실패 알림 | {subject_target}"
    if trigger_source.startswith("approval_rework"):
        request_context = "보완 요청 후 재작업을 다시 돌리던 중 오류가 발생했습니다."
    else:
        request_context = "이번 실행이 끝까지 완료되지 못했습니다."

    body = "\n".join(
        [
            "운영 오류 보고",
            request_context,
            "",
            "실행 개요",
            f"- 실행 ID: {run_id}",
            f"- 대상 국가: {target_country}",
            f"- 실행 방식: {'자동 모드' if inputs.get('auto_mode') else '직접 지정 모드'}",
            f"- 실제 탐색 기준: {inputs.get('lead_query', '-')}",
            "",
            "확인된 오류",
            f"- {error_message}",
            "",
            "지금 하면 되는 일",
            "1. 세일즈 운영 콘솔 > 실행 기록에서 실패한 실행을 확인합니다.",
            "2. 같은 회사인지, 재시도해도 되는지 확인합니다.",
            "3. 필요하면 다시 실행하거나 메모를 남긴 뒤 재작업 흐름을 다시 태웁니다.",
        ]
    )
    return subject, body


def process_auto_delivery_queue(
    *,
    run_id: str,
    workspace_dir: Path,
    test_mode: bool,
) -> dict[str, Any]:
    settings = get_auto_send_settings()
    waiting_items = list_approval_items_for_run(run_id, status="waiting_approval")
    verified_recipients = load_verified_recipients(workspace_dir)
    summary: dict[str, Any] = {
        "mode": settings.mode,
        "total_items": len(waiting_items),
        "eligible_count": 0,
        "blocked_count": 0,
        "shadow_simulated_count": 0,
        "canary_sent_count": 0,
        "live_sent_count": 0,
        "manual_review_count": 0,
        "items": [],
    }

    for index, item in enumerate(waiting_items):
        metadata = parse_json_value(item.get("metadata_json"), {})
        asset_rows = list_assets_by_ids(parse_json_value(item.get("asset_bundle_json"), []))
        validation_issues = parse_json_value(metadata.get("validation_issues"), [])
        assessment = assess_company_sendability(
            company_name=item.get("company_name") or item["title"],
            asset_rows=asset_rows,
            validation_issues=validation_issues,
            verified_recipients=verified_recipients,
            settings=settings,
            test_mode=test_mode,
        )
        item_result: dict[str, Any] = assessment.to_metadata()
        item_result["approval_item_id"] = item["id"]

        if assessment.eligible:
            summary["eligible_count"] += 1
        else:
            summary["blocked_count"] += 1
            summary["manual_review_count"] += 1

        if settings.mode in {"shadow", "canary", "live"} and assessment.eligible and index < settings.max_items_per_run:
            try:
                delivery_result = execute_auto_send(
                    asset_rows=asset_rows,
                    assessment=assessment,
                    settings=settings,
                )
                item_result["delivery_result"] = delivery_result
                notification_status = delivery_result.get("status", "sent")
                notification_subject = delivery_result.get("subject", item["title"])
                notification_recipient = delivery_result.get("recipient", "")
                record_notification(
                    run_id,
                    "auto_delivery",
                    notification_status,
                    notification_subject,
                    notification_recipient,
                    {
                        "approval_item_id": item["id"],
                        "company_name": item.get("company_name"),
                        "mode": settings.mode,
                        "intended_recipient": assessment.recipient_email,
                        "blocked_reasons": assessment.blocked_reasons,
                        "attachments": delivery_result.get("attachments", []),
                    },
                )
                if settings.mode == "shadow":
                    summary["shadow_simulated_count"] += 1
                elif settings.mode == "canary" and delivery_result.get("status") == "sent":
                    summary["canary_sent_count"] += 1
                elif settings.mode == "live" and delivery_result.get("status") == "sent":
                    summary["live_sent_count"] += 1
                    update_approval_item(
                        item["id"],
                        status="approved",
                        decided_at=now_iso(),
                        metadata_json={**metadata, "auto_delivery": item_result},
                    )
                    summary["items"].append(item_result)
                    continue
            except Exception as exc:
                item_result["delivery_result"] = {
                    "mode": settings.mode,
                    "status": "failed",
                    "recipient": assessment.recipient_email,
                    "error": str(exc),
                }
                record_notification(
                    run_id,
                    "auto_delivery",
                    "failed",
                    f"Auto-delivery failed for {item.get('company_name') or item['title']}",
                    assessment.recipient_email,
                    {
                        "approval_item_id": item["id"],
                        "company_name": item.get("company_name"),
                        "mode": settings.mode,
                        "error": str(exc),
                    },
                )
                summary["manual_review_count"] += 1
        elif settings.mode in {"shadow", "canary", "live"} and not assessment.eligible:
            record_notification(
                run_id,
                "auto_delivery",
                "blocked",
                f"Auto-delivery blocked for {item.get('company_name') or item['title']}",
                assessment.recipient_email,
                {
                    "approval_item_id": item["id"],
                    "company_name": item.get("company_name"),
                    "mode": settings.mode,
                    "blocked_reasons": assessment.blocked_reasons,
                },
            )
        elif settings.mode in {"shadow", "canary", "live"} and assessment.eligible:
            item_result["delivery_result"] = {
                "mode": settings.mode,
                "status": "deferred",
                "recipient": assessment.recipient_email,
                "reason": f"max_items_per_run={settings.max_items_per_run}",
            }
            summary["manual_review_count"] += 1

        update_approval_item(
            item["id"],
            metadata_json={**metadata, "auto_delivery": item_result},
        )
        summary["items"].append(item_result)

    summary_counts = summarize_approval_items(run_id)
    summary["remaining_waiting_count"] = int(summary_counts.get("waiting_count") or 0)
    summary["approved_count"] = int(summary_counts.get("approved_count") or 0)
    summary["rejected_count"] = int(summary_counts.get("rejected_count") or 0)
    return summary


def run_managed(args: argparse.Namespace) -> str:
    init_db()
    run_id = str(uuid.uuid4())
    workspace_dir = get_run_workspace(run_id)
    output_dir = get_run_output_dir(run_id)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    inputs = build_inputs(args)

    # Create the run record first so any init failure is visible in the dashboard
    create_run(
        run_id,
        {
            "crew_name": "SalesFactory",
            "trigger_source": args.trigger_source,
            "status": "running",
            "lead_mode": inputs.get("lead_mode"),
            "lead_query": inputs.get("lead_query"),
            "target_country": inputs.get("target_country"),
            "proposal_language": inputs.get("proposal_language"),
            "currency": inputs.get("currency"),
            "max_companies": int(inputs.get("max_companies", 0) or 0),
            "test_mode": args.test_mode,
            "started_at": now_iso(),
            "last_heartbeat_at": now_iso(),
            "inputs_json": inputs,
            "metadata_json": {
                "notify_email": args.notify_email,
                "auto_mode": inputs.get("auto_mode", False),
                "strategy_snapshot": inputs.get("strategy_snapshot", {}),
                "segment_id": inputs.get("segment_id", ""),
                "segment_label": inputs.get("segment_label", ""),
                "log_path": getattr(args, "log_path", "") or "",
                "workspace_dir": str(workspace_dir),
                "output_dir": str(output_dir),
            },
        },
    )

    _country = args.target_country or "-"
    _mode = "[테스트]" if args.test_mode else "[실제]"
    send_slack_message(
        f"🚀 {_mode} 파이프라인 시작 | 국가: {_country} | 최대 {args.max_companies}개 기업 | ID: {run_id[:8]}"
    )

    stop_event = threading.Event()

    def heartbeat() -> None:
        while not stop_event.wait(5):
            update_run(run_id, last_heartbeat_at=now_iso())

    def build_task_callback(current_crew: Any, task_lookup: dict[str, Any], task_sequence: list[str]):
        def handle_task_callback(task_output: Any) -> None:
            task_name = getattr(task_output, "name", None)
            if not task_name and task_sequence:
                pending = list_pending_tasks(run_id)
                if pending:
                    task_name = pending[0]["task_name"]
            if not task_name:
                return
            task_row = task_lookup.get(task_name, {})
            task_obj = next((task for task in current_crew.tasks if task.name == task_name), None)
            agent = getattr(task_obj, "agent", None)
            llm = getattr(agent, "llm", None)
            output_path = ""
            if task_obj and getattr(task_obj, "output_file", None):
                output_path = str(workspace_dir / task_obj.output_file)
            raw_text = getattr(task_output, "raw", "") or ""
            materialize_task_output_snapshot(output_path, raw_text)

            if task_name == "identity_disambiguation_task":
                validate_identity_disambiguation_output(
                    workspace_dir,
                    lead_mode=str(inputs.get("lead_mode", "region_or_industry") or "region_or_industry"),
                )
            if task_name == "lead_verification_task":
                raw_rows, retained_rows = sanitize_lead_verification_output(workspace_dir)
                if raw_rows and retained_rows == 0:
                    raise RuntimeError("Lead verification rejected every company. Manual review is required before proposal generation.")

            usage = llm.get_token_usage_summary() if llm and hasattr(llm, "get_token_usage_summary") else None
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
            total_tokens = int(getattr(usage, "total_tokens", 0) or 0)
            model_name = task_row.get("model_name")
            estimated_cost = estimate_cost_usd(model_name, prompt_tokens, completion_tokens)
            update_task(
                run_id,
                task_name,
                status="completed",
                finished_at=now_iso(),
                summary=getattr(task_output, "summary", "") or task_name,
                excerpt=raw_text[:1500],
                output_path=output_path,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=estimated_cost,
            )

            next_task_name = None
            next_agent_role = None
            for idx, known_name in enumerate(task_sequence):
                if known_name != task_name:
                    continue
                if idx + 1 < len(task_sequence):
                    next_task_name = task_sequence[idx + 1]
                    next_agent_role = task_lookup[next_task_name].get("agent_role")
                break

            if next_task_name:
                update_task(
                    run_id,
                    next_task_name,
                    status="running",
                    started_at=now_iso(),
                )

            update_run(
                run_id,
                current_task=next_task_name,
                current_agent=next_agent_role,
                last_heartbeat_at=now_iso(),
            )

        return handle_task_callback

    def prepare_crew_for_attempt(model_overrides: dict[str, str]) -> tuple[Any, list[dict[str, Any]]]:
        with temporary_llm_model_overrides(model_overrides):
            sales_factory = SalesFactory()
            crew = sales_factory.crew()
        crew.tasks = [task for task in crew.tasks if task.name != "notion_logging_task"]
        task_plan = parse_task_plan(crew)
        register_tasks(run_id, task_plan)
        if task_plan:
            first = task_plan[0]
            update_task(run_id, first["task_name"], status="running", started_at=now_iso())
            update_run(
                run_id,
                current_task=first["task_name"],
                current_agent=first["agent_role"],
                last_heartbeat_at=now_iso(),
            )
        task_lookup = {item["task_name"]: item for item in task_plan}
        task_sequence = [item["task_name"] for item in task_plan]
        crew.task_callback = build_task_callback(crew, task_lookup, task_sequence)
        return crew, task_plan

    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()

    try:
        result = None
        retry_overrides: dict[str, str] = {}
        for attempt in range(LLM_RETRY_ATTEMPTS):
            task_plan: list[dict[str, Any]] = []
            try:
                crew, task_plan = prepare_crew_for_attempt(retry_overrides)
                with working_directory(workspace_dir):
                    result = crew.kickoff(inputs=inputs)
                break
            except Exception as exc:
                if attempt >= LLM_RETRY_ATTEMPTS - 1 or not is_retryable_llm_error(exc):
                    raise
                next_overrides = build_llm_retry_overrides(task_plan)
                if not next_overrides:
                    raise
                delay_seconds = LLM_RETRY_BASE_DELAY_SECONDS * (2**attempt)
                record_notification(
                    run_id,
                    "llm_retry",
                    "retrying",
                    f"Retrying transient LLM failure ({attempt + 2}/{LLM_RETRY_ATTEMPTS})",
                    "",
                    {
                        "attempt": attempt + 2,
                        "max_attempts": LLM_RETRY_ATTEMPTS,
                        "delay_seconds": delay_seconds,
                        "error": str(exc)[:500],
                        "model_overrides": next_overrides,
                    },
                )
                time.sleep(delay_seconds)
                retry_overrides = next_overrides

        if result is None:
            raise RuntimeError("Managed run ended without a crew result.")
        validate_identity_disambiguation_output(
            workspace_dir,
            lead_mode=str(inputs.get("lead_mode", "region_or_industry") or "region_or_industry"),
        )
        raw_rows, retained_rows = sanitize_lead_verification_output(workspace_dir)
        if raw_rows and retained_rows == 0:
            raise RuntimeError("Lead verification rejected every company. Manual review is required before proposal generation.")
        run_pdf_generation(
            workspace_dir=workspace_dir,
            output_dir=output_dir,
            proposal_language=inputs.get("proposal_language"),
        )
        company_assets, validation_issues = build_company_assets(
            run_id,
            workspace_dir=workspace_dir,
            output_dir=output_dir,
            proposal_language=inputs.get("proposal_language"),
        )
        for company_name, issues in sorted(validation_issues.items()):
            record_notification(
                run_id,
                "delivery_guard",
                "warning",
                f"Delivery guard flagged {company_name}",
                "",
                {
                    "company_name": company_name,
                    "issues": issues,
                },
            )
        approval_count = create_approval_queue(run_id, company_assets, validation_issues)
        run_row = get_run(run_id)
        run_metadata = parse_json_value(run_row.get("metadata_json") if run_row else None, {})
        auto_delivery_summary = process_auto_delivery_queue(
            run_id=run_id,
            workspace_dir=workspace_dir,
            test_mode=bool(args.test_mode),
        )
        approval_count = int(auto_delivery_summary.get("remaining_waiting_count") or approval_count)
        usage = getattr(result, "token_usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", 0) or 0)
        cached_prompt_tokens = int(getattr(usage, "cached_prompt_tokens", 0) or 0)
        successful_requests = int(getattr(usage, "successful_requests", 0) or 0)

        task_rows = list_task_costs(run_id)
        estimated_cost = round(sum(float(row["estimated_cost_usd"] or 0) for row in task_rows), 6)
        final_status = "waiting_approval" if approval_count else "completed"
        if (
            approval_count == 0
            and auto_delivery_summary.get("mode") == "live"
            and int(auto_delivery_summary.get("live_sent_count") or 0) > 0
        ):
            final_status = "auto_sent"
        run_metadata["auto_delivery_summary"] = auto_delivery_summary
        update_run(
            run_id,
            status=final_status,
            finished_at=now_iso(),
            last_heartbeat_at=now_iso(),
            current_task=None,
            current_agent=None,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cached_prompt_tokens=cached_prompt_tokens,
            successful_requests=successful_requests,
            estimated_cost_usd=estimated_cost,
            approval_count=approval_count,
            metadata_json=run_metadata,
        )

        if args.notify_email:
            subject, body = build_review_ready_email_v2(
                run_id=run_id,
                target_country=args.target_country,
                inputs=inputs,
                trigger_source=args.trigger_source,
                approval_count=approval_count,
                total_tokens=total_tokens,
                estimated_cost=estimated_cost,
            )
            send_runtime_notification(run_id, args.notify_email, subject, body)

        if approval_count:
            slack_blocks = build_review_ready_slack_blocks(
                run_id=run_id,
                target_country=args.target_country,
                inputs=inputs,
                approval_count=approval_count,
                total_tokens=total_tokens,
                estimated_cost=estimated_cost,
            )
            send_slack_message(
                f"✅ 파이프라인 완료 — 검토 대기 {approval_count}건 | 국가: {args.target_country} | "
                f"비용: ${estimated_cost:.4f} | ID: {run_id[:8]}",
                blocks=slack_blocks,
            )
        else:
            send_slack_message(
                f"✅ 파이프라인 완료 | 국가: {args.target_country} | "
                f"비용: ${estimated_cost:.4f} | ID: {run_id[:8]}"
            )
        return run_id
    except Exception as exc:
        update_run(
            run_id,
            status="failed",
            finished_at=now_iso(),
            last_heartbeat_at=now_iso(),
            current_task=None,
            current_agent=None,
            error_message="".join(traceback.format_exception_only(type(exc), exc)).strip(),
        )
        if args.notify_email:
            subject, body = build_failure_email(
                run_id=run_id,
                target_country=args.target_country,
                inputs=inputs,
                trigger_source=args.trigger_source,
                error_message=str(exc),
            )
            send_runtime_notification(run_id, args.notify_email, subject, body)
        send_slack_message(
            f"❌ 파이프라인 실패 | 국가: {args.target_country} | ID: {run_id[:8]}\n오류: {str(exc)[:200]}"
        )
        raise
    finally:
        stop_event.set()
        heartbeat_thread.join(timeout=1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Managed Sales Factory runtime")
    parser.add_argument("--trigger-source", default="dashboard")
    parser.add_argument("--lead-mode", default="region_or_industry")
    parser.add_argument("--lead-query", default="")
    parser.add_argument("--max-companies", type=int, default=2)
    parser.add_argument("--target-country", default="US")
    parser.add_argument("--proposal-language", default="en")
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--segment-id", default="")
    parser.add_argument("--segment-label", default="")
    parser.add_argument("--segment-brief", default="")
    parser.add_argument("--log-path", default="")
    parser.add_argument("--notify-email", default="")
    parser.add_argument("--test-mode", action="store_true", default=False)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    run_managed(args)


if __name__ == "__main__":
    main()
