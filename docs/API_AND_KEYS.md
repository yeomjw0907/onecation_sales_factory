# 필요한 API·키 정리

**결론: Crew 자체는 Gemini 하나로 돌아감. 나머지는 선택 기능용.**

---

## 1. 필수 (Crew 실행)

| 용도 | 환경 변수 | 비고 |
|------|------------|------|
| **LLM** | `GEMINI_API_KEY`, `MODEL` | 지금 쓰는 건 **Gemini** 하나. 리드 발굴·감사·경쟁 분석·제안서·이메일 문구·Notion 로그까지 **전부 Gemini가 생성**. 별도 “검색 API” 없이도 동작함. |

---

## 2. 도구별 — 추가 API 여부

| 도구 | 추가 API 키 | 설명 |
|------|-------------|------|
| **ScrapeWebsiteTool** (website_auditor, competitor_analyst) | **없음** | URL만 있으면 HTTP로 페이지 가져옴. GEMINI_API_KEY만 있으면 됨. |
| **NotionLogTool** (notion_logger) | `NOTION_API_KEY`, `NOTION_DATABASE_ID` | Notion 로깅 쓸 때만. 없으면 로그는 로컬 요약만. |
| **리드 실시간 검색** | **없음** (Gemini로 가능) | 지역·업종으로 “지금 검색”이 필요하면 **Gemini API의 Google Search grounding** 사용. **같은 GEMINI_API_KEY**로 가능하고, Serper 같은 별도 검색 API는 필요 없음. (Grounding은 Gemini 유료 옵션, 건당 과금.) |

---

## 3. 선택 (기능별)

| 기능 | 환경 변수 | 용도 |
|------|------------|------|
| 이메일 발송 | `SMTP_*` | send_emails.py |
| Notion에 PDF 링크 | `NOTION_PDF_BASE_URL` 또는 `NOTION_PDF_UPLOAD=true` | sync_pdf_to_notion.py |
| (미사용) Serper 검색 | `SERPER_API_KEY` | 쓰지 않아도 됨. 리드 검색은 Gemini grounding으로 가능. |

---

**요약**: **Gemini로 다 할 수 있음.** ScrapeWebsiteTool은 API 키 없음. 리드 실시간 검색도 Gemini Google Search grounding 쓰면 되고, Serper 등 별도 API는 필요 없음.
