#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib import error, request

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

NOTION_VERSION = "2022-06-28"
BASE_DIR = Path(__file__).resolve().parent
# Crew 실행 cwd에 md 파일이 생성되므로, BASE_DIR과 cwd 둘 다 확인
def _summary_path() -> Path:
    p = BASE_DIR / "notion_log_summary.md"
    if p.exists():
        return p
    cwd = Path.cwd()
    if cwd != BASE_DIR:
        q = cwd / "notion_log_summary.md"
        if q.exists():
            return q
    return p

def _outreach_path() -> Path:
    p = BASE_DIR / "outreach_emails.md"
    if p.exists():
        return p
    cwd = Path.cwd()
    if cwd != BASE_DIR:
        q = cwd / "outreach_emails.md"
        if q.exists():
            return q
    return p

AUTO_SECTION_START = "[AUTO_OUTREACH_START]"
AUTO_SECTION_END = "[AUTO_OUTREACH_END]"


def _request_json(url: str, method: str, api_key: str, payload: dict | None = None) -> dict:
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION,
        },
        method=method,
    )
    try:
        with request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        print(f"[notion-api] HTTP {exc.code} {method} {url.split('/')[-1]}: {body[:500]}")
        raise


def _request_no_content(url: str, method: str, api_key: str) -> None:
    req = request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": NOTION_VERSION,
        },
        method=method,
    )
    with request.urlopen(req, timeout=30):
        return


def _parse_contact_to_tel_email(contact: str) -> tuple[str, str]:
    """contact 문자열에서 전화번호(tel)와 이메일(email)을 구분해 반환."""
    tel, email = "", ""
    if not contact or not contact.strip():
        return tel, email
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
        if "@" in part and "." in part:
            candidate = part
            if " " in candidate:
                for token in candidate.split():
                    if email_re.match(token):
                        candidate = token
                        break
            if not email and (email_re.match(candidate) or ("@" in candidate and len(candidate) < 200)):
                email = candidate[:500]
        elif not tel:
            m = tel_re.search(part)
            if m:
                tel = m.group(0).strip()[:100]
    return tel or "", email or ""


def _parse_notion_summary_line_format(text: str) -> dict[str, dict]:
    """한 줄당 company_name=..., notion_logged=..., page_id_or_reason=... 형식."""
    entries: dict[str, dict] = {}
    pattern = re.compile(r"(\w+)=(.*?)(?=,\s+\w+=|$)")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if "notion_logged=" not in line:
            continue
        data = {match.group(1): match.group(2).strip() for match in pattern.finditer(line)}
        company_name = data.get("company_name", "")
        page_id = data.get("page_id") or data.get("page_id_or_reason", "")
        if company_name and page_id:
            entries[company_name] = data
    return entries


def _parse_notion_summary_markdown_format(text: str) -> dict[str, dict]:
    """에이전트 Final Answer 마크다운 형식: ## 회사명 / **key:** value."""
    entries: dict[str, dict] = {}
    current_company: str | None = None
    current_data: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current_company and (current_data.get("page_id_or_reason") or current_data.get("page_id")):
                entries[current_company] = current_data
            current_company = None
            current_data = {}
            continue
        m = re.match(r"^##\s+(.+)$", line)
        if m:
            if current_company and (current_data.get("page_id_or_reason") or current_data.get("page_id")):
                entries[current_company] = current_data
            current_company = m.group(1).strip()
            current_data = {"company_name": current_company}
            continue
        mm = re.match(r"^\*?\s*\*\*(\w+)\*\*:\s*(.*)$", line)
        if mm and current_company:
            key = mm.group(1).strip()
            val = mm.group(2).strip()
            if key in ("page_id", "page_id_or_reason", "company_name", "stage", "priority_score",
                       "icp_fit", "website_status", "recommended_channels", "outcome_status",
                       "first_contact_date", "expected_deal_size", "notion_logged", "contact", "tel", "email"):
                current_data[key] = val
            continue
    if current_company and (current_data.get("page_id_or_reason") or current_data.get("page_id")):
        entries[current_company] = current_data
    return entries


