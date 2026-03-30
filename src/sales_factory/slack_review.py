from __future__ import annotations

import json
import os
import threading
from typing import Any

from sales_factory.review_ops import (
    approve_approval_item,
    asset_preview_text,
    load_approval_assets,
    reject_approval_item,
    send_test_outbound_email,
)
from sales_factory.runtime_db import get_approval_item, list_approval_items_for_run
from sales_factory.runtime_notifications import load_env_file

APP_URL_FALLBACK = "https://onecation-sales-factory.onrender.com"
_SOCKET_MODE_LOCK = threading.Lock()
_SOCKET_MODE_STARTED = False


def parse_json_value(value: Any, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def slack_public_app_url() -> str:
    load_env_file()
    return (
        os.environ.get("SALES_FACTORY_PUBLIC_URL", "").strip()
        or os.environ.get("RENDER_EXTERNAL_URL", "").strip()
        or APP_URL_FALLBACK
    ).rstrip("/")


def slack_socket_mode_enabled() -> bool:
    load_env_file()
    return bool(os.environ.get("SLACK_BOT_TOKEN", "").strip() and os.environ.get("SLACK_APP_TOKEN", "").strip())


def build_review_ready_slack_blocks(
    *,
    run_id: str,
    target_country: str,
    inputs: dict[str, Any],
    approval_count: int,
    total_tokens: int,
    estimated_cost: float,
) -> list[dict[str, Any]]:
    approval_items = sorted(
        list_approval_items_for_run(run_id, status="waiting_approval"),
        key=lambda row: (-int(row.get("priority") or 0), row.get("created_at") or ""),
    )
    app_url = slack_public_app_url()
    mode_label = "자동 모드" if inputs.get("auto_mode") else "직접 지정 모드"

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"검토 대기 {approval_count}건", "emoji": True},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*실행 ID:* `{run_id[:8]}`\n"
                    f"*국가:* {target_country}\n"
                    f"*실행 방식:* {mode_label}\n"
                    f"*탐색 기준:* {inputs.get('lead_query') or '-'}\n"
                    f"*사용 토큰:* {total_tokens:,}\n"
                    f"*예상 비용:* `${estimated_cost:.4f}`"
                ),
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "콘솔 열기", "emoji": True},
                "url": app_url,
            },
        },
        {"type": "divider"},
    ]

    for item in approval_items[:5]:
        metadata = parse_json_value(item.get("metadata_json"), {})
        auto_delivery = parse_json_value(metadata.get("auto_delivery"), {})
        blocked_reasons = auto_delivery.get("blocked_reasons") or []
        validation_issues = parse_json_value(metadata.get("validation_issues"), [])
        asset_rows = load_approval_assets(item)
        asset_types = ", ".join(row.get("asset_type") or "-" for row in asset_rows) or "-"
        email_preview = asset_preview_text(asset_rows, "email_sequence", limit=220).replace("\n", " ")
        note_parts: list[str] = []
        if blocked_reasons:
            note_parts.append("차단: " + " | ".join(str(reason) for reason in blocked_reasons[:2]))
        if validation_issues:
            note_parts.append("검수: " + " | ".join(str(issue) for issue in validation_issues[:2]))
        status_note = "\n".join(note_parts) if note_parts else "특이사항 없음"

        blocks.extend(
            [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*{item.get('company_name') or item.get('title') or item['id']}*\n"
                            f"{status_note}\n"
                            f"*산출물:* {asset_types}\n"
                            f"*메일 미리보기:* {email_preview}"
                        ),
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "미리보기", "emoji": True},
                            "action_id": "approval_preview",
                            "value": item["id"],
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "승인", "emoji": True},
                            "style": "primary",
                            "action_id": "approval_approve",
                            "value": item["id"],
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "보완 요청", "emoji": True},
                            "style": "danger",
                            "action_id": "approval_request_changes",
                            "value": item["id"],
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "테스트 메일", "emoji": True},
                            "action_id": "approval_send_test",
                            "value": item["id"],
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "콘솔", "emoji": True},
                            "url": app_url,
                        },
                    ],
                },
                {"type": "divider"},
            ]
        )

    if len(approval_items) > 5:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"추가 항목 {len(approval_items) - 5}건은 콘솔에서 확인하세요.",
                    }
                ],
            }
        )

    return blocks


