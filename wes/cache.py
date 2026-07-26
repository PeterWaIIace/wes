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
                data = yaml.safe_load(f)
                return data if isinstance(data, dict) else {}
        return {}

    def _save(self) -> None:
        with open(self._cache_file, "w", encoding="utf-8") as f:
            yaml.dump(self._data, f, default_flow_style=False)

    def get_all(self) -> dict[str, dict]:
        tasks = self._data.get("tasks")
        return dict(tasks) if isinstance(tasks, dict) else {}

    def set(self, name: str, data: dict) -> None:
        tasks = self._data.get("tasks")
        if not isinstance(tasks, dict):
            self._data["tasks"] = {}
        self._data["tasks"][name] = data
        self._save()

    def remove(self, name: str) -> None:
        tasks = self._data.get("tasks")
        if isinstance(tasks, dict):
            tasks.pop(name, None)
        self._save()

    def close(self) -> None:
        if not self._persistent:
            shutil.rmtree(self._tmpdir, ignore_errors=True)

    def find_by_task_name(self, name: str) -> list[tuple[str, dict]]:
        """Find all cache entries matching a task name. Returns list of (key, data)."""
        results = []
        for key, data in (self._data.get("tasks") or {}).items():
            if isinstance(data, dict) and data.get("task_name") == name:
                results.append((key, data))
        return results

    def clean_for_task_names(self, names: set[str]) -> list[tuple[str, Task]]:
        """Remove all cache entries whose task_name is in `names`.

        Returns list of (run_id, Task) for the caller to cancel SLURM jobs.
        """
        removed: list[tuple[str, Task]] = []
        for run_id, data in list(self.get_all().items()):
            if not isinstance(data, dict):
                continue
            if data.get("task_name") in names:
                removed.append((run_id, self.cached_task(run_id, data)))
                self.remove(run_id)
        return removed

    def clean_dead(self, is_alive_fn) -> list[str]:
        """Remove cache entries whose jobs are no longer alive.

        `is_alive_fn(task)` returns True if the task's jobs are still running.
        Returns list of run_ids that were removed.
        """
        removed: list[str] = []
        for run_id, data in list(self.get_all().items()):
            if not isinstance(data, dict):
                continue
            state = State(data.get("state", "PENDING"))
            if state not in (State.RUNNING, State.PENDING):
                self.remove(run_id)
                removed.append(run_id)
                continue
            task = self.cached_task(run_id, data)
            if not is_alive_fn(task):
                self.remove(run_id)
                removed.append(run_id)
        return removed

    @staticmethod
    def task_to_cache_data(task: Task) -> dict:
        return {
            "task_name": task.name,
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
            "partition": task.partition,
            "cpus": task.cpus,
            "gpus": task.gpus,
            "memory": task.memory,
            "time": task.time,
            "nodelist": task.nodelist,
            "run_id": task.run_id,
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
            artifacts=data.get("artifacts", []),
            cleanup=data.get("cleanup", False),
            active_jobs=data.get("jobs_ids", []),
            state=State(data["state"]),
            partition=data.get("partition", ""),
            cpus=data.get("cpus", ""),
            gpus=data.get("gpus", ""),
            memory=data.get("memory", ""),
            time=data.get("time", ""),
            nodelist=data.get("nodelist", ""),
            run_id=data.get("run_id", ""),
        )
