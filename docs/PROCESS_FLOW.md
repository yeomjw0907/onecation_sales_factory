# Sales Factory Crew 프로세스 (성과형 개정안)

이 문서는 기존 7단계 파이프라인을 유지하면서, 실제 전환 성과를 높이기 위한 최소 개선안을 반영한 운영 기준입니다.

## 실행 입력값 (기본)

| 변수 | 기본값 | 의미 |
|------|--------|------|
| `lead_mode` | `region_or_industry` | `region_or_industry`=지역/산업 키워드 검색, `company_name`=회사명 1개 |
| `lead_query` | `seoul printing factory` | 검색 키워드 또는 정확한 회사명 |
| `max_companies` | `10` | 최대 리드 수 |
| `current_year` | 현재 연도 | 연도 문맥 |

## 1단계: 리드 조사 (lead_research_task)

- 에이전트: Lead Finder
- 입력: 실행 입력값만 사용
- 하는 일:
  - 최대 10개 회사 수집
  - 기본 정보: 회사명/업종/지역/연락처/홈페이지/출처
  - ICP 필터 정보 추가: 회사 규모 추정, 매출 추정, 세부업종, 의사결정자 식별 여부, ICP 적합 여부
  - 비타깃 리드는 대체 후보가 있으면 제외
- 결과:
  - 리드 테이블 (최대 10개)

## 2단계: 웹사이트 검토 + 구매확률 점수 (website_audit_task)

- 에이전트: Website Auditor
- 참고: 1단계 결과
- 하는 일:
  - 웹 상태 분류: `no_website` / `outdated_website` / `active_website`
  - 우선순위 점수는 웹상태 단독이 아니라 구매확률 기준으로 계산
  - 점수식:
    - `priority_score = website_status_score(0-30) + business_fit_score(0-30) + execution_readiness_score(0-20) + contact_reachability_score(0-20)`
  - 각 하위 점수별 근거와 신뢰도(`high/medium/low`) 기록
  - 실행 버킷 권장:
    - 70점 이상: 즉시 아웃리치
    - 50~69점: 보완조사 후 진행
    - 49점 이하: 보류
- 결과:
  - 감사/우선순위 테이블

## 3단계: 랜딩 페이지 초안 (landing_page_task)

- 에이전트: Landing Page Builder
- 참고: 2단계 결과
- 하는 일:
  - 우선순위 회사별 1페이지 랜딩 초안 작성
  - 필수 항목: 헤드라인, 가치제안, 서비스, 신뢰요소, CTA
  - 회사별 1개 핵심 전환목표(전화/견적문의/폼) 고정
- 결과:
  - `landing_pages.md`

## 4단계: 마케팅 추천 (marketing_recommendation_task)

- 에이전트: Marketing Strategist
- 참고: 2단계 결과
- 하는 일:
  - 회사당 1~2개 채널만 추천(과다 추천 금지)
  - 채널별 필수 항목:
    - 근거 1개
    - 목표 KPI 1개
    - 4주 테스트 예산
    - 월 운영 예산 범위
- 결과:
  - `marketing_plan.md`

## 5단계: 제안서 작성 (proposal_task)

- 에이전트: Proposal Writer
- 참고: 2+3+4단계 결과
- 하는 일:
  - 회사별 제안서 작성
  - 필수 섹션: 현재상태, 기회, 랜딩요약, 마케팅플랜, 오퍼, 다음단계
  - 성과 섹션 추가: `kpi_forecast` (답장률/미팅전환률/리드량 또는 ROAS proxy)
  - 4주 검증 계획 포함
- 결과:
  - `proposal.md`

## 6단계: 멀티채널 아웃리치 초안 (email_outreach_task)

- 에이전트: Email Writer
- 참고: 5단계 결과
- 하는 일:
  - 회사별 4터치 시퀀스 생성
    - D1 이메일
    - D3 전화 또는 문자
    - D6 리마인드 이메일
    - D10 마지막 체크인
  - 개인화 포인트 2개 이상 강제
- 결과:
  - `outreach_emails.md`
  - 발송은 하지 않음(초안만 생성)

## 7단계: Notion 로깅 (notion_logging_task)

- 에이전트: Notion Logger (+ NotionLogTool)
- 참고: 1~6단계 결과
- 하는 일:
  - 회사당 Notion 페이지 1개 생성
  - 실험/성과 필드 포함:
    - first_contact_date
    - channels_used
    - open_rate
    - reply_rate
    - meeting_booked
    - expected_deal_size
    - outcome_status
    - loss_reason_tag
  - Notion 연결이 없으면 fallback 로그 반환
- 결과:
  - Notion DB 행 추가
  - `notion_log_summary.md`

## 운영 루프 (필수)

- 배치 단위: 10개 리드 기준 2주 실행
- 합격 KPI 기준:
  - 답장률 8%+
  - 미팅 전환률 3%+
- 기준 미달 시:
  - 리드 소스 / 카피 / 오퍼 중 1개만 바꿔 A/B 테스트

## 한 줄 요약

서칭은 1단계에서 최대 10개를 만들고, 2~7단계는 같은 회사를 기준으로 점수화, 제작, 제안, 시퀀스, 로깅, 회고까지 닫힌 루프로 운영합니다.
