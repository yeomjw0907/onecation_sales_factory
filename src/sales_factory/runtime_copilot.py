from __future__ import annotations

from typing import Any


def _top_quality_line(quality_rows: list[dict[str, Any]]) -> str:
    if not quality_rows:
        return "제안서 품질 데이터는 아직 없습니다."
    best = sorted(quality_rows, key=lambda row: row.get("score", 0), reverse=True)[0]
    return f"가장 점수가 높은 제안서는 {best['company_name']} ({best['score']}점, {best['label']})입니다."


def answer_ops_question(
    question: str,
    *,
    latest_run: dict[str, Any] | None,
    waiting_approvals: list[dict[str, Any]],
    recent_notifications: list[dict[str, Any]],
    quality_rows: list[dict[str, Any]],
) -> str:
    lowered = (question or "").strip().lower()
    if not lowered:
        return "질문을 입력하면 오늘 성과, 승인 대기, 비용, 실패 내역, 제안서 품질, 다음 추천 액션을 요약해드릴 수 있습니다."

    if "오늘" in lowered and ("성과" in lowered or "status" in lowered):
        if not latest_run:
            return "오늘 실행 기록이 아직 없습니다. 자동 모드나 수동 탐색으로 한 번 실행을 시작하는 게 먼저입니다."
        return (
            f"가장 최근 실행은 {latest_run.get('target_country', '-')} 국가 기준이며 "
            f"상태는 {latest_run.get('status', '-')}입니다. "
            f"검토 대기는 {latest_run.get('approval_count', 0)}건, "
            f"토큰은 {latest_run.get('total_tokens', 0):,}개, "
            f"예상 비용은 ${float(latest_run.get('estimated_cost_usd', 0) or 0):.4f}입니다."
        )

    if "승인" in lowered or "검토" in lowered:
        if not waiting_approvals:
            return "지금 검토 대기 중인 항목은 없습니다."
        company_names = [row.get("company_name") or "-" for row in waiting_approvals[:5]]
        return f"지금 검토 대기 중인 항목은 {len(waiting_approvals)}건입니다. 우선 확인할 회사는 {', '.join(company_names)} 입니다."

    if "비용" in lowered or "토큰" in lowered:
        if not latest_run:
            return "아직 비용을 집계할 실행 기록이 없습니다."
        return (
            f"가장 최근 실행 기준 토큰은 {latest_run.get('total_tokens', 0):,}개이고 "
            f"예상 비용은 ${float(latest_run.get('estimated_cost_usd', 0) or 0):.4f}입니다."
        )

    if "실패" in lowered or "오류" in lowered:
        failed_notifications = [row for row in recent_notifications if row.get("status") == "failed"]
        if latest_run and latest_run.get("status") == "failed":
            return f"최근 실행은 실패 상태입니다. 오류 메시지는: {latest_run.get('error_message') or '확인 필요'}"
        if failed_notifications:
            latest_failure = failed_notifications[0]
            return f"최근 알림 실패가 있습니다. 제목: {latest_failure.get('subject')}, 수신자: {latest_failure.get('recipient')}"
        return "최근 실행과 알림 기준으로 확인된 실패는 없습니다."

    if "품질" in lowered or "제안서" in lowered:
        return _top_quality_line(quality_rows)

    if "뭐" in lowered or "추천" in lowered or "다음" in lowered:
        if waiting_approvals:
            return f"지금은 검토 대기 {len(waiting_approvals)}건을 먼저 처리하는 게 맞습니다. 외부 발송 전에 승인 병목을 줄이는 게 우선입니다."
        if latest_run and latest_run.get("status") == "failed":
            return "최근 실행이 실패했으니, 같은 국가/조건으로 재실행하기 전에 오류 원인과 SMTP/외부 설정부터 확인하는 게 맞습니다."
        if quality_rows:
            best = sorted(quality_rows, key=lambda row: row.get("score", 0), reverse=True)[0]
            return f"다음 액션으로는 품질이 가장 좋은 {best['company_name']} 제안서를 기준 사례로 보고, 같은 패턴의 리드를 더 늘리는 쪽이 좋습니다."
        return "다음 액션으로는 자동 모드 한 번 실행해서 오늘 공략할 패턴과 리드 후보를 먼저 확보하는 게 맞습니다."

    return (
        "답할 수 있는 범위는 오늘 성과, 승인 대기, 비용/토큰, 실패 내역, 제안서 품질, 다음 추천 액션입니다. "
        "예를 들어 '오늘 성과 알려줘', '승인 대기 뭐 있어?', '다음 뭐 해야 해?'처럼 물어보면 됩니다."
    )
