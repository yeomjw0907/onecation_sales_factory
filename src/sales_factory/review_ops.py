from __future__ import annotations

import os
import threading
import traceback
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sales_factory.auto_delivery import build_primary_email_payload
from sales_factory.runtime_assets import route_rejection
from sales_factory.runtime_db import (
    get_run,
    list_assets_by_ids,
    now_iso,
    query_running_run,
    record_notification,
    summarize_approval_items,
    update_approval_item,
    update_run,
)
from sales_factory.runtime_notifications import send_email_message

DEFAULT_LANGUAGE_BY_COUNTRY = {
    "KR": "Korean",
    "US": "English",
    "JP": "Japanese",
    "TW": "Traditional Chinese",
    "SG": "English",
    "CN": "Simplified Chinese",
    "AE": "English",
}

DEFAULT_CURRENCY_BY_COUNTRY = {
    "KR": "KRW",
    "US": "USD",
    "JP": "JPY",
    "TW": "TWD",
    "SG": "SGD",
    "CN": "CNY",
    "AE": "AED",
}


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


def load_approval_assets(item: dict[str, Any]) -> list[dict[str, Any]]:
    bundle_ids = parse_json_value(item.get("asset_bundle_json"), [])
    return list_assets_by_ids(bundle_ids)


def finalize_run_review_state(run_id: str) -> None:
    summary = summarize_approval_items(run_id)
    waiting_count = int(summary.get("waiting_count") or 0)
    approved_count = int(summary.get("approved_count") or 0)
    rejected_count = int(summary.get("rejected_count") or 0)

    if waiting_count > 0:
        update_run(run_id, status="waiting_approval", approval_count=waiting_count)
        return

    run_row = get_run(run_id)
    metadata = parse_json_value(run_row.get("metadata_json") if run_row else None, {})
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


def build_live_send_preview(item: dict[str, Any]) -> dict[str, Any]:
    metadata = parse_json_value(item.get("metadata_json"), {})
    auto_delivery = parse_json_value(metadata.get("auto_delivery"), {})
    asset_rows = load_approval_assets(item)
    subject, body, attachments = build_primary_email_payload(asset_rows)
    run_row = get_run(item["run_id"]) or {}
    recipient = str(auto_delivery.get("recipient_email") or auto_delivery.get("recipient") or "").strip()
    blocked_reasons = [str(reason) for reason in (auto_delivery.get("blocked_reasons") or []) if str(reason).strip()]
    return {
        "company_name": item.get("company_name") or item.get("title") or item.get("id"),
        "recipient": recipient,
        "subject": subject,
        "body": body,
        "attachments": attachments,
        "attachment_names": [path.name for path in attachments],
        "blocked_reasons": blocked_reasons,
        "test_mode": bool(run_row.get("test_mode", 1)),
    }


