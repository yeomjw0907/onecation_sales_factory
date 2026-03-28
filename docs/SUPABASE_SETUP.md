# Supabase Setup

이 프로젝트는 이제 런타임 저장소를 `SQLite` 또는 `Supabase`로 전환할 수 있습니다.

## 1. Supabase 프로젝트 준비

1. Supabase 프로젝트를 생성합니다.
2. SQL Editor에서 `supabase/runtime_schema.sql` 내용을 실행합니다.
3. 필요하면 Storage 버킷을 만듭니다.
   - 권장 이름: `sales-factory-assets`
   - private 버킷으로 두고, 서버에서만 secret/service-role 키로 접근합니다.

## 2. `.env` 추가

아래 값을 `.env`에 넣습니다.

```env
SALES_FACTORY_RUNTIME_BACKEND=supabase
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_SECRET_KEY=YOUR_SECRET_KEY
SUPABASE_STORAGE_BUCKET=sales-factory-assets
```

메모:

- `SUPABASE_SECRET_KEY` 대신 `SUPABASE_SERVICE_ROLE_KEY`도 지원합니다.
- `SUPABASE_STORAGE_BUCKET`은 선택값입니다. 비워두면 DB만 Supabase를 사용하고 파일은 로컬 디스크에 남깁니다.
- Render에서는 같은 값을 Environment Variables에 넣으면 됩니다.

## 3. 의존성 반영

`supabase` 패키지가 `pyproject.toml`에 추가되었습니다.

```bash
uv sync
```

Windows에서 `uv sync` 중 `.venv` 파일 access denied가 나면:

1. 현재 실행 중인 Streamlit/파이썬 프로세스를 종료합니다.
2. 다시 `uv sync`를 실행합니다.

## 4. 기존 SQLite 데이터 마이그레이션

기존 `.runtime/operations.db`를 Supabase로 올리려면:

```bash
python migrate_runtime_to_supabase.py
```

옵션:

```bash
python migrate_runtime_to_supabase.py --sqlite-path C:\path\to\operations.db
```

이 스크립트는:

- `runs`
- `task_events`
- `assets`
- `approval_items`
- `notifications`

를 Supabase로 업서트합니다.

추가 동작:

- Markdown 산출물은 `inline_content`를 메타데이터에 넣어 로컬 파일이 없어도 미리보기가 가능하게 합니다.
- `SUPABASE_STORAGE_BUCKET`이 설정되어 있으면 산출물 파일도 Storage로 업로드합니다.

## 5. 확인 포인트

앱을 다시 띄운 뒤 `설정` 탭에서 아래를 확인합니다.

- 현재 저장소 백엔드
- Supabase URL
- Supabase Storage 버킷

백엔드가 `Supabase`로 보이면 전환이 된 것입니다.
