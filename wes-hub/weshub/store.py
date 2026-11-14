from __future__ import annotations

import re
import threading
import time

_PIPELINE_DEFAULTS = {
    "ssh": "",
    "cron": "",
    "enabled": 1,
    "next_run_at": None,
}

_RUN_DEFAULTS = {
    "trigger": "manual",
    "status": "",
    "finished_at": None,
}

_JOB_DEFAULTS = {
    "run_id": None,
    "pipeline_id": None,
    "task": "",
    "job_name": "",
    "ssh": "",
    "state": "",
    "job_id": "",
    "node": "",
    "partition": "",
    "message": "",
    "updated": "",
    "discovered": 0,
    "artifacts_pulled": 0,
}

_CHILD_DEFAULTS = {
    "job_id": "",
    "state": "",
    "node": "",
    "partition": "",
    "message": "",
    "updated": "",
}

_ACTIVE_RUN_STATUSES = ("", "queued", "running", "PENDING", "RUNNING")


def _cast_int(value: str) -> int:
    """Mimic SQLite's CAST(x AS INTEGER): leading numeric prefix, else 0."""
    match = re.match(r"\s*[+-]?\d+", str(value))
    return int(match.group()) if match else 0


class Store:
    """Thread-safe in-memory runtime store.

    Pipelines, runs, jobs and array children live only for the lifetime of
    the process; nothing is written to disk.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self._pipelines: dict[int, dict] = {}
        self._runs: dict[int, dict] = {}
        self._jobs: dict[str, dict] = {}
        self._array_children: dict[tuple[str, str], dict] = {}
        self._next_pipeline_id = 1
        self._next_run_id = 1
        self._next_job_id = 1

    # -- pipelines ---------------------------------------------------------

    def add_pipeline(self, name: str, wes_yaml: str, ssh: str, cron: str, enabled: bool) -> dict:
        with self.lock:
            pid = self._next_pipeline_id
            self._next_pipeline_id += 1
            row = {
                "id": pid,
                "name": name,
                "wes_yaml": wes_yaml,
                **_PIPELINE_DEFAULTS,
                "ssh": ssh,
                "cron": cron,
                "enabled": int(enabled),
                "created_at": time.time(),
            }
            self._pipelines[pid] = row
            return dict(row)

    def update_pipeline(self, pid: int, **fields) -> dict | None:
        allowed = {"name", "wes_yaml", "ssh", "cron", "enabled", "next_run_at"}
        with self.lock:
            row = self._pipelines.get(pid)
            if row is not None:
                for key, value in fields.items():
                    if key in allowed and value is not None:
                        row[key] = value
            return dict(row) if row else None

    def delete_pipeline(self, pid: int) -> None:
        with self.lock:
            self._pipelines.pop(pid, None)

    def get_pipeline(self, pid: int) -> dict | None:
        with self.lock:
            row = self._pipelines.get(pid)
            return dict(row) if row else None

    def get_pipeline_by_name(self, name: str) -> dict | None:
        with self.lock:
            for row in self._pipelines.values():
                if row["name"] == name:
                    return dict(row)
        return None

    def list_pipelines(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in sorted(self._pipelines.values(), key=lambda r: r["id"])]

    # -- runs --------------------------------------------------------------

    def add_run(self, pipeline_id: int, trigger: str) -> dict:
        with self.lock:
            rid = self._next_run_id
            self._next_run_id += 1
            row = {
                "id": rid,
                "pipeline_id": pipeline_id,
                **_RUN_DEFAULTS,
                "trigger": trigger,
                "created_at": time.time(),
            }
            self._runs[rid] = row
            return dict(row)

    def delete_run(self, run_id: int) -> None:
        with self.lock:
            self._runs.pop(run_id, None)
            for ns in [ns for ns, row in self._jobs.items() if row["run_id"] == run_id]:
                del self._jobs[ns]

    def update_run(self, run_id: int, status: str, finished_at: float | None = None) -> None:
        with self.lock:
            row = self._runs.get(run_id)
            if row is None:
                return
            row["status"] = status
            if finished_at is not None:
                row["finished_at"] = finished_at

    def get_run(self, run_id: int) -> dict | None:
        with self.lock:
            row = self._runs.get(run_id)
            return dict(row) if row else None

    def list_runs(self, pipeline_id: int | None = None, limit: int = 100) -> list[dict]:
        with self.lock:
            rows = self._runs.values()
            if pipeline_id is not None:
                rows = (r for r in rows if r["pipeline_id"] == pipeline_id)
            ordered = sorted(rows, key=lambda r: r["id"], reverse=True)[:limit]
            return [dict(r) for r in ordered]

    def active_run_states(self) -> list[int]:
        with self.lock:
            return [
                r["id"]
                for r in sorted(self._runs.values(), key=lambda r: r["id"])
                if r["status"] in _ACTIVE_RUN_STATUSES
            ]

    # -- jobs --------------------------------------------------------------

    def upsert_job(self, namespace: str, **fields) -> int:
        data = {k: v for k, v in fields.items() if v is not None and k != "namespace"}
        with self.lock:
            row = self._jobs.get(namespace)
            if row is None:
                jid = self._next_job_id
                self._next_job_id += 1
                row = {
                    "id": jid,
                    "namespace": namespace,
                    **_JOB_DEFAULTS,
                    "created_at": time.time(),
                }
                row.update(data)
                self._jobs[namespace] = row
            else:
                row.update(data)
            return row["id"]

    def get_job(self, namespace: str) -> dict | None:
        with self.lock:
            row = self._jobs.get(namespace)
            return dict(row) if row else None

    def delete_job(self, namespace: str) -> None:
        with self.lock:
            self._jobs.pop(namespace, None)
            for key in [k for k in self._array_children if k[0] == namespace]:
                del self._array_children[key]

    def list_jobs(self, run_id: int | None = None) -> list[dict]:
        with self.lock:
            rows = self._jobs.values()
            if run_id is not None:
                rows = (r for r in rows if r["run_id"] == run_id)
            return [dict(r) for r in sorted(rows, key=lambda r: r["id"])]

    def set_job_state(self, namespace: str, state: str, **extra) -> None:
        fields = {"state": state, **{k: v for k, v in extra.items() if v is not None}}
        with self.lock:
            row = self._jobs.get(namespace)
            if row is not None:
                row.update(fields)

    def link_job(self, namespace: str, run_id: int, pipeline_id: int) -> None:
        with self.lock:
            row = self._jobs.get(namespace)
            if row is not None:
                row["run_id"] = run_id
                row["pipeline_id"] = pipeline_id

    # -- array children ----------------------------------------------------

    def upsert_array_child(self, parent_namespace: str, array_index: str, **fields) -> None:
        data = {k: v for k, v in fields.items() if v is not None}
        key = (parent_namespace, array_index)
        with self.lock:
            row = self._array_children.get(key)
            if row is None:
                row = {"parent_namespace": parent_namespace, "array_index": array_index, **_CHILD_DEFAULTS}
                row.update(data)
                self._array_children[key] = row
            else:
                row.update(data)

    def list_array_children(self, parent_namespace: str) -> list[dict]:
        with self.lock:
            rows = [r for r in self._array_children.values() if r["parent_namespace"] == parent_namespace]
            rows.sort(key=lambda r: (_cast_int(r["array_index"]), r["array_index"]))
            return [dict(r) for r in rows]
