# Sales Factory 테스트 방법

## 1. 준비

- **위치**: `sales_factory` 폴더에서 실행
- **가상환경**: `.venv` 활성화 후 진행
- **.env**: `GEMINI_API_KEY`, `MODEL=gemini/gemini-2.5-flash` 등 설정 확인

```powershell
cd "c:\Users\yeomj\OneDrive\Desktop\영업팀\sales_factory"
.\.venv\Scripts\Activate.ps1
```

---

## 2. Crew 실행 (전체 파이프라인)

리드 조사 → 웹 감사 → 랜딩 초안 → 마케팅 추천 → 제안서 → 아웃리치 → Notion 로깅까지 한 번에 돌립니다.

```powershell
run_crew
```

또는

```powershell
python -m sales_factory.main
```

- **리포트(결과 파일)**: **반드시 `sales_factory` 폴더를 현재 디렉터리로 두고** 실행해야 아래 파일들이 같은 폴더에 생성됩니다.
  - `competitor_analysis.md`, `landing_pages.md`, `marketing_plan.md`
  - `proposal.md`, `outreach_emails.md`, `notion_log_summary.md`
- Crew 종료 후 **Notion 후처리**(아웃리치 문구·PDF 링크 반영)는 자동 실행됩니다. `notion_log_summary.md`가 에이전트 마크다운 형식(## 회사명, **page_id_or_reason:** …)이어도 파싱되도록 되어 있습니다.
- **소요 시간**: 회사 10개 기준 대략 수 분 ~ 10분대 (모델/API 속도에 따라 다름)
- **토큰 비용**: 회사 10개 기준 1회 약 $0.10~0.35 수준 (문서: `docs/TOKEN_AND_COST_ESTIMATE.md`)

---

## 3. 빠른 테스트(회사 수 줄이기)

시간·비용을 줄이려면 **회사 수를 3~5개**로 줄여서 테스트할 수 있습니다.

**방법 A — 코드에서 기본값만 바꾸기**

`src/sales_factory/main.py` 안의 `default_inputs()` 에서:

```python
"max_companies": "3",   # "10" → "3" 으로 변경
```

저장 후 `run_crew` 다시 실행.

**방법 B — 트리거(JSON)로 실행**

`run_with_trigger` 를 쓰면 인자를 바꿀 수 있습니다 (구현되어 있을 경우).  
일반 테스트는 **방법 A**로 `max_companies` 만 바꿔서 쓰면 됩니다.

---

## 4. PDF 생성 (Crew 실행 후)

Crew가 끝나고 `proposal.md`, `landing_pages.md` 가 생긴 뒤:

```powershell
python generate_pdf_playwright.py
```

- **입력**: `proposal.md`, `landing_pages.md` (같은 폴더 기준). 스크립트는 **회사 구분을 `# 회사명` (H1) 한 줄로만 인식**하므로, 두 파일 모두 회사마다 `# [회사명]`으로 시작하는 블록이 있어야 회사 수만큼 PDF가 생성됨.
- **출력**: `output/` 아래 `{회사명}_제안서_{날짜}_playwright.pdf` (또는 `_playwright_1.pdf` 등)
- PDF가 이미 열려 있으면 새 파일명(`_1`, `_2` …)으로 저장됨
- **PDF가 1~2개만 나오면**: `proposal.md`·`landing_pages.md`에서 회사별 블록이 `# 회사명` (H1)으로 시작하는지 확인. `##`(H2)로만 구분돼 있으면 스크립트가 회사를 나누지 못함.

특정 회사만 PDF로 만들려면:

```powershell
python generate_pdf_playwright.py --company "동우문화"
```

---

## 5. 한 번에 테스트하는 순서 (요약)

1. `run_crew` 로 Crew 실행 (필요하면 `max_companies` 3으로 줄여서)
2. 끝나면 `python generate_pdf_playwright.py` 로 PDF 생성
3. `output/` 폴더에서 생성된 PDF 확인
4. **(최종 산출물)** 이메일 발송 + 노션 링크 반영:  
   `python send_emails.py --contacts contacts.csv --send --sync-notion`  
   - 이메일: PDF 첨부해서 발송  
   - 노션: `.env`에 `NOTION_PDF_BASE_URL`(output 폴더 공유 URL)이 있으면 해당 회사 페이지에 제안서 PDF 링크 자동 반영

---

## 6. Notion 로깅 테스트

- `.env` 에 `NOTION_API_KEY`, `NOTION_DATABASE_ID`, `NOTION_TITLE_PROPERTY` 설정
- Notion에서 해당 DB 페이지에 **Connections** 로 연동
- `run_crew` 시 마지막 단계에서 자동으로 Notion에 로그 생성

설정 방법: `docs/NOTION_SETUP.md` 참고.

---

## 7. 웹 대시보드 (산출물 보기)

run.bat 대신 **브라우저에서** 최근 산출물을 보려면 웹 대시보드를 켜면 됩니다.

1. **run_web.bat** 더블클릭  
   또는 터미널에서:
   ```powershell
   cd sales_factory
   .\.venv\Scripts\pip install streamlit   # 최초 1회
   .\.venv\Scripts\streamlit run web_dashboard.py
   ```
2. 브라우저가 자동으로 열리거나, **http://localhost:8501** 로 접속
3. 탭에서 **산출물 보기**(proposal.md, notion_log_summary.md), **출력 PDF 목록**, **업종 설정** 확인
4. **실행** 탭에서 파이프라인을 백그라운드로 시작할 수 있음 (실제 실행은 새 터미널 창에서 진행되며, 완료 후 대시보드에서 새로고침하면 최신 산출물 표시)

- **전체 파이프라인 실행**은 여전히 **run.bat** 권장 (Crew가 수 분 걸려 웹에서 동기 실행 시 브라우저가 오래 대기함)
