# Notion API 설정 및 페이지 구성 가이드

Sales Factory Crew가 Notion에 로그를 남기려면 아래 순서대로 설정하면 됩니다.

---

## 1. Notion 통합(연동) 만들기 → API 키 발급

1. **Notion 개발자 사이트 접속**  
   https://www.notion.so/my-integrations

2. **"+ New integration"** 클릭

3. **이름** 입력 (예: `Sales Factory`)

4. **Associated workspace**에서 사용할 워크스페이스 선택

5. **Capabilities**에서  
   - **Read content**, **Update content**, **Insert content** 체크  
   (필요하면 **Read user information** 등도 체크)

6. **Submit** 클릭

7. **Internal Integration Secret** 값 복사  
   - `secret_xxxx...` 형태  
   - 이 값이 **NOTION_API_KEY**입니다. (나중에 `.env`에 넣음)

---

## 2. Notion에서 DB(데이터베이스) 만들기

Crew는 **데이터베이스 안에 페이지(행)를 추가**하는 방식으로 로그를 씁니다.  
그래서 먼저 “로그 받을 DB”를 하나 만들어야 합니다.

### 2-1. DB 생성

1. Notion에서 **원하는 페이지**(예: 영업팀 대시보드)로 이동
2. 새 블록 추가: `/table` 또는 **Table - Full page** 선택
3. 데이터베이스 이름 지정 (예: `Sales Pipeline` 또는 `리드 로그`)

### 2-2. DB 컬럼 구조 (권장)

현재 툴은 **제목 컬럼**에 `회사명`, **본문**에 `[단계명] 요약`을 넣습니다.

| 컬럼 이름 (속성) | 타입     | 용도 |
|------------------|----------|------|
| **Name**         | Title    | 회사명 (Crew가 자동 입력). **이름이 반드시 "Name"이어야 함** (또는 아래 NOTION_TITLE_PROPERTY 사용) |
| **Tel**          | Text     | 전화번호 (연락처에서 자동 구분해 입력). 속성 이름 정확히 `Tel` |
| **Email**        | Text     | 이메일 (연락처에서 자동 구분해 입력). 속성 이름 정확히 `Email` |
| **Contact**      | Text     | (선택) 연락처 원문. Tel/Email로 구분 전 기존 값 보관용 |
| 나머지           | 원하는 대로 | 상태, 담당자, 예산 등 수동 관리용 |

- **Tel**, **Email** 속성을 추가해 두면 Crew/후처리 스크립트가 `contact`(이메일 또는 전화 혼합 문자열)를 파싱해 전화번호는 **Tel**, 이메일은 **Email**에 각각 넣습니다. 기존 **Contact** 컬럼이 있으면 원문도 그대로 기록됩니다.
- **제목 속성 이름**이 `Name`이 아니면 `.env`에 `NOTION_TITLE_PROPERTY=실제제목속성이름` 추가 (아래 4번 참고).
- **기입되는 값은 한국어로 표시**됩니다: 단계(영업 후보, 제안, …), ICP 적합성(적합/부적합), 웹사이트 상태(웹사이트 없음/구형/활성), 결과 상태(신규 리드, 연락함, …). Select 타입 컬럼은 이 한국어 값이 옵션으로 추가됩니다.

### 2-3. DB를 통합과 연결 (중요)

Notion API가 이 DB에 쓸 수 있게 하려면 **DB를 방금 만든 통합과 공유**해야 합니다.

1. 만든 **데이터베이스 페이지** 열기
2. 오른쪽 상단 **"..."** 메뉴 → **Connections** 또는 **연결** 클릭
3. **만든 통합 이름**(예: Sales Factory) 선택해서 연결

연결하지 않으면 API가 404/권한 오류를 냅니다.

---

## 3. Database ID 확인 → 어떤 페이지(DB)에 들어가는지

