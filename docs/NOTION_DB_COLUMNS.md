# Notion DB 탭(열) 체크리스트 — 고도화 버전

## 1. 현재 툴이 Notion에 쓰는 것

`NotionLogTool`은 **지금** 다음만 보냅니다.

| 넣는 곳 | 내용 |
|--------|------|
| **Name** (제목 속성) | 회사명 |
| **페이지 본문** | `[단계명] 요약` 한 줄 |

그래서 **Name** 열만 있어도 툴은 동작합니다.

---

## 2. 태스크에서 기대하는 필드 (고도화)

`notion_logging_task`에서 요구하는 experiment/measurement 필드:

- `first_contact_date`
- `channels_used`
- `open_rate`
- `reply_rate`
- `meeting_booked`
- `expected_deal_size`
- `outcome_status`
- `loss_reason_tag`
- 요약 (`compact_checkpoint_summary`)

이 필드들은 **에이전트 최종 JSON 출력**에는 들어가지만, **현재 툴은 Notion 컬럼에 넣지 않습니다.**  
(툴은 `company_name`, `stage`, `summary` 3개만 받음)

---

## 3. Notion DB에 두면 좋은 탭(열) 정리

### 필수 (지금도 사용 중)

| 속성명 | 유형 | 비고 |
|--------|------|------|
| **Name** | Title | 툴이 자동 입력. 이름 변경 시 `.env`에 `NOTION_TITLE_PROPERTY` 설정 |

### 제안서 PDF (둘 중 하나)

| 속성명 | 유형 | 비고 |
|--------|------|------|
| **Proposal PDF** (또는 **제안서 PDF**) | **Files & media** | 권장. `NOTION_PDF_UPLOAD=true` 설정 시 `sync_pdf_to_notion.py`가 PDF를 **직접 업로드**해 첨부 (20MB 이하). 속성명 변경 시 `.env`에 `NOTION_PDF_PROPERTY=제안서 PDF` |
| **Proposal PDF** (또는 **제안서 PDF**) | **URL** | `NOTION_PDF_BASE_URL` 설정 시 `sync_pdf_to_notion.py`가 링크만 반영. 툴의 `proposal_pdf_url`로도 넣을 수 있음 |

### 기존 권장 (수동/CRM용)

| 속성명 | 유형 | 비고 |
|--------|------|------|
| 상태 | Select | 리드 발굴 / 웹사이트 검토 / … / 완료 등 |
| 담당자 | Person | |
| 산업 | Text | |
| 연락처 | Text 또는 Phone | |
| 홈페이지 | URL | |
| 비고 | Text | |

### 고도화용 — 추가하면 좋은 열

태스크 출력과 맞추려면 아래 열을 **추가**해 두는 걸 권장합니다.  
(지금은 수동 입력용으로 쓰고, 나중에 툴을 확장하면 자동 채우기 가능)

| 속성명 (영문 권장) | 유형 | 용도 |
|--------------------|------|------|
| first_contact_date | Date | 첫 연락일 |
| channels_used | Text 또는 Multi-select | 사용 채널 (이메일, 전화 등) |
| open_rate | Text 또는 Number | 오픈률 |
| reply_rate | Text 또는 Number | 회신률 |
| meeting_booked | Checkbox 또는 Select | 미팅 예약 여부 |
| expected_deal_size | Text 또는 Number | 예상 거래 규모 |
| outcome_status | Select | 진행중/성공/실패 등 |
| loss_reason_tag | Text 또는 Select | 실패 시 사유 |
| compact_summary | Text | 단계별 요약 (길면 본문만 써도 됨) |

---

## 4. 결론

- **지금 구조만으로**:  
  **Name** + (선택) 상태/담당자/산업/연락처/홈페이지/비고 있으면 **탭은 “맞는” 상태**이고, 툴도 그대로 동작합니다.
- **고도화 반영**:  
  위 **고도화용** 열을 Notion DB에 추가해 두면,  
  - 당장은 수동 입력·필터링용으로 쓰기 좋고,  
  - 나중에 `NotionLogTool`이 이 속성들도 채우도록 확장하면, 태스크 출력과 Notion 탭이 완전히 맞게 됩니다.

이미 **원케이션 영업팀 db**에 열을 더해 두었다면, Name/상태/담당자/산업/연락처/홈페이지/비고 + (선택) 고도화용 열만 있으면 됩니다.