def _parse_notion_summary_table_format(text: str) -> dict[str, dict]:
    """에이전트가 마크다운 테이블로 저장한 경우: company_name | notion_logged | page_id_or_reason | ..."""
    entries: dict[str, dict] = {}
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) < 2:
        return entries
    # 헤더: company_name | notion_logged | page_id_or_reason | stage | ...
    # 파일 첫 줄이 아닌, 실제 "company_name"이 포함된 줄을 헤더로 찾는다
    header_idx = None
    for idx, line in enumerate(lines):
        if "|" in line and "company_name" in line.lower():
            header_idx = idx
            break
    if header_idx is None:
        return entries
    header_line = lines[header_idx]
    headers = [c.strip().lower().replace(" ", "_") for c in header_line.split("|")]
    headers = [h for h in headers if h]
    for i, line in enumerate(lines[header_idx + 1:], header_idx + 1):
        if re.match(r"^[\s|\-\s:]+$", line):
            continue
        if "|" not in line:
            break  # 주 요약 테이블 끝 — 서브 테이블 파싱 방지
        cells = [c.strip() for c in line.split("|")]
        cells = [c for c in cells if c is not None and c != ""]
        if len(cells) < len(headers):
            cells.extend([""] * (len(headers) - len(cells)))
        row = dict(zip(headers, cells[: len(headers)]))
        company_name = (row.get("company_name") or (cells[0] if cells else "")).strip()
        if not company_name:
            continue
        # page_id 없어도 됨(Notion DB에서 회사명으로 페이지 조회)
        entries[company_name] = {k: v for k, v in row.items() if v}
    return entries


def _parse_notion_summary_json_format(text: str) -> dict[str, dict]:
    """에이전트가 JSON 배열로 출력한 경우: [{company_name, stage, industry, ...}, ...]"""
    # 마크다운 코드 블록 안에 있는 JSON 추출
    stripped = re.sub(r"^```[a-z]*\n?", "", text.strip(), flags=re.MULTILINE)
    stripped = re.sub(r"```$", "", stripped.strip())
    try:
        data = json.loads(stripped.strip())
    except Exception:
        # 코드 블록 없이 순수 JSON인 경우 시도
        try:
            data = json.loads(text.strip())
        except Exception:
            return {}
    if not isinstance(data, list):
        return {}
    entries: dict[str, dict] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        company_name = str(item.get("company_name") or "").strip()
        if not company_name:
            continue
        # 모든 값을 문자열로 변환
        entries[company_name] = {k: str(v) for k, v in item.items() if v is not None and str(v).strip()}
    return entries


def parse_notion_summary(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}

    text = path.read_text(encoding="utf-8")
    entries = _parse_notion_summary_json_format(text)
    if not entries:
        entries = _parse_notion_summary_line_format(text)
    if not entries:
        entries = _parse_notion_summary_markdown_format(text)
    if not entries:
        entries = _parse_notion_summary_table_format(text)

    # contact가 있으면 tel/email로 구분해 채움 (기존 contact 값 유지)
    for entry in entries.values():
        contact = entry.get("contact", "")
        if contact and (not entry.get("tel") or not entry.get("email")):
            tel, email = _parse_contact_to_tel_email(contact)
            if tel and not entry.get("tel"):
                entry["tel"] = tel
            if email and not entry.get("email"):
                entry["email"] = email

    return entries


