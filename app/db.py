from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .config import DB_PATH, ensure_runtime_dirs


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    ensure_runtime_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS drafts (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL,
                summary TEXT NOT NULL,
                operations TEXT NOT NULL,
                error TEXT
            );
            """
        )


def save_draft(draft_id: str, payload: dict[str, Any], status: str = "draft") -> None:
    ts = now_iso()
    raw = json.dumps(payload, ensure_ascii=False)
    with connect() as conn:
        exists = conn.execute("SELECT 1 FROM drafts WHERE id=?", (draft_id,)).fetchone()
        if exists:
            conn.execute(
                "UPDATE drafts SET updated_at=?, status=?, payload=? WHERE id=?",
                (ts, status, raw, draft_id),
            )
        else:
            conn.execute(
                "INSERT INTO drafts(id, created_at, updated_at, status, payload) VALUES(?,?,?,?,?)",
                (draft_id, ts, ts, status, raw),
            )


def get_draft(draft_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "status": row["status"],
        "payload": json.loads(row["payload"]),
    }


def list_drafts(limit: int = 10) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, created_at, updated_at, status, payload FROM drafts ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    result = []
    for row in rows:
        payload = json.loads(row["payload"])
        result.append({
            "id": row["id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "status": row["status"],
            "series_title": payload.get("series_title", "未命名剧集"),
            "episode_count": len(payload.get("episodes", [])),
        })
    return result


def create_task(task_id: str, summary: str, operations: list[dict[str, Any]], status: str, error: str | None = None) -> None:
    ts = now_iso()
    with connect() as conn:
        conn.execute(
            "INSERT INTO tasks(id, created_at, updated_at, status, summary, operations, error) VALUES(?,?,?,?,?,?,?)",
            (task_id, ts, ts, status, summary, json.dumps(operations, ensure_ascii=False), error),
        )


def update_task(task_id: str, *, status: str, operations: list[dict[str, Any]] | None = None, error: str | None = None) -> None:
    ts = now_iso()
    with connect() as conn:
        if operations is None:
            conn.execute("UPDATE tasks SET updated_at=?, status=?, error=? WHERE id=?", (ts, status, error, task_id))
        else:
            conn.execute(
                "UPDATE tasks SET updated_at=?, status=?, operations=?, error=? WHERE id=?",
                (ts, status, json.dumps(operations, ensure_ascii=False), error, task_id),
            )


def get_task(task_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "status": row["status"],
        "summary": row["summary"],
        "operations": json.loads(row["operations"]),
        "error": row["error"],
    }


def list_tasks(limit: int = 20) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "status": row["status"],
            "summary": row["summary"],
            "operations": json.loads(row["operations"]),
            "error": row["error"],
        }
        for row in rows
    ]
