#!/usr/bin/env python3
"""
output/ 폴더의 Playwright 제안서 PDF를 Notion DB의 해당 회사 페이지에 넣습니다.

방식 1 — 파일 업로드 (권장): .env에 NOTION_PDF_UPLOAD=true 설정.
  → PDF를 Notion에 직접 업로드해, 해당 회사 페이지의 "Files" 속성에 첨부합니다.
  → Notion DB에 "제안서 PDF" 등 이름으로 **Files & media** 타입 속성을 추가하세요.

방식 2 — URL 링크: .env에 NOTION_PDF_BASE_URL=https://... (output 폴더 공유 URL) 설정.
  → 링크만 넣으려면 output/ 을 OneDrive/Drive 등에 올리고 공유 URL을 넣습니다.
  → Notion DB에 **URL** 타입 속성을 추가하세요.
"""

import json
import os
import re
import sys
from pathlib import Path
from urllib import error, parse, request

# .env 로드
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

NOTION_VERSION = "2022-06-28"
NOTION_VERSION_UPLOAD = "2025-09-03"  # File Upload API용
# 20MB 제한 (단일 파트 업로드)
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
# playwright PDF 파일명: {회사명}_제안서_YYYY-MM-DD_playwright.pdf 또는 ..._playwright_1.pdf
PDF_NAME_PATTERN = re.compile(
    r"^(.+)_제안서_\d{4}-\d{2}-\d{2}_playwright(_\d+)?\.pdf$",
    re.IGNORECASE,
)


def _database_id_with_hyphens(database_id: str) -> str:
    db_id = database_id.strip().replace("-", "")
    if len(db_id) == 32:
        return f"{db_id[0:8]}-{db_id[8:12]}-{db_id[12:16]}-{db_id[16:20]}-{db_id[20:32]}"
    return database_id


def _get_title_from_page(page: dict, title_property: str) -> str:
    """Notion 페이지에서 제목 속성의 plain_text를 합쳐서 반환."""
    props = page.get("properties") or {}
    title_prop = props.get(title_property)
    if not title_prop or title_prop.get("type") != "title":
        return ""
    titles = title_prop.get("title") or []
    return "".join(t.get("plain_text", "") for t in titles).strip()


def query_database(api_key: str, database_id: str) -> list:
    """Notion DB에서 모든 페이지(행) 목록을 가져옵니다."""
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    payload: dict = {}
    all_pages: list = []
    while True:
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Notion-Version": NOTION_VERSION,
            },
            method="POST",
        )
        with request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = data.get("results") or []
        all_pages.extend(results)
        next_cursor = data.get("next_cursor")
        if not next_cursor:
            break
        payload["start_cursor"] = next_cursor
    return all_pages


def update_page_url_property(
    api_key: str,
    page_id: str,
    property_name: str,
    url_value: str,
) -> bool:
    """Notion 페이지의 URL 속성을 업데이트합니다."""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    body = {
        "properties": {
            property_name: {"url": url_value[:2000]},
        }
    }
    req = request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION,
        },
        method="PATCH",
    )
    try:
        with request.urlopen(req, timeout=30):
            return True
    except error.HTTPError as e:
        print(f"  [HTTP {e.code}] {e.read().decode('utf-8', errors='ignore')}")
        return False


# ─── 파일 업로드 (Notion File Upload API, 2025-09-03) ─────────────────────────

def _upload_create(api_key: str, filename: str, content_type: str = "application/pdf") -> str | None:
    """File upload 객체 생성. 반환: file_upload_id 또는 None."""
    req = request.Request(
        "https://api.notion.com/v1/file_uploads",
        data=json.dumps({
            "filename": filename[:900],
            "content_type": content_type,
        }).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION_UPLOAD,
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("id")
    except error.HTTPError as e:
        print(f"  [create upload HTTP {e.code}] {e.read().decode('utf-8', errors='ignore')}")
        return None


def _upload_send(api_key: str, file_upload_id: str, file_path: Path) -> bool:
    """파일 바이너리를 Notion에 전송 (multipart/form-data)."""
    try:
        import requests
    except ImportError:
        print("  [오류] 파일 업로드에는 requests 패키지가 필요합니다: pip install requests")
        return False
    url = f"https://api.notion.com/v1/file_uploads/{file_upload_id}/send"
    with open(file_path, "rb") as f:
        files = {"file": (file_path.name, f, "application/pdf")}
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": NOTION_VERSION_UPLOAD,
        }
        resp = requests.post(url, files=files, headers=headers, timeout=60)
    if not resp.ok:
        print(f"  [send upload HTTP {resp.status_code}] {resp.text[:500]}")
        return False
    data = resp.json()
    if data.get("status") != "uploaded":
        print(f"  [send upload] status={data.get('status')}")
        return False
    return True