def parse_outreach(path: Path) -> dict[str, list[dict[str, str]]]:
    if not path.exists():
        return {}

    sequences: dict[str, list[dict[str, str]]] = {}
    current_company: str | None = None
    current_touch: dict[str, str] | None = None
    body_lines: list[str] = []
    in_body = False

    def flush_body() -> None:
        nonlocal body_lines, in_body
        if current_touch is not None and body_lines:
            current_touch["body"] = "\n".join(body_lines).strip()
        body_lines = []
        in_body = False

    def flush_touch() -> None:
        nonlocal current_touch
        flush_body()
        if current_company and current_touch:
            sequences.setdefault(current_company, []).append(current_touch)
        current_touch = None

    for line in path.read_text(encoding="utf-8").splitlines():
        company_match = re.match(r"^-\s+(.+)$", line)
        if company_match and "touchpoint:" not in line and "channel:" not in line:
            flush_touch()
            current_company = company_match.group(1).strip()
            sequences.setdefault(current_company, [])
            continue

        if current_company is None:
            continue

        stripped = line.lstrip()
        touch_match = re.match(r"^-\s+touchpoint:\s*(.+)$", stripped)
        if touch_match:
            flush_touch()
            current_touch = {
                "touchpoint": touch_match.group(1).strip(),
                "channel": "",
                "subject": "",
                "body": "",
                "cta": "",
            }
            continue

        if current_touch is None:
            continue

        if re.match(r"^-\s+body:\s*\|?$", stripped):
            in_body = True
            body_lines = []
            continue

        if in_body:
            next_field = re.match(r"^-\s+(channel|subject_if_email|cta|personalization_points)\s*:", stripped)
            if next_field:
                flush_body()
            else:
                body_lines.append(stripped)
                continue

        field_match = re.match(r"^-\s+(channel|subject_if_email|cta)\s*:\s*(.+)$", stripped)
        if not field_match:
            continue

        field_name, value = field_match.groups()
        if field_name == "subject_if_email":
            current_touch["subject"] = value.strip()
        elif field_name == "channel":
            current_touch["channel"] = value.strip()
        elif field_name == "cta":
            current_touch["cta"] = value.strip()

    flush_touch()
    return sequences


def patch_page_properties(api_key: str, page_id: str, first_contact_date: str) -> None:
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", first_contact_date):
        return

    payload = {
        "properties": {
            "First Contact Date": {
                "date": {"start": first_contact_date}
            }
        }
    }

    try:
        _request_json(f"https://api.notion.com/v1/pages/{page_id}", "PATCH", api_key, payload)
    except error.HTTPError:
        pass


def database_id_with_hyphens(database_id: str) -> str:
    db_id = database_id.strip().replace("-", "")
    if len(db_id) == 32:
        return f"{db_id[0:8]}-{db_id[8:12]}-{db_id[12:16]}-{db_id[16:20]}-{db_id[20:32]}"
    return database_id


def query_database(api_key: str, database_id: str) -> list[dict]:
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    payload: dict = {}
    pages: list[dict] = []
    while True:
        data = _request_json(url, "POST", api_key, payload)
        pages.extend(data.get("results", []))
        next_cursor = data.get("next_cursor")
        if not next_cursor:
            break
        payload["start_cursor"] = next_cursor
    return pages


def normalize_company_name(value: str) -> str:
    return re.sub(r"[\s_()\-]+", "", value or "").lower()


def get_page_title(page: dict, title_property: str) -> str:
    props = page.get("properties") or {}
    title_prop = props.get(title_property) or {}
    title_items = title_prop.get("title") or []
    return "".join(item.get("plain_text", "") for item in title_items).strip()


def find_page_by_company_name(pages: list[dict], title_property: str, company_name: str) -> dict | None:
    target = normalize_company_name(company_name)
    for page in pages:
        title = get_page_title(page, title_property)
        if not title:
            continue
        title_norm = normalize_company_name(title)
        if target == title_norm or target in title_norm or title_norm in target:
            return page
    return None


def rt(text: str) -> dict:
    return {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]}


def sel(name: str) -> dict:
    return {"select": {"name": name[:100]}}


