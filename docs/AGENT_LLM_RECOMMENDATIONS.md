# 에이전트별 전용 LLM 추천

Crew에서 에이전트마다 **역할에 맞는 모델**을 붙이면 품질·비용 균형을 잡기 좋습니다.  
**Gemini만 쓰지 않아도 됨** — 에이전트마다 **Claude**, **GPT**, **Gemini** 중 아무거나 골라서 `llm`에 넣으면 됩니다.

---

## 1. 추천 매트릭스 (Gemini 기준)

| 에이전트 | 추천 모델 | 이유 |
|----------|-----------|------|
| **lead_finder** | Flash (기본) | 검색·구조화·테이블 채우기. 속도와 비용이 중요. |
| **website_auditor** | Flash (기본) | 루브릭 적용·점수 산출. Flash로 충분. |
| **competitor_analyst** | **Pro** | 경쟁사 리서치·표 일관성·제안서에 그대로 붙일 출력. 추론 부담 큼. |
| **landing_page_builder** | Flash (기본) | 카피·CTA. 창의성보다 속도·일관성. |
| **marketing_strategist** | Flash (기본) | 채널 1~2개 추천·근거·KPI. 구조화된 출력. |
| **proposal_writer** | **Pro** | 12섹션·긴 문맥·숫자 정합성·표 다수. 복잡도·품질 우선. |
| **email_writer** | Flash (기본) | 짧은 문구·제목·CTA. 반복 많아 Flash가 적합. |
| **notion_logger** | **Flash-Lite** | 단순 구조 출력·API 호출 필드 채우기. 비용·속도 최우선. |

---

## 2. 모델별 용도 요약

- **Gemini 2.5 Flash**  
  기본용. 리드·감사·랜딩·마케팅·이메일 등 대부분 태스크. 빠르고 저렴.
- **Gemini 2.5 Pro**  
  경쟁 분석, 제안서처럼 **추론·긴 문맥·구조 정확도**가 중요한 에이전트만.
- **Gemini 2.5 Flash-Lite**  
  Notion 로거처럼 **짧고 단순한 구조 출력**만 하는 에이전트. 가장 저렴.

---

## 3. 설정 방법

- **기본 모델**: `.env`의 `MODEL` (예: `gemini/gemini-2.5-flash`).  
  `llm`을 지정하지 않은 에이전트는 전부 이 값을 씁니다.
- **에이전트별 오버라이드**: `config/agents.yaml`에서 해당 에이전트에 `llm: provider/모델ID` 추가.  
  Gemini뿐 아니라 **Claude**(anthropic/...), **GPT**(openai/...) 도 같은 방식으로 넣으면 됨.  
  예: `proposal_writer`에 `llm: gemini/gemini-2.5-pro`, `email_writer`에 `llm: anthropic/claude-3-5-sonnet-20241022`.

지금 프로젝트에는 아래만 **오버라이드**해 두었습니다.

- `competitor_analyst` → **Pro**
- `proposal_writer` → **Pro**
- `notion_logger` → **Flash-Lite** (미지원 시 동일 env의 Flash로 바꾸면 됨)

나머지는 전부 **기본(Flash)** 사용.

---

## 4. provider/model 형식 — Gemini, Claude, GPT 모두 가능

`config/agents.yaml`에서 에이전트마다 `llm: provider/모델ID`만 넣으면 됩니다.  
**한 Crew 안에서 Gemini·Claude·GPT를 섞어 써도 됩니다.**  
해당 provider API 키만 `.env`에 있으면 됩니다 (예: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`).

### 모델 ID 예시

| Provider | 예시 (CrewAI 형식) | 용도 참고 |
|----------|---------------------|-----------|
| **Gemini** | `gemini/gemini-2.5-flash`, `gemini/gemini-2.5-pro`, `gemini/gemini-2.5-flash-lite` | 기본·추론·저비용 |
| **Claude** | `anthropic/claude-sonnet-4-20250514`, `anthropic/claude-3-5-sonnet-20241022` | 카피·창의성·긴 문맥 |
| **GPT** | `openai/gpt-4o`, `openai/gpt-4o-mini` | 구조화·추론·속도 |

예: 제안서는 Pro, 이메일은 Claude, 로거는 mini 같은 식으로 **에이전트마다 다르게** 지정하면 됩니다.

---

## 5. 참고

- 기본 모델은 `.env`의 `MODEL`. 에이전트에 `llm`이 없으면 이 값을 씁니다.
- Flash-Lite 등 특정 모델이 없거나 오류 나면 해당 에이전트에서 `llm`만 지우면 기본 모델로 동작합니다.
