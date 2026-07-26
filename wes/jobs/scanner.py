from __future__ import annotations

import json

from wes.tasks.tasks import Task
from wes.jobs.job import Job
from wes.remote.runner import SshRunner


class JobScanner:

    def __init__(self, ssh_config: str, base_dir: str = ".") -> None:
        self.ssh_config = ssh_config
        self.runner = SshRunner(ssh_config)
        self.base_dir = base_dir

    def _list_job_dirs(self) -> list[str]:
        ok, lines = self.runner.run_command(f"find {self.base_dir} -maxdepth 4 -name '*_config.json'")
        if not ok:
            return []
        return lines

    def _read_config(self, config_path: str) -> dict | None:
        ok, lines = self.runner.run_command(f"cat {config_path}")
        if not ok or not lines:
            return None
        try:
            return json.loads("\n".join(lines))
        except json.JSONDecodeError:
            return None

    def _config_to_task(self, config: dict) -> Task:
        t = config["task"]
        return Task(
            name=t["name"],
            git_url=t["git_url"],
            path=t.get("path", ""),
            ssh_config=t.get("ssh_config", self.ssh_config),
            job_script=t.get("job_script"),
            branch=t.get("branch", ""),
            cleanup=t.get("cleanup", False),
            artifacts=t.get("artifacts", []),
            partition=t.get("partition", ""),
            cpus=t.get("cpus", ""),
            gpus=t.get("gpus", ""),
            memory=t.get("memory", ""),
            time=t.get("time", ""),
            nodelist=t.get("nodelist", ""),
        )

    def scan(self) -> list[Job]:
        config_paths = self._list_job_dirs()
        results = []
        for path in config_paths:
            config = self._read_config(path)
            if not config:
                continue
            task = self._config_to_task(config)
            ssh_config = config.get("job", {}).get("ssh_config", self.ssh_config)
            namespace = config.get("job", {}).get("namespace", "")
            job = Job(task, ssh_config, namespace=namespace)
            results.append(job)
        return results