def _post_ephemeral(client: Any, *, channel_id: str | None, user_id: str | None, text: str) -> None:
    if not channel_id or not user_id:
        return
    client.chat_postEphemeral(channel=channel_id, user=user_id, text=text)


def _build_preview_modal(item: dict[str, Any]) -> dict[str, Any]:
    asset_rows = load_approval_assets(item)
    proposal_preview = asset_preview_text(asset_rows, "proposal", limit=1400)
    email_preview = asset_preview_text(asset_rows, "email_sequence", limit=1400)
    metadata = parse_json_value(item.get("metadata_json"), {})
    auto_delivery = parse_json_value(metadata.get("auto_delivery"), {})
    blocked_reasons = auto_delivery.get("blocked_reasons") or []

    summary_text = f"*회사:* {item.get('company_name') or item.get('title') or item['id']}"
    if blocked_reasons:
        summary_text += "\n*자동발송 차단:* " + " | ".join(str(reason) for reason in blocked_reasons[:3])

    return {
        "type": "modal",
        "callback_id": "approval_preview_modal",
        "title": {"type": "plain_text", "text": "산출물 미리보기"},
        "close": {"type": "plain_text", "text": "닫기"},
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": summary_text}},
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*제안서 미리보기*\n```{proposal_preview}```"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*메일 미리보기*\n```{email_preview}```"},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "콘솔 열기", "emoji": True},
                        "url": slack_public_app_url(),
                    }
                ],
            },
        ],
    }


