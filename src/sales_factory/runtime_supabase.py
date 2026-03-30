from __future__ import annotations

import json
import mimetypes
import os
from hashlib import sha1
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from supabase import Client, create_client
except ImportError:  # pragma: no cover - exercised only before dependency install
    Client = Any  # type: ignore[assignment]
    create_client = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = PROJECT_ROOT / ".runtime"
DOWNLOAD_CACHE_DIR = RUNTIME_DIR / "download_cache"

RUNTIME_BACKEND_ENV = "SALES_FACTORY_RUNTIME_BACKEND"
SUPABASE_URL_ENV = "SUPABASE_URL"
SUPABASE_KEY_ENVS = ("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_STORAGE_BUCKET_ENV = "SUPABASE_STORAGE_BUCKET"

JSON_COLUMNS = {
    "inputs_json",
    "metadata_json",
    "asset_bundle_json",
    "reroute_targets_json",
}

_ENV_LOADED = False
_CLIENT: Client | None = None


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_project_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

    _ENV_LOADED = True


def is_render_environment() -> bool:
    load_project_env()
    return bool((os.environ.get("RENDER", "") or "").strip()) or bool(
        (os.environ.get("RENDER_EXTERNAL_URL", "") or "").strip()
    )


def get_runtime_backend() -> str:
    load_project_env()
    explicit_backend = (os.environ.get(RUNTIME_BACKEND_ENV, "") or "").strip().lower()
    if explicit_backend:
        if explicit_backend not in {"sqlite", "supabase"}:
            raise RuntimeError(
                f"{RUNTIME_BACKEND_ENV} must be either 'sqlite' or 'supabase', got '{explicit_backend}'."
            )
        return explicit_backend

    if get_supabase_url() and get_supabase_key():
        return "supabase"
    return "sqlite"


def is_supabase_backend() -> bool:
    return get_runtime_backend() == "supabase"


def get_supabase_url() -> str:
    load_project_env()
    return (os.environ.get(SUPABASE_URL_ENV, "") or "").strip()


def get_supabase_key() -> str:
    load_project_env()
    for env_name in SUPABASE_KEY_ENVS:
        value = (os.environ.get(env_name, "") or "").strip()
        if value:
            return value
    return ""


def get_supabase_key_candidates() -> list[tuple[str, str]]:
    load_project_env()
    candidates: list[tuple[str, str]] = []
    for env_name in SUPABASE_KEY_ENVS:
        value = (os.environ.get(env_name, "") or "").strip()
        if value:
            candidates.append((env_name, value))
    return candidates


def get_storage_bucket() -> str | None:
    load_project_env()
    bucket = (os.environ.get(SUPABASE_STORAGE_BUCKET_ENV, "") or "").strip()
    return bucket or None


def describe_runtime_backend() -> dict[str, Any]:
    backend = get_runtime_backend()
    if backend == "sqlite":
        return {
            "backend": "sqlite",
            "label": "SQLite",
            "remote_url": None,
            "storage_bucket": None,
        }
    return {
        "backend": "supabase",
        "label": "Supabase",
        "remote_url": get_supabase_url(),
        "storage_bucket": get_storage_bucket(),
    }


def get_supabase_client() -> Client:
    global _CLIENT

    if _CLIENT is not None:
        return _CLIENT

    if not is_supabase_backend():
        raise RuntimeError("Supabase client requested while sqlite backend is active.")

    if create_client is None:
        raise RuntimeError(
            "supabase package is not installed. Run `uv add supabase` before enabling the Supabase backend."
        )

    url = get_supabase_url()
    candidates = get_supabase_key_candidates()
    if not url or not candidates:
        raise RuntimeError(
            "Supabase backend requires SUPABASE_URL and SUPABASE_SECRET_KEY "
            "(or SUPABASE_SERVICE_ROLE_KEY)."
        )

    _CLIENT = create_client(url, candidates[0][1])
    return _CLIENT


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    for column in JSON_COLUMNS:
        value = normalized.get(column)
        if value is None or isinstance(value, str):
            continue
        normalized[column] = json.dumps(value, ensure_ascii=False)
    return normalized


def _normalize_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [_normalize_row(row) for row in (rows or [])]


def _apply_filters(query: Any, filters: list[tuple[str, str, Any]] | None) -> Any:
    for column, operator, value in filters or []:
        if operator == "eq":
            query = query.eq(column, value)
        elif operator == "in":
            query = query.in_(column, list(value))
        else:
            raise ValueError(f"Unsupported Supabase filter operator: {operator}")
    return query


def verify_schema() -> None:
    global _CLIENT

    if not is_supabase_backend():
        return
    if create_client is None:
        raise RuntimeError(
            "supabase package is not installed. Run `uv add supabase` before enabling the Supabase backend."
        )

    url = get_supabase_url()
    candidates = get_supabase_key_candidates()
    if not url or not candidates:
        raise RuntimeError(
            "Supabase backend requires SUPABASE_URL and SUPABASE_SECRET_KEY "
            "(or SUPABASE_SERVICE_ROLE_KEY)."
        )

    required_tables = ["runs", "task_events", "assets", "approval_items", "notifications"]
    failures: list[str] = []

    for env_name, key in candidates:
        client = create_client(url, key)
        try:
            for table in required_tables:
                client.table(table).select("id").limit(1).execute()
            _CLIENT = client
            return
        except Exception as exc:  # pragma: no cover - depends on remote project state
            failures.append(f"{env_name}: {type(exc).__name__}: {exc}")

    failure_summary = " | ".join(failures[:2])
    raise RuntimeError(
        "Supabase runtime schema is missing or unreachable. "
        "Apply `supabase/runtime_schema.sql` and verify the credentials. "
        f"Tried keys: {', '.join(env_name for env_name, _ in candidates)}. "
        f"Last errors: {failure_summary}"
    )


def select_rows(
    table: str,
    *,
    filters: list[tuple[str, str, Any]] | None = None,
    order_by: tuple[str, bool] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    query = get_supabase_client().table(table).select("*")
    query = _apply_filters(query, filters)
    if order_by:
        column, descending = order_by
        query = query.order(column, desc=descending)
    if limit is not None:
        query = query.limit(limit)
    response = query.execute()
    return _normalize_rows(getattr(response, "data", None) or [])


def select_row(
    table: str,
    *,
    filters: list[tuple[str, str, Any]] | None = None,
    order_by: tuple[str, bool] | None = None,
) -> dict[str, Any] | None:
    rows = select_rows(table, filters=filters, order_by=order_by, limit=1)
    return rows[0] if rows else None


def insert_rows(table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    get_supabase_client().table(table).insert(rows, returning="minimal").execute()


def upsert_rows(table: str, rows: list[dict[str, Any]], *, on_conflict: str) -> None:
    if not rows:
        return
    get_supabase_client().table(table).upsert(
        rows,
        on_conflict=on_conflict,
        returning="minimal",
    ).execute()


def update_rows(table: str, values: dict[str, Any], *, filters: list[tuple[str, str, Any]]) -> None:
    if not values:
        return
    query = get_supabase_client().table(table).update(values, returning="minimal")
    query = _apply_filters(query, filters)
    query.execute()


def upload_asset_file(
    local_path: Path,
    *,
    storage_path: str,
    content_type: str | None = None,
) -> dict[str, Any]:
    bucket = get_storage_bucket()
    if not is_supabase_backend() or not bucket or not local_path.exists():
        return {}

    guessed_content_type = content_type or mimetypes.guess_type(local_path.name)[0]
    file_options = {"upsert": "true"}
    if guessed_content_type:
        file_options["content-type"] = guessed_content_type

    try:
        with local_path.open("rb") as file_obj:
            get_supabase_client().storage.from_(bucket).upload(
                path=storage_path,
                file=file_obj,
                file_options=file_options,
            )
    except Exception as exc:  # pragma: no cover - depends on remote storage
        return {
            "storage_error": str(exc),
            "storage_bucket": bucket,
            "storage_path": storage_path,
        }

    return {
        "storage_bucket": bucket,
        "storage_path": storage_path,
        "storage_synced_at": now_iso(),
        "content_type": guessed_content_type,
    }


def download_asset_bytes(bucket: str | None, storage_path: str | None) -> bytes | None:
    if not is_supabase_backend() or not bucket or not storage_path:
        return None
    try:
        return get_supabase_client().storage.from_(bucket).download(storage_path)
    except Exception:  # pragma: no cover - depends on remote storage
        return None


def cached_asset_path(path: Path) -> Path:
    digest = sha1(str(path).encode("utf-8")).hexdigest()[:12]
    return DOWNLOAD_CACHE_DIR / f"{digest}_{path.name}"


def materialize_local_asset(path: Path, metadata: dict[str, Any] | None = None) -> Path | None:
    if path.exists():
        return path

    metadata = metadata or {}
    DOWNLOAD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached_path = cached_asset_path(path)

    inline_content = metadata.get("inline_content")
    if isinstance(inline_content, str):
        cached_path.write_text(inline_content, encoding="utf-8")
        return cached_path

    asset_bytes = download_asset_bytes(metadata.get("storage_bucket"), metadata.get("storage_path"))
    if not asset_bytes:
        return None

    cached_path.write_bytes(asset_bytes)
    return cached_path


def read_asset_bytes(path: Path, metadata: dict[str, Any] | None = None) -> bytes | None:
    local_path = materialize_local_asset(path, metadata)
    if not local_path or not local_path.exists():
        return None
    return local_path.read_bytes()


def read_asset_text(path: Path, metadata: dict[str, Any] | None = None) -> str:
    local_path = materialize_local_asset(path, metadata)
    if not local_path or not local_path.exists():
        return "(file missing)"
    return local_path.read_text(encoding="utf-8", errors="replace")
