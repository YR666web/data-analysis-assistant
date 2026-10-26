"""Local durable task snapshots. No database credentials or external service required."""
import json
import sqlite3
from datetime import datetime, timezone

from utils import path_utils


def _connect():
    directory = path_utils.OUTPUT_DIR / ".history"
    directory.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(directory / "tasks.sqlite3", timeout=5)
    connection.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, updated TEXT NOT NULL, payload TEXT NOT NULL)")
    return connection


def save(thread_id: str, payload: dict) -> None:
    connection = _connect()
    try:
        with connection:
            connection.execute("INSERT INTO tasks VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET updated=excluded.updated, payload=excluded.payload",
                               (thread_id, datetime.now(timezone.utc).isoformat(), json.dumps(payload, ensure_ascii=False)))
    finally:
        connection.close()


def get(thread_id: str) -> dict | None:
    connection = _connect()
    try:
        row = connection.execute("SELECT payload FROM tasks WHERE id=?", (thread_id,)).fetchone()
        return json.loads(row[0]) if row else None
    finally:
        connection.close()


def list_tasks(limit: int = 200, offset: int = 0) -> list[dict]:
    connection = _connect()
    try:
        return [json.loads(row[0]) for row in connection.execute(
            "SELECT payload FROM tasks ORDER BY updated DESC LIMIT ? OFFSET ?", (limit, offset))]
    finally:
        connection.close()


def delete(thread_id: str) -> None:
    connection = _connect()
    try:
        with connection:
            connection.execute("DELETE FROM tasks WHERE id=?", (thread_id,))
    finally:
        connection.close()
