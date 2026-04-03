from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from sales_factory.auto_delivery import build_primary_email_payload
from sales_factory.review_ops import (
    approve_approval_item,
    approve_and_send_approval_item,
    asset_preview_text,
    build_live_send_preview,
    load_approval_assets,
    reject_approval_item,
    send_test_outbound_email,
)
from sales_factory.runtime_db import get_approval_item, list_approval_items_for_run
from sales_factory.runtime_notifications import load_env_file
from sales_factory.runtime_supabase import materialize_local_asset

APP_URL_FALLBACK = "https://onecation-sales-factory.onrender.com"
_SOCKET_MODE_LOCK = threading.Lock()
_SOCKET_MODE_STARTED = False
_SOCKET_MODE_THREAD: threading.Thread | None = None


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


def prime_slack_review_handlers() -> bool:
    try:
        return ensure_slack_socket_mode_started()
    except Exception as exc:
        print(f"[slack] failed to prime socket mode: {exc}")
        return False


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
                            "text": {"type": "plain_text", "text": "바로 발송", "emoji": True},
                            "action_id": "approval_confirm_send",
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


def _extract_action_context(body: dict[str, Any]) -> dict[str, str | None]:
    view = body.get("view") or {}
    metadata = parse_json_value(view.get("private_metadata"), {})
    return {
        "channel_id": body.get("channel", {}).get("id") or metadata.get("channel_id"),
        "user_id": body.get("user", {}).get("id") or metadata.get("user_id"),
        "message_ts": body.get("message", {}).get("ts") or metadata.get("message_ts"),
    }


def _notify_action_result(client: Any, body: dict[str, Any], *, text: str, title: str = "처리 결과") -> None:
    view = body.get("view") or {}
    view_id = view.get("id")
    if view_id:
        client.views_update(
            view_id=view_id,
            hash=view.get("hash"),
            view={
                "type": "modal",
                "title": {"type": "plain_text", "text": title[:24]},
                "close": {"type": "plain_text", "text": "닫기"},
                "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
            },
        )
        return
    _post_ephemeral(
        client,
        channel_id=body.get("channel", {}).get("id"),
        user_id=body.get("user", {}).get("id"),
        text=text,
    )


def _notify_channel_or_dm(client: Any, *, channel_id: str | None, user_id: str | None, text: str) -> None:
    if channel_id and user_id:
        _post_ephemeral(client, channel_id=channel_id, user_id=user_id, text=text)
        return
    if user_id:
        dm_channel = _open_user_dm(client, user_id)
        if dm_channel:
            client.chat_postMessage(channel=dm_channel, text=text)


def _try_add_message_reaction(
    client: Any,
    *,
    channel_id: str | None,
    message_ts: str | None,
    name: str,
) -> None:
    if not channel_id or not message_ts:
        return
    try:
        client.reactions_add(channel=channel_id, timestamp=message_ts, name=name)
    except Exception:
        return


def _handle_request_changes_async(
    client: Any,
    *,
    item: dict[str, Any],
    reason: str,
    reviewer_identity: str,
    channel_id: str | None,
    user_id: str | None,
    message_ts: str | None,
) -> None:
    try:
        launched, message = reject_approval_item(
            item,
            reason,
            reviewer_identity=reviewer_identity,
        )
        _try_add_message_reaction(
            client,
            channel_id=channel_id,
            message_ts=message_ts,
            name="memo",
        )
        _post_ephemeral(
            client,
            channel_id=channel_id,
            user_id=user_id,
            text=message if launched else f"보완 요청은 기록했지만 재작업 시작은 보류됐습니다. {message}",
        )
    except Exception as exc:
        _post_ephemeral(
            client,
            channel_id=channel_id,
            user_id=user_id,
            text=f"보완 요청 처리 중 오류가 발생했습니다: {exc}",
        )