def build_page_properties(title_property: str, entry: dict) -> dict:
    props: dict = {
        title_property: {
            "title": [{"type": "text", "text": {"content": entry.get("company_name", "")[:2000]}}]
        }
    }
    if entry.get("stage"):
        props["Stage"] = sel(entry["stage"])
    if entry.get("icp_fit"):
        props["ICP Fit"] = sel(entry["icp_fit"])
    if entry.get("website_status"):
        props["Website Status"] = sel(entry["website_status"])
    if entry.get("outcome_status"):
        props["Outcome Status"] = sel(entry["outcome_status"])
    if entry.get("priority_score", "").isdigit():
        props["Priority Score"] = {"number": int(entry["priority_score"])}
    if entry.get("recommended_channels"):
        props["Recommended Channels"] = rt(entry["recommended_channels"])
    if entry.get("expected_deal_size"):
        props["Expected Deal Size"] = rt(entry["expected_deal_size"])
    if re.match(r"^\d{4}-\d{2}-\d{2}$", entry.get("first_contact_date", "")):
        props["First Contact Date"] = {"date": {"start": entry["first_contact_date"]}}
    if entry.get("industry"):
        props["Industry"] = rt(entry["industry"])
    if entry.get("location"):
        props["Location"] = rt(entry["location"])
    if entry.get("tel"):
        props["Tel"] = rt(entry["tel"])
    if entry.get("email"):
        props["Email"] = rt(entry["email"])
    if entry.get("contact"):
        props["Contact"] = rt(entry["contact"])
    return props


def build_page_children(entry: dict) -> list:
    """entry 데이터로 페이지 요약 블록 콘텐츠 생성."""
    def h2(text: str) -> dict:
        return {"object": "block", "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]}}

    def para(text: str) -> dict:
        return {"object": "block", "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": text[:1900]}}]}}

    divider: dict = {"object": "block", "type": "divider", "divider": {}}
    WS_KO = {"no_website": "웹사이트 없음", "outdated_website": "웹사이트 구형", "active_website": "웹사이트 활성"}
    blocks: list = []

    # 회사 개요
    overview = []
    if entry.get("industry"):
        overview.append(f"업종: {entry['industry']}")
    if entry.get("location"):
        overview.append(f"위치: {entry['location']}")
    if entry.get("tel"):
        overview.append(f"전화: {entry['tel']}")
    if entry.get("email"):
        overview.append(f"이메일: {entry['email']}")
    if not entry.get("tel") and not entry.get("email") and entry.get("contact"):
        overview.append(f"연락처: {entry['contact']}")
    if overview:
        blocks += [h2("회사 개요"), para("\n".join(overview))]

    # 파이프라인 평가
    assessment = []
    if entry.get("website_status"):
        assessment.append(f"웹사이트 상태: {WS_KO.get(entry['website_status'], entry['website_status'])}")
    if entry.get("icp_fit"):
        assessment.append(f"ICP 적합성: {entry['icp_fit']}")
    if entry.get("priority_score"):
        assessment.append(f"우선순위 점수: {entry['priority_score']}/100")
    if assessment:
        blocks += [h2("파이프라인 평가"), para("\n".join(assessment))]

    # 마케팅 계획
    if entry.get("recommended_channels"):
        blocks += [h2("마케팅 계획"), para(f"추천 채널: {entry['recommended_channels']}")]

    # 현황
    status = []
    if entry.get("outcome_status"):
        status.append(f"결과 상태: {entry['outcome_status']}")
    if entry.get("first_contact_date"):
        status.append(f"최초 접촉일: {entry['first_contact_date']}")
    if entry.get("expected_deal_size"):
        status.append(f"예상 계약 규모: {entry['expected_deal_size']}")
    if status:
        blocks += [h2("현황"), para("\n".join(status)), divider]

    return blocks


def create_page(api_key: str, database_id: str, title_property: str, entry: dict) -> dict:
    children = build_page_children(entry)
    payload = {
        "parent": {"database_id": database_id},
        "properties": build_page_properties(title_property, entry),
        "children": children,
    }
    try:
        return _request_json("https://api.notion.com/v1/pages", "POST", api_key, payload)
    except error.HTTPError:
        # 속성 스키마 불일치 시 제목 + 블록으로 fallback
        fallback = {
            "parent": {"database_id": database_id},
            "properties": {
                title_property: {
                    "title": [{"type": "text", "text": {"content": entry.get("company_name", "")[:2000]}}]
                }
            },
            "children": children,
        }
        return _request_json("https://api.notion.com/v1/pages", "POST", api_key, fallback)


