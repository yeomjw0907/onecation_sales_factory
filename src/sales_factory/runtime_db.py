from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sales_factory.runtime_supabase import (
    describe_runtime_backend as describe_supabase_backend,
    is_supabase_backend,
    load_project_env,
    select_row as supabase_select_row,
    select_rows as supabase_select_rows,
    upsert_rows as supabase_upsert_rows,
    update_rows as supabase_update_rows,
    insert_rows as supabase_insert_rows,
    verify_schema as verify_supabase_schema,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = PROJECT_ROOT / ".runtime"
DB_PATH = RUNTIME_DIR / "operations.db"
ASSET_ROOT = RUNTIME_DIR / "assets"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ensure_runtime_dirs() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_ROOT.mkdir(parents=True, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    ensure_runtime_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def describe_runtime_backend() -> dict[str, Any]:
    if is_supabase_backend():
        return describe_supabase_backend()
    return {
        "backend": "sqlite",
        "label": "SQLite",
        "database_path": str(DB_PATH),
        "remote_url": None,
        "storage_bucket": None,
    }


def init_db() -> None:
    load_project_env()
    ensure_runtime_dirs()
    if is_supabase_backend():
        verify_supabase_schema()
        return

    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                crew_name TEXT NOT NULL,
                trigger_source TEXT NOT NULL,
                status TEXT NOT NULL,
                lead_mode TEXT,
                lead_query TEXT,
                target_country TEXT,
                proposal_language TEXT,
                currency TEXT,
                max_companies INTEGER,
                test_mode INTEGER NOT NULL DEFAULT 1,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                last_heartbeat_at TEXT NOT NULL,
                current_task TEXT,
                current_agent TEXT,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                cached_prompt_tokens INTEGER NOT NULL DEFAULT 0,
                successful_requests INTEGER NOT NULL DEFAULT 0,
                estimated_cost_usd REAL NOT NULL DEFAULT 0,
                approval_count INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                inputs_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                task_name TEXT NOT NULL,
                task_order INTEGER NOT NULL,
                agent_role TEXT,
                model_name TEXT,
                status TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                summary TEXT,
                excerpt TEXT,
                output_path TEXT,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                estimated_cost_usd REAL NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(run_id, task_name),
                FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS assets (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                company_name TEXT,
                asset_type TEXT NOT NULL,
                title TEXT NOT NULL,
                path TEXT NOT NULL,
                status TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS approval_items (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                company_name TEXT,
                title TEXT NOT NULL,
                asset_bundle_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                decided_at TEXT,
                rejection_reason TEXT,
                reroute_targets_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                subject TEXT NOT NULL,
                recipient TEXT NOT NULL,
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
            );
            """
        )


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _serialize_run_row(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": run_id,
        "crew_name": payload.get("crew_name", "SalesFactory"),
        "trigger_source": payload.get("trigger_source", "manual"),
        "status": payload.get("status", "queued"),
        "lead_mode": payload.get("lead_mode"),
        "lead_query": payload.get("lead_query"),
        "target_country": payload.get("target_country"),
        "proposal_language": payload.get("proposal_language"),
        "currency": payload.get("currency"),
        "max_companies": payload.get("max_companies"),
        "test_mode": bool(payload.get("test_mode", True)),
        "started_at": payload.get("started_at", now_iso()),
        "last_heartbeat_at": payload.get("last_heartbeat_at", now_iso()),
        "inputs_json": payload.get("inputs_json", {}),
        "metadata_json": payload.get("metadata_json", {}),
    }


def create_run(run_id: str, payload: dict[str, Any]) -> None:
    if is_supabase_backend():
        supabase_upsert_rows("runs", [_serialize_run_row(run_id, payload)], on_conflict="id")
        return

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO runs (
                id, crew_name, trigger_source, status, lead_mode, lead_query,
                target_country, proposal_language, currency, max_companies,
                test_mode, started_at, last_heartbeat_at, inputs_json, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                payload.get("crew_name", "SalesFactory"),
                payload.get("trigger_source", "manual"),
                payload.get("status", "queued"),
                payload.get("lead_mode"),
                payload.get("lead_query"),
                payload.get("target_country"),
                payload.get("proposal_language"),
                payload.get("currency"),
                payload.get("max_companies"),
                1 if payload.get("test_mode", True) else 0,
                payload.get("started_at", now_iso()),
                payload.get("last_heartbeat_at", now_iso()),
                _json(payload.get("inputs_json", {})),
                _json(payload.get("metadata_json", {})),
            ),
        )


def update_run(run_id: str, **fields: Any) -> None:
    if not fields:
        return

    allowed = {
        "status",
        "finished_at",
        "last_heartbeat_at",
        "current_task",
        "current_agent",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "cached_prompt_tokens",
        "successful_requests",
        "estimated_cost_usd",
        "approval_count",
        "error_message",
        "metadata_json",
    }
    assignments: list[str] = []
    values: list[Any] = []
    payload: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in allowed:
            continue
        assignments.append(f"{key} = ?")
        if key == "metadata_json":
            values.append(_json(value))
            payload[key] = value
        else:
            values.append(value)
            payload[key] = value

    if not assignments:
        return

    if is_supabase_backend():
        supabase_update_rows("runs", payload, filters=[("id", "eq", run_id)])
        return

    values.append(run_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE runs SET {', '.join(assignments)} WHERE id = ?",
            values,
        )


def register_tasks(run_id: str, tasks: list[dict[str, Any]]) -> None:
    if is_supabase_backend():
        supabase_upsert_rows(
            "task_events",
            [
                {
                    "run_id": run_id,
                    "task_name": task["task_name"],
                    "task_order": task["task_order"],
                    "agent_role": task.get("agent_role"),
                    "model_name": task.get("model_name"),
                    "status": task.get("status", "pending"),
                    "started_at": task.get("started_at"),
                    "metadata_json": task.get("metadata_json", {}),
                }
                for task in tasks
            ],
            on_conflict="run_id,task_name",
        )
        return

    with get_connection() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO task_events (
                run_id, task_name, task_order, agent_role, model_name,
                status, started_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    task["task_name"],
                    task["task_order"],
                    task.get("agent_role"),
                    task.get("model_name"),
                    task.get("status", "pending"),
                    task.get("started_at"),
                    _json(task.get("metadata_json", {})),
                )
                for task in tasks
            ],
        )


def update_task(run_id: str, task_name: str, **fields: Any) -> None:
    if not fields:
        return

    allowed = {
        "status",
        "started_at",
        "finished_at",
        "summary",
        "excerpt",
        "output_path",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "estimated_cost_usd",
        "metadata_json",
    }
    assignments: list[str] = []
    values: list[Any] = []
    payload: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in allowed:
            continue
        assignments.append(f"{key} = ?")
        if key == "metadata_json":
            values.append(_json(value))
            payload[key] = value
        else:
            values.append(value)
            payload[key] = value

    if not assignments:
        return

    if is_supabase_backend():
        supabase_update_rows(
            "task_events",
            payload,
            filters=[("run_id", "eq", run_id), ("task_name", "eq", task_name)],
        )
        return

    values.extend([run_id, task_name])
    with get_connection() as conn:
        conn.execute(
            f"""
            UPDATE task_events
            SET {', '.join(assignments)}
            WHERE run_id = ? AND task_name = ?
            """,
            values,
        )


def create_asset(asset_id: str, payload: dict[str, Any]) -> None:
    if is_supabase_backend():
        supabase_upsert_rows(
            "assets",
            [
                {
                    "id": asset_id,
                    "run_id": payload["run_id"],
                    "company_name": payload.get("company_name"),
                    "asset_type": payload["asset_type"],
                    "title": payload["title"],
                    "path": payload["path"],
                    "status": payload.get("status", "generated"),
                    "version": payload.get("version", 1),
                    "created_at": payload.get("created_at", now_iso()),
                    "metadata_json": payload.get("metadata_json", {}),
                }
            ],
            on_conflict="id",
        )
        return

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO assets (
                id, run_id, company_name, asset_type, title, path,
                status, version, created_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                payload["run_id"],
                payload.get("company_name"),
                payload["asset_type"],
                payload["title"],
                payload["path"],
                payload.get("status", "generated"),
                payload.get("version", 1),
                payload.get("created_at", now_iso()),
                _json(payload.get("metadata_json", {})),
            ),
        )


def create_approval_item(item_id: str, payload: dict[str, Any]) -> None:
    if is_supabase_backend():
        supabase_upsert_rows(
            "approval_items",
            [
                {
                    "id": item_id,
                    "run_id": payload["run_id"],
                    "company_name": payload.get("company_name"),
                    "title": payload["title"],
                    "asset_bundle_json": payload.get("asset_bundle_json", []),
                    "status": payload.get("status", "waiting_approval"),
                    "priority": payload.get("priority", 0),
                    "created_at": payload.get("created_at", now_iso()),
                    "reroute_targets_json": payload.get("reroute_targets_json", []),
                    "metadata_json": payload.get("metadata_json", {}),
                }
            ],
            on_conflict="id",
        )
        return

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO approval_items (
                id, run_id, company_name, title, asset_bundle_json, status,
                priority, created_at, reroute_targets_json, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                payload["run_id"],
                payload.get("company_name"),
                payload["title"],
                _json(payload.get("asset_bundle_json", [])),
                payload.get("status", "waiting_approval"),
                payload.get("priority", 0),
                payload.get("created_at", now_iso()),
                _json(payload.get("reroute_targets_json", [])),
                _json(payload.get("metadata_json", {})),
            ),
        )


def update_approval_item(item_id: str, **fields: Any) -> None:
    if not fields:
        return

    allowed = {
        "status",
        "decided_at",
        "rejection_reason",
        "reroute_targets_json",
        "metadata_json",
    }
    assignments: list[str] = []
    values: list[Any] = []
    payload: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in allowed:
            continue
        assignments.append(f"{key} = ?")
        if key in {"reroute_targets_json", "metadata_json"}:
            values.append(_json(value))
            payload[key] = value
        else:
            values.append(value)
            payload[key] = value

    if not assignments:
        return

    if is_supabase_backend():
        supabase_update_rows("approval_items", payload, filters=[("id", "eq", item_id)])
        return

    values.append(item_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE approval_items SET {', '.join(assignments)} WHERE id = ?",
            values,
        )


def record_notification(
    run_id: str | None,
    kind: str,
    status: str,
    subject: str,
    recipient: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    if is_supabase_backend():
        supabase_insert_rows(
            "notifications",
            [
                {
                    "run_id": run_id,
                    "kind": kind,
                    "status": status,
                    "subject": subject,
                    "recipient": recipient,
                    "created_at": now_iso(),
                    "metadata_json": metadata or {},
                }
            ],
        )
        return

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO notifications (
                run_id, kind, status, subject, recipient, created_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                kind,
                status,
                subject,
                recipient,
                now_iso(),
                _json(metadata or {}),
            ),
        )


def fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    if is_supabase_backend():
        raise RuntimeError("Raw SQL fetch is unavailable in Supabase mode. Use named runtime_db helpers.")
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def fetch_one(query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    if is_supabase_backend():
        raise RuntimeError("Raw SQL fetch is unavailable in Supabase mode. Use named runtime_db helpers.")
    with get_connection() as conn:
        row = conn.execute(query, params).fetchone()
    return dict(row) if row else None


def get_run(run_id: str) -> dict[str, Any] | None:
    if is_supabase_backend():
        return supabase_select_row("runs", filters=[("id", "eq", run_id)])
    return fetch_one("SELECT * FROM runs WHERE id = ?", (run_id,))


def query_running_run() -> dict[str, Any] | None:
    if is_supabase_backend():
        return supabase_select_row("runs", filters=[("status", "eq", "running")], order_by=("started_at", True))
    return fetch_one(
        """
        SELECT *
        FROM runs
        WHERE status = 'running'
        ORDER BY started_at DESC
        LIMIT 1
        """
    )


def list_running_runs() -> list[dict[str, Any]]:
    if is_supabase_backend():
        return supabase_select_rows("runs", filters=[("status", "eq", "running")], order_by=("started_at", True))
    return fetch_all(
        """
        SELECT *
        FROM runs
        WHERE status = 'running'
        ORDER BY started_at DESC
        """
    )


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    if is_supabase_backend():
        return supabase_select_rows("runs", order_by=("started_at", True), limit=limit)
    return fetch_all(
        """
        SELECT *
        FROM runs
        ORDER BY started_at DESC
        LIMIT ?
        """,
        (limit,),
    )


def list_tasks(run_id: str) -> list[dict[str, Any]]:
    if is_supabase_backend():
        return supabase_select_rows("task_events", filters=[("run_id", "eq", run_id)], order_by=("task_order", False))
    return fetch_all(
        """
        SELECT *
        FROM task_events
        WHERE run_id = ?
        ORDER BY task_order ASC
        """,
        (run_id,),
    )


def list_pending_tasks(run_id: str) -> list[dict[str, Any]]:
    if is_supabase_backend():
        return supabase_select_rows(
            "task_events",
            filters=[("run_id", "eq", run_id), ("status", "in", ["pending", "running"])],
            order_by=("task_order", False),
        )
    return fetch_all(
        """
        SELECT task_name
        FROM task_events
        WHERE run_id = ? AND status IN ('pending', 'running')
        ORDER BY task_order ASC
        """,
        (run_id,),
    )


def list_task_costs(run_id: str) -> list[dict[str, Any]]:
    if is_supabase_backend():
        rows = supabase_select_rows("task_events", filters=[("run_id", "eq", run_id)])
        return [{"estimated_cost_usd": row.get("estimated_cost_usd", 0)} for row in rows]
    return fetch_all(
        "SELECT estimated_cost_usd FROM task_events WHERE run_id = ?",
        (run_id,),
    )


def list_assets(run_id: str | None = None, *, limit: int = 200) -> list[dict[str, Any]]:
    if is_supabase_backend():
        filters = [("run_id", "eq", run_id)] if run_id else None
        effective_limit = None if run_id else limit
        return supabase_select_rows("assets", filters=filters, order_by=("created_at", True), limit=effective_limit)
    if run_id:
        return fetch_all(
            """
            SELECT *
            FROM assets
            WHERE run_id = ?
            ORDER BY created_at DESC
            """,
            (run_id,),
        )
    return fetch_all(
        """
        SELECT *
        FROM assets
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    )


def list_assets_by_ids(asset_ids: list[str]) -> list[dict[str, Any]]:
    if not asset_ids:
        return []
    if is_supabase_backend():
        rows = supabase_select_rows("assets", filters=[("id", "in", asset_ids)])
        order_lookup = {asset_id: index for index, asset_id in enumerate(asset_ids)}
        return sorted(rows, key=lambda row: (row.get("asset_type") or "", order_lookup.get(row["id"], 9999)))
    placeholders = ",".join("?" for _ in asset_ids)
    return fetch_all(
        f"SELECT * FROM assets WHERE id IN ({placeholders}) ORDER BY asset_type ASC",
        tuple(asset_ids),
    )


def list_approval_items(status: str | None = None, *, limit: int = 200) -> list[dict[str, Any]]:
    if is_supabase_backend():
        filters = [("status", "eq", status)] if status else None
        return supabase_select_rows("approval_items", filters=filters, order_by=("created_at", True), limit=limit)
    if status:
        return fetch_all(
            """
            SELECT *
            FROM approval_items
            WHERE status = ?
            ORDER BY created_at DESC
            """,
            (status,),
        )
    return fetch_all(
        """
        SELECT *
        FROM approval_items
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    )


def list_approval_items_for_run(run_id: str, status: str | None = None) -> list[dict[str, Any]]:
    if is_supabase_backend():
        filters: list[tuple[str, str, Any]] = [("run_id", "eq", run_id)]
        if status:
            filters.append(("status", "eq", status))
        return supabase_select_rows("approval_items", filters=filters, order_by=("created_at", True))
    if status:
        return fetch_all(
            """
            SELECT *
            FROM approval_items
            WHERE run_id = ? AND status = ?
            ORDER BY created_at DESC
            """,
            (run_id, status),
        )
    return fetch_all(
        """
        SELECT *
        FROM approval_items
        WHERE run_id = ?
        ORDER BY created_at DESC
        """,
        (run_id,),
    )


def list_notifications(limit: int = 20) -> list[dict[str, Any]]:
    if is_supabase_backend():
        return supabase_select_rows("notifications", order_by=("created_at", True), limit=limit)
    return fetch_all(
        """
        SELECT *
        FROM notifications
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    )


def summarize_approval_items(run_id: str) -> dict[str, int]:
    rows = list_approval_items_for_run(run_id)
    waiting_count = sum(1 for row in rows if row.get("status") == "waiting_approval")
    approved_count = sum(1 for row in rows if row.get("status") == "approved")
    rejected_count = sum(1 for row in rows if row.get("status") == "rejected")
    return {
        "waiting_count": waiting_count,
        "approved_count": approved_count,
        "rejected_count": rejected_count,
    }


def mark_stale_runs(timeout_minutes: int = 15) -> int:
    cutoff = datetime.now() - timedelta(minutes=timeout_minutes)
    rows = list_running_runs()
    updated = 0
    for row in rows:
        heartbeat = row.get("last_heartbeat_at")
        if not heartbeat:
            continue
        try:
            heartbeat_dt = datetime.fromisoformat(heartbeat)
        except ValueError:
            continue
        if heartbeat_dt < cutoff:
            update_run(
                row["id"],
                status="failed",
                finished_at=now_iso(),
                error_message="Run became stale and was marked failed automatically.",
            )
            updated += 1
    return updated