def _handle_approve_and_send_async(
    client: Any,
    *,
    item: dict[str, Any],
    reviewer_identity: str,
    channel_id: str | None,
    user_id: str | None,
    message_ts: str | None,
) -> None:
    try:
        sent, message = approve_and_send_approval_item(
            item,
            reviewer_identity=reviewer_identity,
        )
        if sent:
            _try_add_message_reaction(
                client,
                channel_id=channel_id,
                message_ts=message_ts,
                name="outbox_tray",
            )
        _post_ephemeral(
            client,
            channel_id=channel_id,
            user_id=user_id,
            text=message,
        )
    except Exception as exc:
        _post_ephemeral(
            client,
            channel_id=channel_id,
            user_id=user_id,
            text=f"실제 발송 처리 중 오류가 발생했습니다: {exc}",
        )


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


def _truncate_for_slack(text: str, *, limit: int = 2600) -> str:
    normalized = (text or "").strip()
    if len(normalized) <= limit:
        return normalized or "-"
    return normalized[: limit - 1].rstrip() + "…"


def _build_email_preview(asset_rows: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        subject, body, attachments = build_primary_email_payload(asset_rows)
    except Exception:
        subject = "-"
        body = asset_preview_text(asset_rows, "email_sequence", limit=2200)
        attachments = []
    return {
        "subject": subject or "-",
        "body": body or "-",
        "attachments": attachments,
        "attachment_names": [path.name for path in attachments],
    }


def _resolve_attachment_for_slack(item: dict[str, Any], asset_type: str) -> Path | None:
    asset_rows = load_approval_assets(item)
    asset_row = next((row for row in asset_rows if row.get("asset_type") == asset_type), None)
    if not asset_row:
        return None
    metadata = parse_json_value(asset_row.get("metadata_json"), {})
    return materialize_local_asset(Path(str(asset_row.get("path") or "")), metadata)


def _open_user_dm(client: Any, user_id: str) -> str | None:
    response = client.conversations_open(users=user_id)
    channel = response.get("channel") or {}
    return channel.get("id")


def _send_attachment_to_user_dm(client: Any, *, user_id: str, item: dict[str, Any], asset_type: str) -> tuple[bool, str]:
    label = "PDF" if asset_type == "proposal_pdf" else "Word"
    try:
        local_path = _resolve_attachment_for_slack(item, asset_type)
        if not local_path or not local_path.exists():
            return False, f"{label} 파일을 준비하지 못했습니다."

        dm_channel = _open_user_dm(client, user_id)
        if not dm_channel:
            return False, "Slack DM 채널을 열지 못했습니다."

        title = f"{item.get('company_name') or item.get('title') or item.get('id')} {label}"
        client.files_upload_v2(
            channel=dm_channel,
            file=str(local_path),
            filename=local_path.name,
            title=title,
            initial_comment=f"{title} 파일입니다.",
        )
        return True, f"{label} 파일을 Slack DM으로 보냈습니다."
    except Exception as exc:
        return False, f"{label} 파일 전송에 실패했습니다: {exc}"


def _build_preview_modal(item: dict[str, Any]) -> dict[str, Any]:
    asset_rows = load_approval_assets(item)
    proposal_preview = asset_preview_text(asset_rows, "proposal", limit=1400)
    email_preview = _build_email_preview(asset_rows)
    metadata = parse_json_value(item.get("metadata_json"), {})
    auto_delivery = parse_json_value(metadata.get("auto_delivery"), {})
    blocked_reasons = auto_delivery.get("blocked_reasons") or []

    summary_text = f"*회사:* {item.get('company_name') or item.get('title') or item['id']}"
    if blocked_reasons:
        summary_text += "\n*자동발송 차단:* " + " | ".join(str(reason) for reason in blocked_reasons[:3])

    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": summary_text}},
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*메일 제목*\n```{_truncate_for_slack(email_preview['subject'], limit=280)}```"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*메일 본문*\n```{_truncate_for_slack(email_preview['body'])}```"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*첨부 파일*\n"
                + ("\n".join(f"• {name}" for name in email_preview["attachment_names"]) if email_preview["attachment_names"] else "첨부 없음"),
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*제안서 미리보기*\n```{_truncate_for_slack(proposal_preview)}```"},
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "승인", "emoji": True},
                    "style": "primary",
                    "action_id": "approval_approve",
                    "value": item["id"],
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "바로 발송", "emoji": True},
                    "action_id": "approval_confirm_send",
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
            ],
        },
    ]

    attachment_actions: list[dict[str, Any]] = []
    if any(path.suffix.lower() == ".pdf" for path in email_preview["attachments"]):
        attachment_actions.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "PDF 받기", "emoji": True},
                "action_id": "approval_send_pdf",
                "value": item["id"],
            }
        )
    if any(path.suffix.lower() in {".docx", ".doc"} for path in email_preview["attachments"]):
        attachment_actions.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Word 받기", "emoji": True},
                "action_id": "approval_send_docx",
                "value": item["id"],
            }
        )
    attachment_actions.append(
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "콘솔 열기", "emoji": True},
            "url": slack_public_app_url(),
        }
    )
    blocks.append({"type": "actions", "elements": attachment_actions[:5]})

    return {
        "type": "modal",
        "callback_id": "approval_preview_modal",
        "private_metadata": json.dumps({"item_id": item["id"]}),
        "title": {"type": "plain_text", "text": "산출물 미리보기"},
        "close": {"type": "plain_text", "text": "닫기"},
        "blocks": blocks,
    }