def update_page_properties(api_key: str, page_id: str, title_property: str, entry: dict) -> None:
    payload = {"properties": build_page_properties(title_property, entry)}
    try:
        _request_json(f"https://api.notion.com/v1/pages/{page_id}", "PATCH", api_key, payload)
    except error.HTTPError:
        minimal_payload = {
            "properties": {
                title_property: {
                    "title": [{"type": "text", "text": {"content": entry.get("company_name", "")[:2000]}}]
                }
            }
        }
        _request_json(f"https://api.notion.com/v1/pages/{page_id}", "PATCH", api_key, minimal_payload)


def upsert_page(api_key: str, database_id: str, title_property: str, entry: dict, pages: list[dict]) -> str | None:
    company_name = entry.get("company_name", "")
    if not company_name:
        return None

    page = find_page_by_company_name(pages, title_property, company_name)
    if page:
        page_id = page.get("id")
        if page_id:
            update_page_properties(api_key, page_id, title_property, entry)
            # 블록이 없는 페이지에만 요약 블록 추가
            try:
                existing = list_block_children(api_key, page_id)
                if not existing:
                    children = build_page_children(entry)
                    if children:
                        _request_json(
                            f"https://api.notion.com/v1/blocks/{page_id}/children",
                            "PATCH", api_key, {"children": children}
                        )
            except error.HTTPError:
                pass
            return page_id

    created = create_page(api_key, database_id, title_property, entry)
    page_id = created.get("id")
    if page_id:
        pages.append(created)
    return page_id


def list_block_children(api_key: str, block_id: str) -> list[dict]:
    url = f"https://api.notion.com/v1/blocks/{block_id}/children?page_size=100"
    data = _request_json(url, "GET", api_key)
    return data.get("results", [])


def rich_text_plain(block: dict) -> str:
    block_type = block.get("type", "")
    payload = block.get(block_type, {})
    rich_text = payload.get("rich_text", [])
    return "".join(item.get("plain_text", "") for item in rich_text).strip()


def clear_existing_outreach_section(api_key: str, page_id: str) -> None:
    try:
        children = list_block_children(api_key, page_id)
    except error.HTTPError:
        return

    deleting = False
    delete_ids: list[str] = []
    for block in children:
        text = rich_text_plain(block)
        block_id = block.get("id")
        if not block_id:
            continue
        if text == AUTO_SECTION_START:
            deleting = True
            delete_ids.append(block_id)
            continue
        if deleting:
            delete_ids.append(block_id)
            if text == AUTO_SECTION_END:
                deleting = False
                break

    for block_id in delete_ids:
        try:
            _request_no_content(f"https://api.notion.com/v1/blocks/{block_id}", "DELETE", api_key)
        except error.HTTPError:
            pass


def find_pdf_path(company_name: str) -> str:
    output_dir = BASE_DIR / "output"
    if not output_dir.exists():
        return ""
    safe = re.sub(r'[\\/*?:"<>|]', "_", company_name)
    candidates = sorted(output_dir.glob(f"{safe}_*playwright*.pdf"), reverse=True)
    if candidates:
        return str(candidates[0])
    for pdf in sorted(output_dir.glob("*.pdf"), reverse=True):
        if normalize_company_name(company_name) in normalize_company_name(pdf.stem):
            return str(pdf)
    return ""


def split_text(text: str, size: int = 1800) -> list[str]:
    normalized = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not normalized:
        return []

    chunks: list[str] = []
    current = ""
    for piece in normalized.splitlines():
        candidate = piece if not current else f"{current}\n{piece}"
        if len(candidate) <= size:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(piece) > size:
            chunks.append(piece[:size])
            piece = piece[size:]
        current = piece
    if current:
        chunks.append(current)
    return chunks


