# Crew 능력치 업그레이드 로드맵

Sales Factory Crew의 에이전트·태스크·도구를 단계적으로 개선하기 위한 정리입니다.

---

## 1. 현재 적용된 업그레이드 (완료)

### 에이전트 역할·목표·백스토리 강화

| 에이전트 | 변경 요약 |
|----------|------------|
| **lead_finder** | Senior B2B Local Lead Researcher. 연락 가능·ICP 적합 리드 우선, contact/homepage 누락 금지, icp_fit 근거 명시. |
| **website_auditor** | Website & Purchase-Likelihood Auditor. docs/scoring_matrix.md 루브릭 준수, evidence·confidence·action_bucket 명시. |
| **competitor_analyst** | 출력을 제안서에 그대로 쓸 수 있게 KRW·한국어 일관, 출처·신뢰도 명시. |
| **landing_page_builder** | Conversion-Focused. 1 CTA, 모바일 퍼스트, 채널 전략과 연동된 카피. |
| **marketing_strategist** | 1–2채널만 추천, 채널별 evidence·KPI·예산 명시, 일반론 배제. |
| **proposal_writer** | 숫자 조작 금지(추정 불가 시 명시), 12섹션 구조 준수, 프리미엄 컨설팅 톤. |
| **email_writer** | 이미 시니어 콜드이메일 전문가 기준으로 설정됨 (docs/EMAIL_COPY_GUIDE.md 참고). |
| **notion_logger** | 제안서 PDF는 sync_pdf_to_notion 후처리 가능하다는 백스토리 안내 추가. |

### 태스크 보강

- **website_audit_task**: docs/scoring_matrix.md 적용 명시, information 부족 시 "unknown"·보수적 채점, action_bucket 규칙 명시. 홈페이지 URL 있으면 scrape 도구로 본문 확인하도록 안내.
- **lead_research_task**: expected_output에 contact/homepage 누락 금지, decision_maker_found·icp_notes 필수 및 icp_fit=no 시 사유 1줄 명시.
- **proposal_task**: 추정 불가 시 셀에 "—" 또는 "추정 불가" 기입 규칙 추가.
- **competitor_analysis_task**: URL 있으면 scrape 도구로 경쟁사 사이트 내용 확인하도록 안내.

### 도구 추가 (중기 반영)

- **website_auditor**, **competitor_analyst**: CrewAI `ScrapeWebsiteTool` 연결 (crewai_tools). URL이 있을 때 실제 페이지 내용을 가져와 no_website/outdated 판단 및 경쟁사 강약점 분석에 활용.

---

## 2. 단기 개선 (완료)

- ~~lead_research_task expected_output 보강~~ ✅
- ~~proposal_task 추정 불가 표기~~ ✅
- ~~notion_logger PDF 후처리 안내~~ ✅

---

## 3. 중기 개선 (일부 적용)

### 3.1 리드/감사/경쟁 조사 도구

| 에이전트 | 도구 | 상태 |
|----------|------|------|
| **lead_finder** | (Gemini만으로 추론 가능; 실시간 검색 원하면 Gemini Google Search grounding) | — |
| **website_auditor** | ScrapeWebsiteTool | ✅ 적용 (API 키 없음) |
| **competitor_analyst** | ScrapeWebsiteTool | ✅ 적용 (API 키 없음) |

**리드 검색**: Serper 같은 **별도 검색 API는 필요 없음**. Gemini에 **Google Search grounding**을 켜면 같은 **GEMINI_API_KEY**로 실시간 웹 검색이 가능함 (Gemini API 유료 옵션, 건당 과금). CrewAI에서 Gemini 호출 시 grounding 옵션을 넘기면 됨. 별도 SERPER_API_KEY는 선택 사항.

### 3.2 컨텍스트 주입

- **website_audit_task** 실행 전에 `scoring_matrix.md` 내용을 task description 또는 별도 context로 주입하면 루브릭 적용 일관성이 올라감.
- **proposal_task**: 경쟁 분석·마케팅 계획 출력 중 핵심 표를 요약해 context로 넘기면 섹션 간 정합성 개선 가능(이미 context로 이전 태스크 전체가 전달되므로 우선순위 낮음).

---

## 4. 장기 개선 (품질·자동화)

- **출력 검증**: proposal_task·email_outreach_task 결과에 대해 "검증 에이전트" 또는 간단한 룰 기반 검사(필수 섹션 존재, 제목 길이, CTA 개수 등)로 품질 게이트 추가.
- **피드백 루프**: Notion 로그의 outcome(성공/실패/미팅)을 나중에 수집해, 리드 품질·제안 초안·이메일 문구 개선에 반영하는 프롬프트 보강 (수동 정리 후 프롬프트에 반영하는 수준으로 시작 가능).
- **멀티 에이전트 검토**: proposal는 proposal_writer가 작성 후 marketing_strategist가 "채널 정합성" 한 줄 리뷰 등으로 검토하는 2단 구조(선택).

---

## 5. 점검 체크리스트 (Crew 실행 후)

- [ ] lead_research_task: 연락처·홈페이지가 비어 있는 행이 의도적 예외 없이 없는지
- [ ] website_audit_task: priority_score가 4개 하위 점수 합과 일치하는지, action_bucket이 점수 구간과 맞는지
- [ ] competitor_analysis_task: 표가 proposal에 그대로 붙여 넣기 가능한 형식인지
- [ ] proposal_task: 12섹션 존재, 표·숫자 출처/추정 불가 표기
- [ ] email_outreach_task: 제목 6–10단어, 본문 3–5문장, CTA 1개 (docs/EMAIL_COPY_GUIDE.md)

이 로드맵은 agents.yaml, tasks.yaml, docs/scoring_matrix.md, docs/EMAIL_COPY_GUIDE.md와 함께 유지됩니다.
