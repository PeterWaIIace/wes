from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml

from .states import State
from .tasks import Task

_CACHE_FILENAME = "cache.yml"
_PERSISTENT_CACHE = ".wes-cache.yml"


class JobCache:
    def __init__(self, persistent: bool = False) -> None:
        self._persistent = persistent
        if persistent:
            self._cache_file = Path(_PERSISTENT_CACHE)
        else:
            self._tmpdir = Path(tempfile.mkdtemp(prefix="wes_"))
            self._cache_file = self._tmpdir / _CACHE_FILENAME
        self._data: dict = self._load()

    def _load(self) -> dict:
        if self._cache_file.exists():
            with open(self._cache_file, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def _save(self) -> None:
        with open(self._cache_file, "w", encoding="utf-8") as f:
            yaml.dump(self._data, f, default_flow_style=False)

    def get_all(self) -> dict[str, dict]:
        return self._data.get("tasks", {})

    def set(self, name: str, data: dict) -> None:
        self._data.setdefault("tasks", {})[name] = data
        self._save()

    def remove(self, name: str) -> None:
        self._data.get("tasks", {}).pop(name, None)
        self._save()

    def close(self) -> None:
        if not self._persistent:
            shutil.rmtree(self._tmpdir, ignore_errors=True)

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
