import json
import os
import re
from typing import Any, Dict, Optional, Type
from urllib import error, request

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


def parse_contact_to_tel_email(contact: str) -> tuple[str, str]:
    """contact 문자열에서 전화번호(tel)와 이메일(email)을 구분해 반환."""
    tel, email = "", ""
    if not contact or not contact.strip():
        return tel, email
    # 쉼표, 슬래시, 줄바꿈으로 분리
    parts = re.split(r"[,/]\s*|\s+/\s+|\n", contact.strip())
    email_re = re.compile(r"^[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}$")
    tel_re = re.compile(
        r"01[0-9][-\s]?\d{3,4}[-\s]?\d{4}|"
        r"02[-\s]?\d{3,4}[-\s]?\d{4}|"
        r"0[3-9]\d{1}[-\s]?\d{3,4}[-\s]?\d{4}|"
        r"\+82\s*0?\d[-\s]?\d{3,4}[-\s]?\d{4}"
    )
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # 이메일: @ 포함 또는 이메일 패턴
        if "@" in part and "." in part:
            candidate = part
            if " " in candidate:
                for token in candidate.split():
                    if email_re.match(token):
                        candidate = token
                        break
            if not email and (email_re.match(candidate) or ("@" in candidate and len(candidate) < 200)):
                email = candidate[:500]
        # 전화번호: 한국 형식
        elif not tel:
            m = tel_re.search(part)
            if m:
                tel = m.group(0).strip()[:100]
    return tel or "", email or ""


class NotionLogToolInput(BaseModel):
    """Input schema for NotionLogTool."""

    company_name: str = Field(..., description="Company name to log in Notion")
    stage: str = Field(..., description="Pipeline stage name (e.g. prospecting)")
    summary: str = Field(..., description="2-3 sentence summary of audit result and proposal highlight")
    industry: str = Field(default="", description="Company industry")
    location: str = Field(default="", description="Company location")
    contact: str = Field(default="", description="Contact info (email and/or phone); will be split into Tel and Email in Notion")
    tel: str = Field(default="", description="Phone number only (optional; if omitted, parsed from contact)")
    email: str = Field(default="", description="Email only (optional; if omitted, parsed from contact)")
    website_status: str = Field(default="", description="no_website / outdated_website / active_website")
    priority_score: Optional[int] = Field(default=None, description="Priority score 1-100 from website audit")
    icp_fit: str = Field(default="", description="yes / no")
    recommended_channels: str = Field(default="", description="Comma-separated recommended marketing channels")
    outcome_status: str = Field(default="", description="Current outcome status (e.g. new_lead)")
    first_contact_date: str = Field(default="", description="First contact date in YYYY-MM-DD format")
    expected_deal_size: str = Field(default="", description="Expected deal size estimate (e.g. 300,000원/월)")
    proposal_pdf_url: str = Field(default="", description="Optional URL to the proposal PDF (e.g. shared OneDrive/Drive link)")


# Notion에 표시할 때 영어 값 → 한국어 (사용자가 보기 쉽도록)
STAGE_KO = {"prospecting": "영업 후보", "qualification": "자격 검토", "proposal": "제안", "negotiation": "협상", "closed": "종료"}
ICP_FIT_KO = {"yes": "적합", "no": "부적합"}
WEBSITE_STATUS_KO = {"no_website": "웹사이트 없음", "outdated_website": "웹사이트 구형", "active_website": "웹사이트 활성"}
OUTCOME_STATUS_KO = {"new_lead": "신규 리드", "contacted": "연락함", "meeting_scheduled": "미팅 예정", "proposal_sent": "제안서 발송", "won": "성사", "lost": "실패"}


def _to_ko(value: str, mapping: dict) -> str:
    if not value or not value.strip():
        return value
    v = value.strip().lower()
    return mapping.get(v, value)


