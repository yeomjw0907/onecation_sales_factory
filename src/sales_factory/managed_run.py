from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sales_factory.crew import SalesFactory
from sales_factory.proposal_quality import evaluate_proposal_path, evaluate_proposal_text
from sales_factory.runtime_assets import build_company_assets, create_approval_queue
from sales_factory.runtime_db import (
    PROJECT_ROOT,
    create_run,
    init_db,
    list_approval_items_for_run,
    list_assets,
    list_pending_tasks,
    list_task_costs,
    now_iso,
    record_notification,
    register_tasks,
    update_run,
    update_task,
)
from sales_factory.runtime_notifications import send_alert_email
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
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
}

ASSET_TYPE_LABELS = {
    "proposal": "제안서 원본",
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


def resolve_python_executable() -> str:
    local_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if local_python.exists():
        return str(local_python)
    return sys.executable


def run_pdf_generation() -> None:
    script_path = PROJECT_ROOT / "generate_pdf_playwright.py"
    if not script_path.exists():
        return
    subprocess.run([resolve_python_executable(), str(script_path)], cwd=str(PROJECT_ROOT), check=False)


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
        "target_country": args.target_country,
        "proposal_language": args.proposal_language,
        "currency": args.currency,
        "alert_email_to": args.notify_email,
        "test_mode": args.test_mode,
        "auto_mode": strategy_snapshot["auto_mode"],
        "strategy_snapshot": strategy_snapshot,
    }
    return payload


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


def run_managed(args: argparse.Namespace) -> str:
    init_db()
    run_id = str(uuid.uuid4())
    inputs = build_inputs(args)

    sales_factory = SalesFactory()
    crew = sales_factory.crew()
    crew.tasks = [task for task in crew.tasks if task.name != "notion_logging_task"]
    task_plan = parse_task_plan(crew)

    create_run(
        run_id,
        {
            "crew_name": getattr(crew, "name", "SalesFactory"),
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
            },
        },
    )
    register_tasks(run_id, task_plan)

    if task_plan:
        first = task_plan[0]
        update_task(run_id, first["task_name"], status="running", started_at=now_iso())
        update_run(run_id, current_task=first["task_name"], current_agent=first["agent_role"])

    task_lookup = {item["task_name"]: item for item in task_plan}
    task_sequence = [item["task_name"] for item in task_plan]
    stop_event = threading.Event()

    def heartbeat() -> None:
        while not stop_event.wait(5):
            update_run(run_id, last_heartbeat_at=now_iso())

    def handle_task_callback(task_output: Any) -> None:
        task_name = getattr(task_output, "name", None)
        if not task_name and task_sequence:
            pending = list_pending_tasks(run_id)
            if pending:
                task_name = pending[0]["task_name"]
        if not task_name:
            return

        task_row = task_lookup.get(task_name, {})
        task_obj = next((task for task in crew.tasks if task.name == task_name), None)
        agent = getattr(task_obj, "agent", None)
        llm = getattr(agent, "llm", None)
        usage = llm.get_token_usage_summary() if llm and hasattr(llm, "get_token_usage_summary") else None
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", 0) or 0)
        model_name = task_row.get("model_name")
        estimated_cost = estimate_cost_usd(model_name, prompt_tokens, completion_tokens)

        output_path = ""
        if task_obj and getattr(task_obj, "output_file", None):
            output_path = str(PROJECT_ROOT / task_obj.output_file)

        raw_text = getattr(task_output, "raw", "") or ""
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

    crew.task_callback = handle_task_callback
    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()

    try:
        result = crew.kickoff(inputs=inputs)
        run_pdf_generation()
        company_assets = build_company_assets(run_id)
        approval_count = create_approval_queue(run_id, company_assets)
        usage = getattr(result, "token_usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", 0) or 0)
        cached_prompt_tokens = int(getattr(usage, "cached_prompt_tokens", 0) or 0)
        successful_requests = int(getattr(usage, "successful_requests", 0) or 0)

        task_rows = list_task_costs(run_id)
        estimated_cost = round(sum(float(row["estimated_cost_usd"] or 0) for row in task_rows), 6)
        final_status = "waiting_approval" if approval_count else "completed"
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
    parser.add_argument("--notify-email", default="")
    parser.add_argument("--test-mode", action="store_true", default=False)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    run_managed(args)


if __name__ == "__main__":
    main()