def _update_page_files_property(
    api_key: str,
    page_id: str,
    property_name: str,
    file_upload_id: str,
    filename: str,
) -> bool:
    """페이지의 Files 속성에 업로드한 파일을 첨부합니다 (Notion-Version 2025-09-03)."""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    body = {
        "properties": {
            property_name: {
                "files": [
                    {
                        "type": "file_upload",
                        "file_upload": {"id": file_upload_id},
                        "name": filename[:900],
                    }
                ]
            }
        }
    }
    req = request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION_UPLOAD,
        },
        method="PATCH",
    )
    try:
        with request.urlopen(req, timeout=30):
            return True
    except error.HTTPError as e:
        print(f"  [PATCH page HTTP {e.code}] {e.read().decode('utf-8', errors='ignore')}")
        return False


def company_from_pdf_filename(filename: str) -> str | None:
    """Playwright PDF 파일명에서 회사명 부분만 추출. 매칭 불가면 None."""
    m = PDF_NAME_PATTERN.match(Path(filename).name)
    if not m:
        return None
    return m.group(1).strip()


def find_matching_page(pages: list, title_property: str, company_from_pdf: str) -> dict | None:
    """회사명(PDF에서 추출)과 매칭되는 Notion 페이지를 찾습니다. 제목 포함 여부로 비교."""
    company_norm = company_from_pdf.lower().replace(" ", "").replace("_", "")
    for page in pages:
        title = _get_title_from_page(page, title_property)
        if not title:
            continue
        title_norm = title.lower().replace(" ", "")
        # PDF 회사명이 Notion 제목에 포함되거나, 제목이 PDF 회사명에 포함되면 매칭
        if (
            company_from_pdf in title
            or title in company_from_pdf
            or company_norm in title_norm
            or title_norm in company_norm
        ):
            return page
    return None


def _is_upload_mode() -> bool:
    v = (os.getenv("NOTION_PDF_UPLOAD") or "").strip().lower()
    return v in ("true", "1", "yes", "on")


def main() -> None:
    api_key = os.getenv("NOTION_API_KEY")
    database_id = os.getenv("NOTION_DATABASE_ID")
    base_url = (os.getenv("NOTION_PDF_BASE_URL") or "").strip().rstrip("/")
    title_property = os.getenv("NOTION_TITLE_PROPERTY", "Name")
    pdf_property = os.getenv("NOTION_PDF_PROPERTY", "Proposal PDF")
    use_upload = _is_upload_mode()

    if not api_key or not database_id:
        print("NOTION_API_KEY, NOTION_DATABASE_ID 가 .env에 필요합니다.")
        sys.exit(1)
    if not use_upload and not base_url:
        print(
            "PDF를 Notion에 넣는 방식을 선택하세요:\n"
            "  • 파일 업로드(권장): .env에 NOTION_PDF_UPLOAD=true 추가\n"
            "    → Notion DB에 '제안서 PDF' 등 이름으로 **Files & media** 타입 속성 추가\n"
            "  • URL 링크: .env에 NOTION_PDF_BASE_URL=https://... (output 폴더 공유 URL) 추가\n"
            "    → Notion DB에 **URL** 타입 속성 추가"
        )
        sys.exit(1)

    output_dir = Path(__file__).resolve().parent / "output"
    if not output_dir.is_dir():
        print(f"output 폴더가 없습니다: {output_dir}")
        sys.exit(1)

    pdf_files = [f for f in output_dir.glob("*.pdf") if PDF_NAME_PATTERN.match(f.name)]
    if not pdf_files:
        print("output/ 에 Playwright 형식의 제안서 PDF가 없습니다.")
        sys.exit(0)

    db_id = _database_id_with_hyphens(database_id)
    print("Notion DB 쿼리 중...")
    pages = query_database(api_key, db_id)
    print(f"  페이지 {len(pages)}개, PDF {len(pdf_files)}개 | 방식: {'파일 업로드' if use_upload else 'URL 링크'}\n")

    updated = 0
    for pdf_path in sorted(pdf_files):
        company = company_from_pdf_filename(pdf_path.name)
        if not company:
            continue
        page = find_matching_page(pages, title_property, company)
        if not page:
            print(f"  [건너뜀] {pdf_path.name} — 매칭되는 Notion 페이지 없음")
            continue
        page_id = page.get("id")
        if not page_id:
            continue

        if use_upload:
            size = pdf_path.stat().st_size
            if size > MAX_UPLOAD_BYTES:
                print(f"  [건너뜀] {pdf_path.name} — 20MB 초과 ({size // (1024*1024)}MB)")
                continue
            fid = _upload_create(api_key, pdf_path.name, "application/pdf")
            if not fid:
                print(f"  [실패] {company} — 업로드 생성 실패")
                continue
            if not _upload_send(api_key, fid, pdf_path):
                print(f"  [실패] {company} — 파일 전송 실패")
                continue
            if _update_page_files_property(api_key, page_id, pdf_property, fid, pdf_path.name):
                print(f"  [반영] {company} → {pdf_property} (업로드)")
                updated += 1
            else:
                print(f"  [실패] {company} — 페이지 속성 반영 실패")
        else:
            file_url = f"{base_url}/{parse.quote(pdf_path.name)}"
            if update_page_url_property(api_key, page_id, pdf_property, file_url):
                print(f"  [반영] {company} → {pdf_property}")
                updated += 1
            else:
                print(f"  [실패] {company}")

    print(f"\n완료: {updated}개 페이지에 PDF 반영.")


if __name__ == "__main__":
    main()