Crew가 로그를 넣는 곳은 **방금 연결한 그 데이터베이스**입니다.  
즉, “어떤 페이지에 들어가냐” = **그 DB가 있는 페이지**이고, **각 행(레코드)**가 한 건의 로그입니다.

### Database ID 찾는 방법

1. Notion에서 **해당 데이터베이스**를 열기 (전체 페이지로 열린 상태)
2. 주소창 URL 확인  
   - 형태: `https://www.notion.so/workspace명/xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx?v=...`
3. **Database ID**는 `?` 앞의 32자리 영숫자입니다.  
   - 예: `https://www.notion.so/myworkspace/a1b2c3d4e5f6...32자리?v=...`  
   → `a1b2c3d4e5f6...32자리` 부분만 복사
4. 복사한 ID에서 **하이픈(-)** 있으면 그대로 두고, 없으면 그대로 사용  
   - Notion API는 보통 하이픈 없이 32자리로 씁니다. 둘 다 되는 경우가 많으니, 안 되면 하이픈 제거해서 시도.

이 **Database ID**가 **NOTION_DATABASE_ID**입니다.

---

## 4. .env에 넣기

프로젝트 루트의 `.env` 파일에 아래 세 줄을 추가합니다.

```env
NOTION_API_KEY=secret_여기에_위에서_복사한_통합_시크릿
NOTION_DATABASE_ID=여기에_32자리_데이터베이스_ID
```

제목 속성을 **Name**이 아닌 이름으로 썼다면:

```env
NOTION_TITLE_PROPERTY=실제제목속성이름
```

제안서 PDF 링크를 넣을 속성 이름이 **Proposal PDF**가 아니면 (예: **제안서 PDF**):

```env
NOTION_PDF_PROPERTY=제안서 PDF
```

예시 (제목 속성이 "회사명"인 경우):

```env
NOTION_API_KEY=secret_xxxxxxxxxxxx
NOTION_DATABASE_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
NOTION_TITLE_PROPERTY=회사명
```

저장 후 Crew 다시 실행하면, 해당 DB에 페이지가 생성됩니다.

---

## 5. Notion 페이지(DB) 꾸미기

- **어떤 페이지에 들어가냐**  
  → 위에서 만든 **그 DB가 있는 Notion 페이지**입니다.  
  → DB를 “인라인”으로 넣었다면: 그 블록이 있는 페이지.  
  → “Full page”로 만들었다면: 그 DB 자체가 하나의 페이지.

- **어떻게 꾸미면 좋은지**
  - **뷰 추가**: Table 뷰(리스트), Board(상태별), Calendar(날짜별) 등 추가해서 사용
  - **컬럼 추가**: 상태(Select), 담당자(People), 예산(Number), 다음 연락일(Date) 등으로 CRM처럼 활용
  - **필터/정렬**: “상태 = 진행중” 등으로 필터링
  - **제목 클릭** → 페이지 안에 Crew가 적어 둔 `[단계명] 요약` 본문이 보입니다. 여기는 API가 자동으로 채우는 부분이라, 추가 설명은 그 페이지 본문에 수동으로 적으면 됩니다.

---

## 6. 제안서 PDF를 각 Notion 페이지에 넣기

