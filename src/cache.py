from pathlib import Path

import yaml

from .states import State
from .tasks import Task

CACHE_FILE = Path("cache.yml")


class JobCache:
    def __init__(self):
        self._data = self._load()

    def _load(self) -> dict:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def _save(self):
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            yaml.dump(self._data, f, default_flow_style=False)

    def get_all(self) -> dict:
        return self._data.get("tasks", {})

    def set(self, name: str, data: dict):
        self._data.setdefault("tasks", {})[name] = data
        self._save()

    def remove(self, name: str):
        self._data.get("tasks", {}).pop(name, None)
        self._save()

    @staticmethod
    def task_to_cache_data(task: Task) -> dict:
        return {
            "state": task.status.value,
            "jobs_ids": task.jobs_ids,
            "git_url": task.git_url,
            "branch": task.branch,
            "ssh": task.ssh_config,
            "path": task.path,
            "job": task.job,
            "run": task.run,
            "post": task.post,
            "artifacts": task.artifacts,
            "cleanup": task.cleanup_git,
        }

    @staticmethod
    def cached_task(name: str, data: dict) -> Task:
        return Task(
            name=name,
            git_url=data.get("git_url", ""),
            branch=data.get("branch", ""),
            path=data.get("path", "."),
            ssh_config=data.get("ssh", ""),
            job=data.get("job", ""),
            run=data.get("run", []),
            post=data.get("post", ""),
            artifacts=data.get("artifacts", []),
            cleanup=data.get("cleanup", False),
            active_jobs=data.get("jobs_ids", []),
            state=State(data["state"]),
        )
