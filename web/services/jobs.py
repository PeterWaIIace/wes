from __future__ import annotations

from web.cache import JobCache
from wes.remote.runner import SshRunner


def get_ssh_user(ssh: str) -> str:
    try:
        return SshRunner(ssh).get_user()
    except Exception:
        return ""


def build_cache_index() -> dict[str, dict]:
    cache = JobCache()
    index: dict[str, dict] = {}
    for run_id, data in cache.get_all().items():
        if not isinstance(data, dict):
            continue
        entry = {**data, "run_id": run_id}
        for jid in entry.get("jobs_ids", []):
            index[str(jid)] = entry
        index[run_id] = entry
    return index


def job_dir_from_name(job_name: str) -> tuple[str, str]:
    idx = job_name.rfind("_")
    if idx > 0:
        return job_name[:idx], job_name[idx + 1 :]
    return job_name, ""


def make_job_dir(cached: dict, name: str) -> str:
    task_name = cached.get("task_name") or ""
    run_id = cached.get("run_id") or ""
    if task_name and run_id:
        return f"{task_name}/{run_id}"
    if run_id:
        return f"{name}/{run_id}"
    task, ns = job_dir_from_name(name)
    return f"{task}/{ns}" if ns else task
