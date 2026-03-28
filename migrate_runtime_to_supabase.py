from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sales_factory.runtime_assets import slugify
from sales_factory.runtime_supabase import (
    load_project_env,
    upsert_rows,
    upload_asset_file,
    verify_schema,
)


JSON_COLUMNS = {
    "inputs_json",
    "metadata_json",
    "asset_bundle_json",
    "reroute_targets_json",
}

JSON_ARRAY_COLUMNS = {
    "asset_bundle_json",
    "reroute_targets_json",
}

TABLE_IMPORT_CONFIG = [
    ("runs", "id"),
    ("task_events", "run_id,task_name"),
    ("assets", "id"),
    ("approval_items", "id"),
    ("notifications", "id"),
]


def _read_sqlite_rows(db_path: Path, table: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def _parse_json_columns(row: dict[str, Any]) -> dict[str, Any]:
    parsed = dict(row)
    for column in JSON_COLUMNS:
        value = parsed.get(column)
        if value is None or isinstance(value, (dict, list)):
            continue
        fallback: Any = [] if column in JSON_ARRAY_COLUMNS else {}
        try:
            parsed[column] = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            parsed[column] = fallback
    return parsed


def _enrich_asset_row(row: dict[str, Any]) -> dict[str, Any]:
    path = Path(row.get("path") or "")
    metadata = dict(row.get("metadata_json") or {})

    if row.get("asset_type") != "proposal_pdf" and path.exists() and path.suffix.lower() != ".pdf":
        metadata.setdefault("inline_content", path.read_text(encoding="utf-8", errors="replace"))

    if path.exists():
        company_slug = slugify(row.get("company_name") or row["id"])
        storage_metadata = upload_asset_file(
            path,
            storage_path=f"{row['run_id']}/{company_slug}/{path.name}",
        )
        metadata.update(storage_metadata)

    row["metadata_json"] = metadata
    return row


def _prepare_rows(table: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for row in rows:
        item = _parse_json_columns(row)
        if table == "runs":
            item["test_mode"] = bool(item.get("test_mode"))
        if table == "task_events":
            item.pop("id", None)
        if table == "assets":
            item = _enrich_asset_row(item)
        prepared.append(item)
    return prepared


def migrate(sqlite_path: Path) -> None:
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite runtime DB not found: {sqlite_path}")

    load_project_env()
    os.environ["SALES_FACTORY_RUNTIME_BACKEND"] = "supabase"
    verify_schema()

    for table, on_conflict in TABLE_IMPORT_CONFIG:
        rows = _prepare_rows(table, _read_sqlite_rows(sqlite_path, table))
        upsert_rows(table, rows, on_conflict=on_conflict)
        print(f"[migrated] {table}: {len(rows)} rows")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate local runtime SQLite data to Supabase.")
    parser.add_argument(
        "--sqlite-path",
        default=str(ROOT_DIR / ".runtime" / "operations.db"),
        help="Path to the local runtime SQLite database.",
    )
    args = parser.parse_args()
    migrate(Path(args.sqlite_path))


if __name__ == "__main__":
    main()
