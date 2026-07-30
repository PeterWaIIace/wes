from __future__ import annotations

from pathlib import Path

import yaml

_CACHE_FILENAME = ".wes-cache.yml"


class JobCache:
    def __init__(self) -> None:
        self._cache_file = Path(_CACHE_FILENAME)
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

    def get(self, run_id: str) -> dict | None:
        return self.get_all().get(run_id)

    def set(self, run_id: str, data: dict) -> None:
        if "tasks" not in self._data:
            self._data["tasks"] = {}
        self._data["tasks"][run_id] = data
        self._save()

    def remove(self, run_id: str) -> None:
        tasks = self._data.get("tasks")
        if isinstance(tasks, dict):
            tasks.pop(run_id, None)
        self._save()

    def find_by_task_name(self, name: str) -> list[tuple[str, dict]]:
        results = []
        for run_id, data in self.get_all().items():
            if isinstance(data, dict) and data.get("task_name") == name:
                results.append((run_id, data))
        return results

    def clean_for_task_names(self, names: set[str]) -> list[tuple[str, dict]]:
        removed: list[tuple[str, dict]] = []
        for run_id, data in list(self.get_all().items()):
            if not isinstance(data, dict):
                continue
            if data.get("task_name") in names:
                removed.append((run_id, data))
                self.remove(run_id)
        return removed


def task_to_cache_data(task: dict) -> dict:
    return {
        "task_name": task.get("name", ""),
        "state": task.get("state", "PENDING"),
        "jobs_ids": task.get("jobs_ids", []),
        "git_url": task.get("git_url", ""),
        "branch": task.get("branch", ""),
        "ssh": task.get("ssh", ""),
        "path": task.get("path", ""),
        "job": task.get("job", ""),
        "run": task.get("run", []),
        "post": task.get("post", ""),
        "artifacts": task.get("artifacts", []),
        "cleanup": task.get("cleanup", False),
        "partition": task.get("partition", ""),
        "cpus": task.get("cpus", ""),
        "gpus": task.get("gpus", ""),
        "memory": task.get("memory", ""),
        "time": task.get("time", ""),
        "nodelist": task.get("nodelist", ""),
        "run_id": task.get("run_id", ""),
    }
