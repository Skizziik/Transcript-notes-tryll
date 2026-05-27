from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    audio_name TEXT NOT NULL,
    audio_size INTEGER,
    audio_duration_sec REAL,
    language TEXT,
    status TEXT NOT NULL,
    error TEXT,
    title TEXT,
    run_dir TEXT NOT NULL,
    artifacts TEXT NOT NULL DEFAULT '{}',
    settings TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at DESC);
"""


def init() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        c.executescript(SCHEMA)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def create_run(run_id: str, created_at: str, audio_name: str, audio_size: int, run_dir: str, settings: dict) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO runs (id, created_at, audio_name, audio_size, status, run_dir, settings) VALUES (?,?,?,?,?,?,?)",
            (run_id, created_at, audio_name, audio_size, "queued", run_dir, json.dumps(settings)),
        )


def update_run(run_id: str, **fields: Any) -> None:
    if not fields:
        return
    if "artifacts" in fields and not isinstance(fields["artifacts"], str):
        fields["artifacts"] = json.dumps(fields["artifacts"])
    if "settings" in fields and not isinstance(fields["settings"], str):
        fields["settings"] = json.dumps(fields["settings"])
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [run_id]
    with connect() as c:
        c.execute(f"UPDATE runs SET {cols} WHERE id=?", vals)


def get_run(run_id: str) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return _row_to_dict(row) if row else None


def list_runs(limit: int = 200) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [_row_to_dict(r) for r in rows]


def delete_run(run_id: str) -> dict | None:
    run = get_run(run_id)
    if run is None:
        return None
    with connect() as c:
        c.execute("DELETE FROM runs WHERE id=?", (run_id,))
    return run


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for key in ("artifacts", "settings"):
        try:
            d[key] = json.loads(d.get(key) or "{}")
        except Exception:
            d[key] = {}
    return d