class NotionLogTool(BaseTool):
    name: str = "notion_log_tool"
    description: str = (
        "Log pipeline progress to a Notion database page. "
        "Accepts company details, audit results, and marketing plan fields. "
        "If credentials are missing, returns a fallback status message."
    )
    args_schema: Type[BaseModel] = NotionLogToolInput

    def _run(
        self,
        company_name: str,
        stage: str,
        summary: str,
        industry: str = "",
        location: str = "",
        contact: str = "",
        tel: str = "",
        email: str = "",
        website_status: str = "",
        priority_score: Optional[int] = None,
        icp_fit: str = "",
        recommended_channels: str = "",
        outcome_status: str = "",
        first_contact_date: str = "",
        expected_deal_size: str = "",
        proposal_pdf_url: str = "",
    ) -> str:
        api_key = os.getenv("NOTION_API_KEY")
        database_id = os.getenv("NOTION_DATABASE_ID")
        title_property = os.getenv("NOTION_TITLE_PROPERTY", "Name")

        if not api_key or not database_id:
            return (
                "Notion credentials are missing. "
                "Set NOTION_API_KEY and NOTION_DATABASE_ID to enable API logging."
            )

        # Format database_id with hyphens (8-4-4-4-12)
        db_id = database_id.strip().replace("-", "")
        if len(db_id) == 32:
            database_id_for_api = (
                f"{db_id[0:8]}-{db_id[8:12]}-{db_id[12:16]}-{db_id[16:20]}-{db_id[20:32]}"
            )
        else:
            database_id_for_api = database_id

        # Notion에 표시할 값은 한국어로 변환
        stage_ko = _to_ko(stage, STAGE_KO)
        icp_fit_ko = _to_ko(icp_fit, ICP_FIT_KO)
        website_status_ko = _to_ko(website_status, WEBSITE_STATUS_KO)
        outcome_status_ko = _to_ko(outcome_status, OUTCOME_STATUS_KO)

        # contact에서 전화/이메일 미지정 시 파싱
        if not tel and not email and contact:
            tel, email = parse_contact_to_tel_email(contact)

        properties = self._build_properties(
            title_property, company_name, stage_ko, icp_fit_ko, website_status_ko,
            priority_score, industry, location, contact, tel, email, recommended_channels,
            outcome_status_ko, first_contact_date, expected_deal_size,
            proposal_pdf_url,
        )
        children = self._build_children(
            stage_ko, summary, industry, location, contact, tel, email, website_status_ko,
            priority_score, icp_fit_ko, recommended_channels, outcome_status_ko,
            first_contact_date, expected_deal_size,
        )

        payload: Dict[str, Any] = {
            "parent": {"database_id": database_id_for_api},
            "properties": properties,
            "children": children,
        }

        result = self._post_page(api_key, payload)

        # If database schema doesn't have the extra columns, fall back to title-only
        if "HTTP error 400" in result:
            fallback_payload: Dict[str, Any] = {
                "parent": {"database_id": database_id_for_api},
                "properties": {
                    title_property: {
                        "title": [{"type": "text", "text": {"content": company_name}}]
                    }
                },
                "children": children,
            }
            fallback_result = self._post_page(api_key, fallback_payload)
            if "error" not in fallback_result.lower():
                return (
                    fallback_result
                    + " (Note: property columns skipped — add Stage, ICP Fit, "
                    "Website Status, Outcome Status, Priority Score, Industry, "
                    "Location, Tel, Email, Contact, Recommended Channels, Expected Deal Size, "
                    "First Contact Date, Proposal PDF to your Notion database for full CRM tracking)"
                )
            return fallback_result

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_properties(
        self,
        title_property: str,
        company_name: str,
        stage: str,
        icp_fit: str,
        website_status: str,
        priority_score: Optional[int],
        industry: str,
        location: str,
        contact: str,
        tel: str,
        email: str,
        recommended_channels: str,
        outcome_status: str,
        first_contact_date: str,
        expected_deal_size: str,
        proposal_pdf_url: str = "",
    ) -> Dict[str, Any]:
        def rt(text: str) -> Dict[str, Any]:
            return {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]}

        def sel(name: str) -> Dict[str, Any]:
            return {"select": {"name": name[:100]}}

        props: Dict[str, Any] = {
            title_property: {
                "title": [{"type": "text", "text": {"content": company_name}}]
            }
        }

        if stage:
            props["Stage"] = sel(stage)
        if icp_fit:
            props["ICP Fit"] = sel(icp_fit)
        if website_status:
            props["Website Status"] = sel(website_status)
        if outcome_status:
            props["Outcome Status"] = sel(outcome_status)
        if priority_score is not None:
            props["Priority Score"] = {"number": priority_score}
        if industry:
            props["Industry"] = rt(industry)
        if location:
            props["Location"] = rt(location)
        if tel:
            props["Tel"] = rt(tel)
        if email:
            props["Email"] = rt(email)
        if contact:
            props["Contact"] = rt(contact)
        if recommended_channels:
            props["Recommended Channels"] = rt(recommended_channels)
        if expected_deal_size:
            props["Expected Deal Size"] = rt(expected_deal_size)
        if first_contact_date and re.match(r"^\d{4}-\d{2}-\d{2}$", first_contact_date):
            props["First Contact Date"] = {"date": {"start": first_contact_date}}
        pdf_prop = os.getenv("NOTION_PDF_PROPERTY", "Proposal PDF")
        if pdf_prop and proposal_pdf_url and proposal_pdf_url.strip().startswith(("http://", "https://")):
            props[pdf_prop] = {"url": proposal_pdf_url.strip()[:2000]}

        return props

    def _build_children(
        self,
        stage: str,
        summary: str,
        industry: str,
        location: str,
        contact: str,
        tel: str,
        email: str,
        website_status: str,
        priority_score: Optional[int],
        icp_fit: str,
        recommended_channels: str,
        outcome_status: str,
        first_contact_date: str,
        expected_deal_size: str,
    ) -> list:
        def h2(text: str) -> Dict[str, Any]:
            return {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": text}}]
                },
            }

        def para(text: str) -> Dict[str, Any]:
            return {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": text[:1900]}}]
                },
            }

        divider: Dict[str, Any] = {"object": "block", "type": "divider", "divider": {}}
        blocks = []

        # 회사 개요
        overview_lines = []
        if industry:
            overview_lines.append(f"업종: {industry}")
        if location:
            overview_lines.append(f"위치: {location}")
        if tel:
            overview_lines.append(f"전화: {tel}")
        if email:
            overview_lines.append(f"이메일: {email}")
        if not tel and not email and contact:
            overview_lines.append(f"연락처: {contact}")
        if overview_lines:
            blocks.append(h2("회사 개요"))
            blocks.append(para("\n".join(overview_lines)))

        # 파이프라인 평가
        assessment_lines = []
        if website_status:
            assessment_lines.append(f"웹사이트 상태: {website_status}")
        if icp_fit:
            assessment_lines.append(f"ICP 적합성: {icp_fit}")
        if priority_score is not None:
            assessment_lines.append(f"우선순위 점수: {priority_score}/100")
        if assessment_lines:
            blocks.append(h2("파이프라인 평가"))
            blocks.append(para("\n".join(assessment_lines)))

        # 마케팅 계획
        if recommended_channels:
            blocks.append(h2("마케팅 계획"))
            blocks.append(para(f"추천 채널: {recommended_channels}"))

        # 현황
        status_lines = []
        if outcome_status:
            status_lines.append(f"결과 상태: {outcome_status}")
        if first_contact_date:
            status_lines.append(f"최초 접촉일: {first_contact_date}")
        if expected_deal_size:
            status_lines.append(f"예상 계약 규모: {expected_deal_size}")
        if status_lines:
            blocks.append(h2("현황"))
            blocks.append(para("\n".join(status_lines)))

        # 요약
        blocks.append(divider)
        blocks.append(h2("요약"))
        blocks.append(para(f"[{stage}] {summary}"[:1900]))

        return blocks

    def _post_page(self, api_key: str, payload: Dict[str, Any]) -> str:
        req = request.Request(
            "https://api.notion.com/v1/pages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                page_id = body.get("id", "unknown")
                return f"Logged to Notion successfully. page_id={page_id}"
        except error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="ignore")
            return f"Notion API HTTP error {e.code}: {detail}"
        except Exception as e:  # noqa: BLE001
            return f"Notion API error: {e}"
