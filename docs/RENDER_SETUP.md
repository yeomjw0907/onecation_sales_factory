# Render Setup

이 프로젝트는 Render의 Docker Web Service로 올리는 것을 기준으로 맞춰져 있다.

## 왜 Docker로 올리나

- `playwright` 브라우저 런타임이 필요하다.
- `LibreOffice`가 필요하다.
- 한국어/일본어 PDF를 위해 `fonts-noto-cjk`가 필요하다.

위 세 가지 때문에 Render native Python runtime보다 Docker가 안전하다.

공식 참고:

- [Docker on Render](https://render.com/docs/docker)
- [Blueprint Spec](https://render.com/docs/blueprint-spec)

## 사전 준비

1. Supabase에서 `supabase/runtime_schema.sql` 실행
2. Supabase Storage 버킷 `sales-factory-assets` 생성
3. GitHub에 최신 코드 push

## 이번 저장소에 이미 들어간 것

- [Dockerfile](C:/Users/yeomj/OneDrive/Desktop/onecation_sales_factory/Dockerfile)
- [render.yaml](C:/Users/yeomj/OneDrive/Desktop/onecation_sales_factory/render.yaml)

## Render에서 만드는 순서

1. Render 대시보드에서 `New +`
2. `Blueprint` 선택
3. GitHub repo `onecation_sales_factory` 연결
4. `render.yaml` 감지되면 그대로 진행
5. 아래 `sync: false` 환경변수 값을 입력

필수 env:

- `GEMINI_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_SECRET_KEY`
- `ALERT_EMAIL_TO`

기본값으로 이미 들어가는 env:

- `SALES_FACTORY_RUNTIME_BACKEND=supabase`
- `SALES_FACTORY_REQUIRE_PDF=1`
- `LIBREOFFICE_BIN=/usr/bin/soffice`
- `SUPABASE_STORAGE_BUCKET=sales-factory-assets`
- `SALES_FACTORY_AUTO_SEND_MODE=shadow`
- `SALES_FACTORY_AUTO_SEND_MIN_PROPOSAL_SCORE=85`
- `SALES_FACTORY_AUTO_SEND_REQUIRE_PDF=1`
- `SALES_FACTORY_AUTO_SEND_MAX_ITEMS_PER_RUN=1`

## 첫 배포 후 확인

1. Render 서비스 URL 접속
2. Streamlit 운영 콘솔이 뜨는지 확인
3. 설정 탭에서 저장소 백엔드가 `Supabase`인지 확인
4. 실행 1건 돌려서 `docx/pdf` 산출물이 생성되는지 확인
5. 자동발송 모드가 `shadow`로 보이는지 확인

## 메일 쪽은 나중에

처음 배포에서는 SMTP를 넣지 않아도 된다.

- `shadow`: 필요 없음
- `canary/live`: 아래 env 추가 필요

추가 env:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SALES_FACTORY_AUTO_SEND_CANARY_EMAIL`

## 추천 운영 순서

1. Render 배포
2. `shadow`
3. PDF 생성 확인
4. SMTP 추가
5. `canary`
6. 마지막에 `live`
