from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pipelines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    ssh TEXT NOT NULL DEFAULT '',
    cron TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    wes_yaml TEXT NOT NULL,
    created_at REAL NOT NULL,
    next_run_at REAL
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_id INTEGER NOT NULL,
    trigger TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'queued',
    created_at REAL NOT NULL,
    finished_at REAL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace TEXT NOT NULL UNIQUE,
    run_id INTEGER,
    pipeline_id INTEGER,
    task TEXT NOT NULL DEFAULT '',
    job_name TEXT NOT NULL DEFAULT '',
    ssh TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'PENDING',
    job_id TEXT NOT NULL DEFAULT '',
    node TEXT NOT NULL DEFAULT '',
    partition TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    updated TEXT NOT NULL DEFAULT '',
    discovered INTEGER NOT NULL DEFAULT 0,
    artifacts_pulled INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
"""


class Store:
    """Tiny thread-safe sqlite persistence layer."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.executescript(_SCHEMA)
            self.conn.commit()

    # -- helpers -----------------------------------------------------------

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self.lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def _query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def _query_one(self, sql: str, params: tuple = ()) -> dict | None:
        rows = self._query(sql, params)
        return rows[0] if rows else None

    # -- pipelines ---------------------------------------------------------

    def add_pipeline(self, name: str, wes_yaml: str, ssh: str, cron: str, enabled: bool) -> dict:
        now = time.time()
        cur = self._exec(
            "INSERT INTO pipelines "
            "(name, wes_yaml, ssh, cron, enabled, created_at) VALUES (?,?,?,?,?,?)",
            (name, wes_yaml, ssh, cron, int(enabled), now),
        )
        return self.get_pipeline(cur.lastrowid)

    def update_pipeline(self, pid: int, **fields) -> dict | None:
        allowed = {"name", "wes_yaml", "ssh", "cron", "enabled", "next_run_at"}
        cols = [k for k in fields if k in allowed and fields[k] is not None]
        if not cols:
            return self.get_pipeline(pid)
        sets = ", ".join(f"{c} = ?" for c in cols)
        params = tuple(fields[c] for c in cols) + (pid,)
        self._exec(f"UPDATE pipelines SET {sets} WHERE id = ?", params)
        return self.get_pipeline(pid)

    def delete_pipeline(self, pid: int) -> None:
        self._exec("DELETE FROM pipelines WHERE id = ?", (pid,))

    def get_pipeline(self, pid: int) -> dict | None:
        return self._query_one("SELECT * FROM pipelines WHERE id = ?", (pid,))

    def list_pipelines(self) -> list[dict]:
        return self._query("SELECT * FROM pipelines ORDER BY id")

    # -- runs --------------------------------------------------------------

    def add_run(self, pipeline_id: int, trigger: str) -> dict:
        now = time.time()
        cur = self._exec(
            "INSERT INTO runs (pipeline_id, trigger, status, created_at) VALUES (?,?,?,?)",
            (pipeline_id, trigger, "queued", now),
        )
        return self.get_run(cur.lastrowid)

    def update_run(self, run_id: int, status: str, finished_at: float | None = None) -> None:
        if finished_at is not None:
            self._exec(
                "UPDATE runs SET status = ?, finished_at = ? WHERE id = ?",
                (status, finished_at, run_id),
            )
        else:
            self._exec("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))

    def get_run(self, run_id: int) -> dict | None:
        return self._query_one("SELECT * FROM runs WHERE id = ?", (run_id,))

    def list_runs(self, pipeline_id: int | None = None, limit: int = 100) -> list[dict]:
        if pipeline_id is not None:
            return self._query(
                "SELECT * FROM runs WHERE pipeline_id = ? ORDER BY id DESC LIMIT ?",
                (pipeline_id, limit),
            )
        return self._query("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))

    def active_run_states(self) -> list[int]:
        return [
            r["id"] for r in self._query("SELECT id FROM runs WHERE status IN ('queued','running')")
        ]

    # -- jobs --------------------------------------------------------------

    def upsert_job(self, namespace: str, **fields) -> int:
        data = {k: v for k, v in fields.items() if v is not None}
        with self.lock:
            existing = self.conn.execute(
                "SELECT id FROM jobs WHERE namespace = ?", (namespace,)
            ).fetchone()
            if not existing:
                data.pop("namespace", None)
                cols = ["namespace", "created_at"] + list(data)
                vals = [namespace, time.time()] + [data[c] for c in data]
                marks = ", ".join("?" for _ in cols)
                cur = self.conn.execute(
                    f"INSERT INTO jobs ({', '.join(cols)}) VALUES ({marks})", vals
                )
                new_id = cur.lastrowid
            else:
                if data:
                    sets = ", ".join(f"{k} = ?" for k in data)
                    self.conn.execute(
                        f"UPDATE jobs SET {sets} WHERE namespace = ?",
                        (*data.values(), namespace),
                    )
                new_id = existing["id"]
            self.conn.commit()
            return new_id

    def get_job(self, namespace: str) -> dict | None:
        return self._query_one("SELECT * FROM jobs WHERE namespace = ?", (namespace,))

    def list_jobs(self, run_id: int | None = None) -> list[dict]:
        if run_id is not None:
            return self._query("SELECT * FROM jobs WHERE run_id = ? ORDER BY id", (run_id,))
        return self._query("SELECT * FROM jobs ORDER BY id")

    def set_job_state(self, namespace: str, state: str, **extra) -> None:
        fields = {"state": state, **{k: v for k, v in extra.items() if v is not None}}
        sets = ", ".join(f"{k} = ?" for k in fields)
        params = tuple(fields.values()) + (namespace,)
        self._exec(f"UPDATE jobs SET {sets} WHERE namespace = ?", params)

    def link_job(self, namespace: str, run_id: int, pipeline_id: int) -> None:
        self._exec(
            "UPDATE jobs SET run_id = ?, pipeline_id = ? WHERE namespace = ?",
            (run_id, pipeline_id, namespace),
        )

    def close(self) -> None:
        with self.lock:
            self.conn.close()
