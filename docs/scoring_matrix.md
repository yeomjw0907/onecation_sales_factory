# Sales Factory Scoring Matrix

`website_audit_task`에서 사용하는 구매확률 점수표입니다.

## 총점 구조 (100점)

- `website_status_score`: 0~30
- `business_fit_score`: 0~30
- `execution_readiness_score`: 0~20
- `contact_reachability_score`: 0~20

`priority_score = website_status_score + business_fit_score + execution_readiness_score + contact_reachability_score`

## 1) Business Fit Score (0~30)

### 업종 적합도 (0/5/10/15)
- 15: 핵심 타깃 업종
- 10: 인접 업종
- 5: 약한 연관
- 0: 비타깃 업종

### 지역/권역 적합도 (0/5/10)
- 10: 영업 가능 지역 정확히 일치
- 5: 인접 권역
- 0: 비영업권

### 니즈 징후 (0/5)
- 5: 사이트/SNS/채용/공지에서 마케팅 니즈 신호 확인
- 0: 신호 없음

## 2) Execution Readiness Score (0~20)

### 규모 추정 (0/4/8)
- 8: 소화 가능한 예산/규모로 판단
- 4: 제한적 가능성
- 0: 예산 가능성 낮음

### 활동성 (0/3/6)
- 6: 최근 3개월 내 온라인 업데이트 활발
- 3: 활동성 보통
- 0: 장기 비활성

### 과거 집행 흔적 (0/3/6)
- 6: 광고/캠페인/프로모션 흔적 명확
- 3: 약한 흔적
- 0: 흔적 없음

## 3) Contact Reachability Score (0~20)

### 직통 채널 가용성 (0/4/8)
- 8: 이메일 + 전화 + 문의폼 중 2개 이상 유효
- 4: 1개만 유효
- 0: 유효 채널 없음

### 의사결정자 식별 (0/3/7)
- 7: 대표/마케팅 담당자 식별
- 3: 부서 단위만 확인
- 0: 식별 불가

### 응답 가능성 (0/2/5)
- 5: 최근 응대/운영 흔적 있음
- 2: 불명확
- 0: 응답 가능성 낮음

## 4) Website Status Score (0~30)

- 30: no_website
- 20~25: outdated_website (근거 필요)
- 5~15: active_website (개선 여지에 따라)

## 신뢰도/불확실성 처리

- 각 하위 점수마다 근거와 `confidence`를 기록 (`high` / `medium` / `low`)
- 정보 부족 시 중립점 부여 금지, `unknown` 명시 후 보수적으로 채점

## 실행 버킷

- 70~100: `hot` (즉시 아웃리치)
- 50~69: `warm` (보완조사 후 진행)
- 0~49: `cold` (보류)