def ensure_slack_socket_mode_started() -> bool:
    global _SOCKET_MODE_STARTED

    if _SOCKET_MODE_STARTED:
        return True

    load_env_file()
    bot_token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    app_token = os.environ.get("SLACK_APP_TOKEN", "").strip()
    if not bot_token or not app_token:
        return False

    with _SOCKET_MODE_LOCK:
        if _SOCKET_MODE_STARTED:
            return True

        try:
            from slack_bolt import App
            from slack_bolt.adapter.socket_mode import SocketModeHandler
        except Exception:
            return False

        app = App(
            token=bot_token,
            signing_secret=os.environ.get("SLACK_SIGNING_SECRET", "socket-mode"),
            process_before_response=True,
        )

        @app.action("approval_preview")
        def _approval_preview(ack: Any, body: dict[str, Any], client: Any) -> None:
            ack()
            item_id = body["actions"][0]["value"]
            item = get_approval_item(item_id)
            if not item:
                _post_ephemeral(
                    client,
                    channel_id=body.get("channel", {}).get("id"),
                    user_id=body.get("user", {}).get("id"),
                    text="승인 항목을 찾지 못했습니다.",
                )
                return
            client.views_open(trigger_id=body["trigger_id"], view=_build_preview_modal(item))

        @app.action("approval_approve")
        def _approval_approve(ack: Any, body: dict[str, Any], client: Any) -> None:
            ack()
            item_id = body["actions"][0]["value"]
            item = get_approval_item(item_id)
            if not item:
                _post_ephemeral(
                    client,
                    channel_id=body.get("channel", {}).get("id"),
                    user_id=body.get("user", {}).get("id"),
                    text="승인 항목을 찾지 못했습니다.",
                )
                return
            approve_approval_item(item, reviewer_identity=body.get("user", {}).get("username") or body.get("user", {}).get("id", ""))
            _post_ephemeral(
                client,
                channel_id=body.get("channel", {}).get("id"),
                user_id=body.get("user", {}).get("id"),
                text=f"{item.get('company_name') or item.get('title')} 승인 처리했습니다.",
            )

        @app.action("approval_send_test")
        def _approval_send_test(ack: Any, body: dict[str, Any], client: Any) -> None:
            ack()
            item_id = body["actions"][0]["value"]
            item = get_approval_item(item_id)
            recipient = os.environ.get("ALERT_EMAIL_TO", "").strip() or os.environ.get("SMTP_USER", "").strip()
            if not item or not recipient:
                _post_ephemeral(
                    client,
                    channel_id=body.get("channel", {}).get("id"),
                    user_id=body.get("user", {}).get("id"),
                    text="테스트 메일 대상 주소 또는 승인 항목을 찾지 못했습니다.",
                )
                return
            asset_rows = load_approval_assets(item)
            send_test_outbound_email(
                run_id=item["run_id"],
                company_name=item.get("company_name") or "",
                asset_rows=asset_rows,
                recipient=recipient,
            )
            _post_ephemeral(
                client,
                channel_id=body.get("channel", {}).get("id"),
                user_id=body.get("user", {}).get("id"),
                text=f"{recipient} 로 테스트 메일을 보냈습니다.",
            )

        @app.action("approval_request_changes")
        def _approval_request_changes(ack: Any, body: dict[str, Any], client: Any) -> None:
            ack()
            item_id = body["actions"][0]["value"]
            item = get_approval_item(item_id)
            if not item:
                _post_ephemeral(
                    client,
                    channel_id=body.get("channel", {}).get("id"),
                    user_id=body.get("user", {}).get("id"),
                    text="보완 요청 대상 항목을 찾지 못했습니다.",
                )
                return

            private_metadata = json.dumps(
                {
                    "item_id": item_id,
                    "channel_id": body.get("channel", {}).get("id"),
                    "user_id": body.get("user", {}).get("id"),
                }
            )
            client.views_open(
                trigger_id=body["trigger_id"],
                view={
                    "type": "modal",
                    "callback_id": "approval_request_changes_modal",
                    "private_metadata": private_metadata,
                    "title": {"type": "plain_text", "text": "보완 요청"},
                    "submit": {"type": "plain_text", "text": "제출"},
                    "close": {"type": "plain_text", "text": "취소"},
                    "blocks": [
                        {
                            "type": "input",
                            "block_id": "reason_block",
                            "label": {"type": "plain_text", "text": "보완 사유"},
                            "element": {
                                "type": "plain_text_input",
                                "action_id": "reason_input",
                                "multiline": True,
                                "placeholder": {"type": "plain_text", "text": "Slack에서 바로 보완 메모를 남기세요."},
                            },
                        }
                    ],
                },
            )

        @app.view("approval_request_changes_modal")
        def _approval_request_changes_modal(ack: Any, body: dict[str, Any], client: Any, view: dict[str, Any]) -> None:
            ack()
            metadata = parse_json_value(view.get("private_metadata"), {})
            item = get_approval_item(metadata.get("item_id", ""))
            reason = (
                view.get("state", {})
                .get("values", {})
                .get("reason_block", {})
                .get("reason_input", {})
                .get("value", "")
                .strip()
            )
            if not item or not reason:
                _post_ephemeral(
                    client,
                    channel_id=metadata.get("channel_id"),
                    user_id=metadata.get("user_id"),
                    text="보완 요청 처리에 필요한 항목 또는 사유를 찾지 못했습니다.",
                )
                return

            launched, message = reject_approval_item(
                item,
                reason,
                reviewer_identity=body.get("user", {}).get("username") or body.get("user", {}).get("id", ""),
            )
            _post_ephemeral(
                client,
                channel_id=metadata.get("channel_id"),
                user_id=metadata.get("user_id"),
                text=message if launched else f"보완 요청은 기록했지만 재작업 시작은 보류됐습니다. {message}",
            )

        def _start() -> None:
            handler = SocketModeHandler(app, app_token)
            handler.start()

        thread = threading.Thread(target=_start, name="slack-socket-mode", daemon=True)
        thread.start()
        _SOCKET_MODE_STARTED = True
        return True