def append_outreach_blocks(
    api_key: str,
    page_id: str,
    first_contact_date: str,
    touches: list[dict[str, str]],
    pdf_path: str = "",
) -> None:
    children: list[dict] = [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": AUTO_SECTION_START}}]},
        },
        {"object": "block", "type": "divider", "divider": {}},
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Outreach Sequence"}}]},
        },
    ]

    if first_contact_date:
        children.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"type": "text", "text": {"content": f"First contact date: {first_contact_date}"}}
                    ]
                },
            }
        )
    if pdf_path:
        children.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": f"Local PDF path: {pdf_path}"[:1900]}}]
                },
            }
        )

    for touch in touches:
        heading = f"{touch.get('touchpoint', '')} | {touch.get('channel', '')}".strip(" |")
        children.append(
            {
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": heading[:200]}}]},
            }
        )

        subject = touch.get("subject", "").strip()
        if subject:
            children.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": f"Subject: {subject}"[:1900]}}]
                    },
                }
            )

        body = touch.get("body", "").strip()
        if body:
            for chunk in split_text(body):
                children.append(
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]},
                    }
                )

        cta = touch.get("cta", "").strip()
        if cta:
            children.append(
                {
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [{"type": "text", "text": {"content": f"CTA: {cta}"[:1900]}}]
                    },
                }
            )

    children.append(
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": AUTO_SECTION_END}}]},
        }
    )

    payload = {"children": children[:100]}
    _request_json(f"https://api.notion.com/v1/blocks/{page_id}/children", "PATCH", api_key, payload)


def maybe_sync_pdf() -> None:
    upload_enabled = (os.getenv("NOTION_PDF_UPLOAD") or "").strip().lower() in {"true", "1", "yes", "on"}
    base_url = (os.getenv("NOTION_PDF_BASE_URL") or "").strip()
    if not upload_enabled and not base_url:
        return

    sync_script = BASE_DIR / "sync_pdf_to_notion.py"
    if not sync_script.exists():
        return

    subprocess.run([sys.executable, str(sync_script)], cwd=str(BASE_DIR), check=False)


def main() -> int:
    api_key = os.getenv("NOTION_API_KEY")
    database_id = os.getenv("NOTION_DATABASE_ID")
    title_property = os.getenv("NOTION_TITLE_PROPERTY", "Name")
    if not api_key:
        print("[notion-post] NOTION_API_KEY missing, skip.")
        return 0
    if not database_id:
        print("[notion-post] NOTION_DATABASE_ID missing, skip.")
        return 0

    summary_path = _summary_path()
    outreach_path = _outreach_path()
    if not summary_path.exists():
        print("[notion-post] notion_log_summary.md missing (checked %s and cwd), skip." % BASE_DIR)
        return 0
    page_entries = parse_notion_summary(summary_path)
    outreach = parse_outreach(outreach_path)
    if not page_entries:
        print("[notion-post] notion_log_summary.md: no page ids parsed (file format may have changed), skip.")
        return 0
    print("[notion-post] summary: %s (%d companies)" % (summary_path, len(page_entries)))

    db_id = database_id_with_hyphens(database_id)
    try:
        pages = query_database(api_key, db_id)
    except Exception as exc:  # noqa: BLE001
        print(f"[notion-post] failed to query database: {exc}")
        return 1

    updated = 0
    for company_name, entry in page_entries.items():
        entry["company_name"] = company_name
        page_id = upsert_page(api_key, db_id, title_property, entry, pages)
        if not page_id:
            continue

        first_contact_date = entry.get("first_contact_date", "")
        touches = outreach.get(company_name, [])

        if first_contact_date:
            patch_page_properties(api_key, page_id, first_contact_date)

        if touches:
            try:
                clear_existing_outreach_section(api_key, page_id)
                pdf_path = find_pdf_path(company_name)
                append_outreach_blocks(api_key, page_id, first_contact_date, touches, pdf_path)
                updated += 1
            except error.HTTPError as exc:
                print(f"[notion-post] failed to append outreach for {company_name}: HTTP {exc.code}")
            except Exception as exc:  # noqa: BLE001
                print(f"[notion-post] failed to append outreach for {company_name}: {exc}")

    maybe_sync_pdf()
    print(f"[notion-post] updated {updated} notion page(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