def _build_confirm_send_modal(item: dict[str, Any]) -> dict[str, Any]:
    preview = build_live_send_preview(item)
    recipient = preview.get("recipient") or "(missing)"
    attachments = preview.get("attachment_names") or []
    blocked_reasons = preview.get("blocked_reasons") or []
    test_mode_label = "원본 실행은 테스트 모드였습니다." if preview.get("test_mode") else "원본 실행은 실제 모드였습니다."

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*정말 이 업체에 바로 발송하시겠습니까?*\n"
                    f"*회사:* {preview.get('company_name')}\n"
                    f"*수신 이메일:* `{recipient}`\n"
                    f"*메일 제목:* `{_truncate_for_slack(str(preview.get('subject') or '-'), limit=280)}`\n"
                    f"*첨부 파일:* {', '.join(attachments) if attachments else '첨부 없음'}\n"
                    f"*참고:* {test_mode_label}"
                ),
            },
        }
    ]
    if blocked_reasons:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*주의 사항*\n" + "\n".join(f"• {reason}" for reason in blocked_reasons[:4]),
                },
            }
        )
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "이 버튼은 테스트 메일이 아니라 실제 고객 발송입니다.",
                }
            ],
        }
    )
    return {
        "type": "modal",
        "callback_id": "approval_confirm_send_modal",
        "private_metadata": json.dumps({"item_id": item["id"]}),
        "title": {"type": "plain_text", "text": "실제 발송 확인"},
        "submit": {"type": "plain_text", "text": "실제 발송"},
        "close": {"type": "plain_text", "text": "취소"},
        "blocks": blocks,
    }