Crew 실행 후 `generate_pdf_playwright.py`로 PDF를 만들면 **output/** 에 회사별 PDF가 생깁니다.  
이 PDF를 Notion 해당 회사 페이지에 넣는 방법은 **두 가지**입니다.

### 방식 A — 파일 업로드 (권장)

PDF 파일을 **Notion에 직접 업로드**해 페이지에 첨부합니다. 공유 URL 없이 사용할 수 있습니다.

1. **Notion DB에 속성 추가**  
   - 속성 이름: **Proposal PDF** 또는 **제안서 PDF** (다른 이름이면 `.env`에 `NOTION_PDF_PROPERTY=제안서 PDF`)  
   - **유형: Files & media** (URL이 아님).

2. **.env 설정**  
   ```env
   NOTION_PDF_UPLOAD=true
   ```

3. **동기화 실행**  
   ```powershell
   python sync_pdf_to_notion.py
   ```  
   - `output/` 의 Playwright PDF를 회사명으로 매칭해 해당 Notion 페이지에 **파일로 업로드** 후 첨부합니다.  
   - 파일당 20MB 이하여야 합니다 (Notion 제한).

### 방식 B — URL 링크

PDF를 외부에 공유해 두고, Notion에는 **링크만** 넣습니다.

1. **Notion DB에 속성 추가**  
   - 속성 이름: **Proposal PDF** (또는 `NOTION_PDF_PROPERTY`)  
   - **유형: URL**.

2. **output/ 폴더를 공개 URL로 공유**  
   - OneDrive·Google Drive·SharePoint 등에 `output/` 을 올리고 **폴더 공유 링크**를 만든 뒤,  
   - 그 **기준 URL**을 `.env`에 넣습니다.  
   ```env
   NOTION_PDF_BASE_URL=https://company.sharepoint.com/.../output
   ```

3. **동기화 실행**  
   ```powershell
   python sync_pdf_to_notion.py
   ```  
   - 각 페이지의 Proposal PDF 속성에 `NOTION_PDF_BASE_URL + 파일명` 링크를 넣습니다.

---

- **방식 A**를 쓰면 `NOTION_PDF_UPLOAD=true` 만 있으면 되고, **방식 B**를 쓰면 `NOTION_PDF_BASE_URL` 이 필요합니다.  
- 이메일 발송 후 노션 반영: `send_emails.py --send --sync-notion` 사용 시, 위 둘 중 하나만 설정되어 있으면 동기화가 실행됩니다.

---

---

## 7. Notion에 기록하는 방법 (요약)

- **키**: `.env`에 `NOTION_API_KEY`, `NOTION_DATABASE_ID`(와 필요 시 `NOTION_TITLE_PROPERTY` 등)만 넣으면 됩니다. Crew 실행 시 진입점에서 `.env`를 로드하므로, **그냥 .env에 키 넣고 실행하면 Notion에 기록**됩니다.
- **이미 요약만 있고 기록이 안 됐을 때**: 에이전트가 도구를 호출하지 않고 코드만 출력한 경우, 아래 보정 스크립트로 `notion_log_summary.md`를 파싱해 Notion API를 직접 호출하면 됩니다.  
  ```powershell
  python run_notion_log_from_summary.py
  ```  
  (이 스크립트도 `.env`의 키를 참조합니다. 파일 경로 지정: `python run_notion_log_from_summary.py 경로/notion_log_summary.md`)

## 8. Notion에 기록이 안 될 때 (상세)

- **증상**: Crew는 끝났는데 Notion DB에 행이 하나도 안 생김.
- **원인**: 에이전트가 Notion 도구를 **실제로 호출하지 않고**, 호출하는 코드만 텍스트로 출력한 경우 (예: `notion_log_summary.md`에 `"tool_code"`만 있고 실제 API 호출이 없음).
- **해결 1 — 보정 스크립트**: 위 7번처럼 `run_notion_log_from_summary.py` 실행 (`.env` 키 사용).
- **해결 2 — 다음 실행부터**: `notion_logging_task` 지시에 “도구를 반드시 실제로 호출할 것”이 있으므로 Crew를 다시 실행하면 개선될 수 있음.
- **Notion MCP**: Cursor에서 Notion MCP를 쓰려면 해당 MCP 서버 인증(`mcp_auth`) 후 사용 가능합니다. 지금 파이프라인은 **.env 키 + Notion API**로 동작합니다.

정리하면:  
**Notion API 넣는 방법** = 1~4번, **어떤 페이지에 들어가는지/어떻게 꾸밀지** = 2번에서 만든 DB 페이지 + 5번에서 뷰/컬럼으로 꾸미면 됩니다.
