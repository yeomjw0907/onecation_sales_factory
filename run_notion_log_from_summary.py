#!/usr/bin/env python3
"""
notion_log_summary.md에 에이전트가 "tool_code"로만 출력하고 실제 도구를 호출하지 않았을 때,
해당 내용을 파싱해서 Notion API를 직접 호출해 주는 보정 스크립트.

사용: python run_notion_log_from_summary.py [notion_log_summary.md 경로]
"""

import json
import os
import re
import sys
from pathlib import Path

# 프로젝트 루트에서 .env 로드
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

# NotionLogTool 사용
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from sales_factory.tools import NotionLogTool


def _extract_inner_args(tool_code: str) -> str:
    """tool_code 문자열에서 notion_log_tool(...) 안의 인자 부분만 추출."""
    start = "notion_log_tool("
    i = tool_code.find(start)
    if i == -1:
        return ""
    i += len(start)
    depth = 1
    j = i
    while j < len(tool_code) and depth > 0:
        if tool_code[j] == "(":
            depth += 1
        elif tool_code[j] == ")":
            depth -= 1
        j += 1
    return tool_code[i : j - 1].strip()


def _parse_kwargs(inner: str) -> dict:
    """'key=value', key=123 형태의 문자열을 kwargs dict로 파싱."""
    kwargs: dict = {}
    # key='...' (다음 키 전 또는 괄호 닫기 전까지) 또는 key=숫자
    pattern = r"(\w+)=(\d+)|(\w+)='((?:[^'\\]|\\.)*?)'(?=\s*,\s*\w+=|\s*\))|(\w+)=\"((?:[^\"\\]|\\.)*?)\"(?=\s*,\s*\w+=|\s*\))"
    for m in re.finditer(pattern, inner):
        if m.group(1):
            kwargs[m.group(1)] = int(m.group(2))
        elif m.group(3):
            kwargs[m.group(3)] = m.group(4).replace("\\'", "'").replace('\\"', '"')
        elif m.group(5):
            kwargs[m.group(5)] = m.group(6).replace("\\'", "'").replace('\\"', '"')
    return kwargs


def main() -> None:
    if not os.getenv("NOTION_API_KEY") or not os.getenv("NOTION_DATABASE_ID"):
        print("NOTION_API_KEY, NOTION_DATABASE_ID 가 .env에 필요합니다.")
        sys.exit(1)
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "notion_log_summary.md"
    if not path.exists():
        print(f"파일 없음: {path}")
        sys.exit(1)
    print(f"읽는 파일: {path}\n")

    text = path.read_text(encoding="utf-8")
    # JSON 배열 추출 (```json ... ``` 또는 그냥 [ ... ])
    json_match = re.search(r"\[[\s\S]*\]", text)
    if not json_match:
        print("JSON 배열을 찾을 수 없습니다.")
        sys.exit(1)

    try:
        items = json.loads(json_match.group(0))
    except json.JSONDecodeError as e:
        print(f"JSON 파싱 오류: {e}")
        sys.exit(1)

    tool = NotionLogTool()
    success = 0
    fail = 0
    for item in items:
        if item.get("action") != "tool_code" or "notion_log_tool" not in (item.get("tool_code") or ""):
            continue
        code = item["tool_code"]
        inner = _extract_inner_args(code)
        if not inner:
            fail += 1
            continue
        kwargs = _parse_kwargs(inner)
        if "company_name" not in kwargs:
            fail += 1
            continue
        # NotionLogTool._run에 전달 (필수 3개 + 선택)
        required = {"company_name", "stage", "summary"}
        if not required.issubset(kwargs.keys()):
            kwargs.setdefault("stage", "prospecting")
            kwargs.setdefault("summary", "")
        try:
            result = tool._run(
                company_name=kwargs.get("company_name", ""),
                stage=kwargs.get("stage", "prospecting"),
                summary=kwargs.get("summary", ""),
                industry=kwargs.get("industry", ""),
                location=kwargs.get("location", ""),
                contact=kwargs.get("contact", ""),
                tel=kwargs.get("tel", ""),
                email=kwargs.get("email", ""),
                website_status=kwargs.get("website_status", ""),
                priority_score=kwargs.get("priority_score"),
                icp_fit=kwargs.get("icp_fit", ""),
                recommended_channels=kwargs.get("recommended_channels", ""),
                outcome_status=kwargs.get("outcome_status", ""),
                first_contact_date=kwargs.get("first_contact_date", ""),
                expected_deal_size=kwargs.get("expected_deal_size", ""),
                proposal_pdf_url=kwargs.get("proposal_pdf_url", ""),
            )
            if "successfully" in result or "page_id=" in result:
                success += 1
                print(f"  [OK] {kwargs.get('company_name', '')}")
            else:
                fail += 1
                print(f"  [FAIL] {kwargs.get('company_name', '')}: {result[:80]}")
        except Exception as e:
            fail += 1
            print(f"  [ERR] {kwargs.get('company_name', '')}: {e}")

    if success == 0 and fail == 0:
        print("실행할 notion_log_tool 호출이 없습니다. (tool_code 항목이 없거나 형식이 다름)")
        sys.exit(0)
    print(f"\n완료: 성공 {success}, 실패 {fail}")


if __name__ == "__main__":
    main()