def ensure_slack_socket_mode_started() -> bool:
    global _SOCKET_MODE_STARTED, _SOCKET_MODE_THREAD

    if _SOCKET_MODE_STARTED and _SOCKET_MODE_THREAD and _SOCKET_MODE_THREAD.is_alive():
        return True
    if _SOCKET_MODE_THREAD and not _SOCKET_MODE_THREAD.is_alive():
        _SOCKET_MODE_STARTED = False
        _SOCKET_MODE_THREAD = None

    load_env_file()
    bot_token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    app_token = os.environ.get("SLACK_APP_TOKEN", "").strip()
    if not bot_token or not app_token:
        return False

    with _SOCKET_MODE_LOCK:
        if _SOCKET_MODE_STARTED and _SOCKET_MODE_THREAD and _SOCKET_MODE_THREAD.is_alive():
            return True
        if _SOCKET_MODE_THREAD and not _SOCKET_MODE_THREAD.is_alive():
            _SOCKET_MODE_STARTED = False
            _SOCKET_MODE_THREAD = None

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
            context = _extract_action_context(body)
            if not item:
                _post_ephemeral(
                    client,
                    channel_id=context["channel_id"],
                    user_id=context["user_id"],
                    text="승인 항목을 찾지 못했습니다.",
                )
                return
            view = _build_preview_modal(item)
            metadata = parse_json_value(view.get("private_metadata"), {})
            metadata.update(context)
            view["private_metadata"] = json.dumps(metadata)
            client.views_open(trigger_id=body["trigger_id"], view=view)

        @app.action("approval_approve")
        def _approval_approve(ack: Any, body: dict[str, Any], client: Any) -> None:
            ack()
            item_id = body["actions"][0]["value"]
            item = get_approval_item(item_id)
            context = _extract_action_context(body)
            if not item:
                _post_ephemeral(
                    client,
                    channel_id=context["channel_id"],
                    user_id=context["user_id"],
                    text="승인 항목을 찾지 못했습니다.",
                )
                return
            approve_approval_item(item, reviewer_identity=body.get("user", {}).get("username") or body.get("user", {}).get("id", ""))
            _try_add_message_reaction(
                client,
                channel_id=context["channel_id"],
                message_ts=context["message_ts"],
                name="white_check_mark",
            )
            _notify_action_result(
                client,
                body,
                text=f"{item.get('company_name') or item.get('title')} 승인 처리했습니다.",
                title="승인 완료",
            )
            _post_ephemeral(
                client,
                channel_id=context["channel_id"],
                user_id=context["user_id"],
                text=f"{item.get('company_name') or item.get('title')} 승인 처리했습니다.",
            )

        @app.action("approval_confirm_send")
        def _approval_confirm_send(ack: Any, body: dict[str, Any], client: Any) -> None:
            ack()
            item_id = body["actions"][0]["value"]
            item = get_approval_item(item_id)
            context = _extract_action_context(body)
            if not item:
                _post_ephemeral(
                    client,
                    channel_id=context["channel_id"],
                    user_id=context["user_id"],
                    text="실제 발송 대상 항목을 찾지 못했습니다.",
                )
                return
            try:
                view = _build_confirm_send_modal(item)
            except Exception as exc:
                _post_ephemeral(
                    client,
                    channel_id=context["channel_id"],
                    user_id=context["user_id"],
                    text=f"실제 발송 미리보기를 준비하지 못했습니다: {exc}",
                )
                return
            private_metadata = parse_json_value(view.get("private_metadata"), {})
            private_metadata.update(
                {
                    "channel_id": context["channel_id"],
                    "user_id": context["user_id"],
                    "message_ts": context["message_ts"],
                }
            )
            view["private_metadata"] = json.dumps(private_metadata)
            open_modal = client.views_push if body.get("view", {}).get("id") else client.views_open
            open_modal(trigger_id=body["trigger_id"], view=view)

        @app.action("approval_send_test")
        def _approval_send_test(ack: Any, body: dict[str, Any], client: Any) -> None:
            ack()
            item_id = body["actions"][0]["value"]
            item = get_approval_item(item_id)
            context = _extract_action_context(body)
            recipient = os.environ.get("ALERT_EMAIL_TO", "").strip() or os.environ.get("SMTP_USER", "").strip()
            if not item or not recipient:
                _post_ephemeral(
                    client,
                    channel_id=context["channel_id"],
                    user_id=context["user_id"],
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
            _try_add_message_reaction(
                client,
                channel_id=context["channel_id"],
                message_ts=context["message_ts"],
                name="email",
            )
            _post_ephemeral(
                client,
                channel_id=context["channel_id"],
                user_id=context["user_id"],
                text=f"{recipient} 로 테스트 메일을 보냈습니다.",
            )

        @app.action("approval_send_pdf")
        def _approval_send_pdf(ack: Any, body: dict[str, Any], client: Any) -> None:
            ack()
            item_id = body["actions"][0]["value"]
            item = get_approval_item(item_id)
            context = _extract_action_context(body)
            if not item:
                _post_ephemeral(
                    client,
                    channel_id=context["channel_id"],
                    user_id=context["user_id"],
                    text="PDF를 보낼 승인 항목을 찾지 못했습니다.",
                )
                return
            _ok, message = _send_attachment_to_user_dm(
                client,
                user_id=context["user_id"] or "",
                item=item,
                asset_type="proposal_pdf",
            )
            _post_ephemeral(
                client,
                channel_id=context["channel_id"],
                user_id=context["user_id"],
                text=message,
            )

        @app.action("approval_send_docx")
        def _approval_send_docx(ack: Any, body: dict[str, Any], client: Any) -> None:
            ack()
            item_id = body["actions"][0]["value"]
            item = get_approval_item(item_id)
            context = _extract_action_context(body)
            if not item:
                _post_ephemeral(
                    client,
                    channel_id=context["channel_id"],
                    user_id=context["user_id"],
                    text="Word 파일을 보낼 승인 항목을 찾지 못했습니다.",
                )
                return
            _ok, message = _send_attachment_to_user_dm(
                client,
                user_id=context["user_id"] or "",
                item=item,
                asset_type="proposal_docx",
            )
            _post_ephemeral(
                client,
                channel_id=context["channel_id"],
                user_id=context["user_id"],
                text=message,
            )

        @app.action("approval_request_changes")
        def _approval_request_changes(ack: Any, body: dict[str, Any], client: Any) -> None:
            ack()
            item_id = body["actions"][0]["value"]
            item = get_approval_item(item_id)
            context = _extract_action_context(body)
            if not item:
                _post_ephemeral(
                    client,
                    channel_id=context["channel_id"],
                    user_id=context["user_id"],
                    text="보완 요청 대상 항목을 찾지 못했습니다.",
                )
                return

            private_metadata = json.dumps(
                {
                    "item_id": item_id,
                    "channel_id": context["channel_id"],
                    "user_id": context["user_id"],
                    "message_ts": context["message_ts"],
                }
            )
            open_modal = client.views_push if body.get("view", {}).get("id") else client.views_open
            open_modal(
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

            threading.Thread(
                target=_handle_request_changes_async,
                kwargs={
                    "client": client,
                    "item": item,
                    "reason": reason,
                    "reviewer_identity": body.get("user", {}).get("username") or body.get("user", {}).get("id", ""),
                    "channel_id": metadata.get("channel_id"),
                    "user_id": metadata.get("user_id"),
                    "message_ts": metadata.get("message_ts"),
                },
                name=f"slack-request-changes-{item['id'][:8]}",
                daemon=True,
            ).start()

        @app.view("approval_confirm_send_modal")
        def _approval_confirm_send_modal(ack: Any, body: dict[str, Any], client: Any, view: dict[str, Any]) -> None:
            ack()
            metadata = parse_json_value(view.get("private_metadata"), {})
            item = get_approval_item(metadata.get("item_id", ""))
            if not item:
                _post_ephemeral(
                    client,
                    channel_id=metadata.get("channel_id"),
                    user_id=metadata.get("user_id"),
                    text="실제 발송 대상 항목을 찾지 못했습니다.",
                )
                return

            threading.Thread(
                target=_handle_approve_and_send_async,
                kwargs={
                    "client": client,
                    "item": item,
                    "reviewer_identity": body.get("user", {}).get("username") or body.get("user", {}).get("id", ""),
                    "channel_id": metadata.get("channel_id"),
                    "user_id": metadata.get("user_id"),
                    "message_ts": metadata.get("message_ts"),
                },
                name=f"slack-approve-send-{item['id'][:8]}",
                daemon=True,
            ).start()

        def _start() -> None:
            global _SOCKET_MODE_STARTED, _SOCKET_MODE_THREAD

            try:
                handler = SocketModeHandler(app, app_token)
                handler.start()
            except Exception as exc:
                print(f"[slack] socket mode stopped: {exc}")
            finally:
                with _SOCKET_MODE_LOCK:
                    _SOCKET_MODE_STARTED = False
                    _SOCKET_MODE_THREAD = None

        thread = threading.Thread(target=_start, name="slack-socket-mode", daemon=True)
        _SOCKET_MODE_THREAD = thread
        _SOCKET_MODE_STARTED = True
        try:
            thread.start()
        except Exception:
            _SOCKET_MODE_STARTED = False
            _SOCKET_MODE_THREAD = None
            raise
        return True