def approve_and_send_approval_item(
    item: dict[str, Any],
    *,
    reviewer_note: str = "",
    reviewer_identity: str = "",
) -> tuple[bool, str]:
    preview = build_live_send_preview(item)
    recipient = str(preview.get("recipient") or "").strip()
    if not recipient:
        return False, "실제 발송 대상 이메일을 찾지 못했습니다."

    subject = str(preview["subject"])
    body = str(preview["body"])
    attachments = list(preview["attachments"])
    send_email_message(
        subject=subject,
        body_text=body,
        to_email=recipient,
        attachment_paths=attachments,
    )

    metadata = parse_json_value(item.get("metadata_json"), {})
    if reviewer_note.strip():
        metadata["reviewer_note"] = reviewer_note.strip()
    if reviewer_identity.strip():
        metadata["reviewed_via"] = "slack"
        metadata["reviewer_identity"] = reviewer_identity.strip()
    metadata["manual_delivery"] = {
        "status": "sent",
        "recipient": recipient,
        "subject": subject,
        "attachments": [str(path) for path in attachments],
        "sent_at": now_iso(),
    }

    update_approval_item(
        item["id"],
        status="approved",
        decided_at=now_iso(),
        metadata_json=metadata,
    )
    finalize_run_review_state(item["run_id"])
    record_notification(
        item["run_id"],
        "manual_outbound_email",
        "sent",
        subject,
        recipient,
        {
            "company_name": item.get("company_name"),
            "attachments": [str(path) for path in attachments],
            "approval_item_id": item["id"],
        },
    )
    return True, f"{recipient} 로 실제 발송을 완료했습니다."


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
    source_metadata = parse_json_value(source_run.get("metadata_json"), {})
    notify_email = source_metadata.get("notify_email") or os.environ.get("ALERT_EMAIL_TO", "").strip()

    run_args = SimpleNamespace(
        trigger_source="approval_rework_slack",
        target_country=target_country,
        lead_mode=lead_mode,
        lead_query=lead_query,
        max_companies=max_companies,
        notify_email=notify_email,
        proposal_language=source_run.get("proposal_language") or DEFAULT_LANGUAGE_BY_COUNTRY.get(target_country, "English"),
        currency=source_run.get("currency") or DEFAULT_CURRENCY_BY_COUNTRY.get(target_country, "USD"),
        test_mode=bool(source_run.get("test_mode", 1)),
    )

    def _run_in_background() -> None:
        from sales_factory.managed_run import run_managed

        try:
            run_managed(run_args)
        except Exception:
            record_notification(
                item["run_id"],
                "rework_run",
                "failed",
                f"Rework failed for {company_name or target_country}",
                notify_email or "(missing)",
                {"reason": reason, "traceback": traceback.format_exc()},
            )

    thread = threading.Thread(
        target=_run_in_background,
        name=f"slack-rework-{datetime.now().strftime('%H%M%S')}",
        daemon=True,
    )
    thread.start()

    record_notification(
        item["run_id"],
        "rework_run",
        "queued",
        f"Rework queued for {company_name or target_country}",
        notify_email or "(missing)",
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


def approve_approval_item(item: dict[str, Any], reviewer_note: str = "", reviewer_identity: str = "") -> None:
    metadata = parse_json_value(item.get("metadata_json"), {})
    if reviewer_note.strip():
        metadata["reviewer_note"] = reviewer_note.strip()
    if reviewer_identity.strip():
        metadata["reviewed_via"] = "slack"
        metadata["reviewer_identity"] = reviewer_identity.strip()

    update_approval_item(
        item["id"],
        status="approved",
        decided_at=now_iso(),
        metadata_json=metadata,
    )
    finalize_run_review_state(item["run_id"])


def reject_approval_item(item: dict[str, Any], reason: str, reviewer_identity: str = "") -> tuple[bool, str]:
    metadata = parse_json_value(item.get("metadata_json"), {})
    metadata["reviewer_note"] = reason.strip()
    if reviewer_identity.strip():
        metadata["reviewed_via"] = "slack"
        metadata["reviewer_identity"] = reviewer_identity.strip()

    reroute = route_rejection(metadata.get("asset_type", "proposal_package"), reason)
    update_approval_item(
        item["id"],
        status="rejected",
        decided_at=now_iso(),
        rejection_reason=reason,
        reroute_targets_json=reroute,
        metadata_json=metadata,
    )
    finalize_run_review_state(item["run_id"])
    return launch_rework_for_approval(item, reason)


def asset_preview_text(asset_rows: list[dict[str, Any]], asset_type: str, *, limit: int = 1200) -> str:
    target = next((row for row in asset_rows if row.get("asset_type") == asset_type), None)
    if not target:
        return "해당 산출물이 없습니다."

    from sales_factory.runtime_supabase import read_asset_text

    path = Path(target["path"])
    metadata = parse_json_value(target.get("metadata_json"), {})
    if path.suffix.lower() == ".pdf":
        return f"PDF가 준비되었습니다: {path.name}"
    text = read_asset_text(path, metadata).strip()
    if not text:
        return "내용을 불러오지 못했습니다."
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
