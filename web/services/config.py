from __future__ import annotations

import json
import logging
from pathlib import Path

from web.cache import JobCache
from web.models import TaskInfo
from web.parser import parse_wes_file
from web.services.mock import mock_enabled, mock_tasks
from web.services.settings import load_settings

log = logging.getLogger("wes.web")

RESULTS_DIR = Path("results")


def find_local_config(job_id: str) -> dict | None:
    for config_path in RESULTS_DIR.glob(f"*_{job_id}/*_config.json"):
        try:
            with open(config_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return None


def parse_wes_files() -> list[TaskInfo]:
    if mock_enabled():
        return mock_tasks()

    wes_files = sorted(Path(".").glob("*.wes"))
    if not wes_files:
        return []

    cached = JobCache().get_all() or {}

    tasks: list[TaskInfo] = []
    seen_names: set[str] = set()
    for wes_file in wes_files:
        try:
            for task_dict in parse_wes_file(str(wes_file)):
                if task_dict["name"] in seen_names:
                    continue
                seen_names.add(task_dict["name"])
                state = ""
                active_run_id = ""
                for run_id, data in cached.items():
                    if isinstance(data, dict) and data.get("task_name") == task_dict["name"]:
                        state = data.get("state", "")
                        active_run_id = run_id
                        break
                tasks.append(
                    TaskInfo(
                        name=task_dict["name"],
                        git_url=task_dict["git_url"],
                        branch=task_dict["branch"],
                        ssh=task_dict["ssh"],
                        job=task_dict["job"],
                        path=task_dict["path"],
                        run=task_dict["run"],
                        pre=task_dict["pre"],
                        post=task_dict["post"],
                        artifacts=task_dict["artifacts"],
                        cleanup=task_dict["cleanup"],
                        partition=task_dict["partition"],
                        cpus=task_dict["cpus"],
                        gpus=task_dict["gpus"],
                        memory=task_dict["memory"],
                        time=task_dict["time"],
                        nodelist=task_dict["nodelist"],
                        status=state,
                        run_id=active_run_id,
                    )
                )
        except Exception as e:
            log.error("Failed to parse %s: %s", wes_file, e)
    return tasks


def known_ssh_hosts() -> list[str]:
    hosts: set[str] = set()
    for task in parse_wes_files():
        if task.ssh:
            hosts.add(task.ssh)
    for h in load_settings().get("ssh_hosts", []):
        hosts.add(h)
    return sorted(hosts)
