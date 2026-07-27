from __future__ import annotations

import re
import uuid

from .states import State

_ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x1b]*\x1b\\")

def _strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)

class Task:
    def __init__(
        self,
        name: str,
        git_url: str,
        path: str = "",
        ssh_config: str = "",
        job_script: str | None = None,
        pre_script: str | None = None,
        branch: str = "",
        cleanup: bool = False,
        artifacts: list[str] | None = None,
        active_jobs: list[str] | None = None,
        state: State = State.PENDING,
        partition: str = "",
        cpus: str = "",
        gpus: str = "",
        memory: str = "",
        time: str = "",
        nodelist: str = "",
    ) -> None:
        self.name = name
        self.ssh_config = ssh_config
        self.git_url = git_url
        self.branch = branch
        self.path = path
        self.job_script = job_script
        self.pre_script = pre_script
        self.cleanup_git = cleanup
        self.status = state
        self.jobs_ids: list[str] = active_jobs if active_jobs is not None else []
        self.artifacts: list[str] = artifacts if artifacts is not None else []
        self.partition = partition
        self.cpus = cpus
        self.gpus = gpus
        self.memory = memory
        self.time = time
        self.nodelist = nodelist

    @property
    def _git_name(self) -> str:
        return self.git_url.split("/")[-1].replace(".git", "")

    @property
    def _artifact_dir(self) -> str:
        return f"{self._git_name}/{self.path}"

    def getStatus(self) -> State:
        return self.status

    def __repr__(self) -> str:
        return f"Task(name={self.name}, git_url={self.git_url}, path={self.path}, ssh_config={self.ssh_config}, job={self.job_script}, pre={self.pre_script}, branch={self.branch}, cleanup_git={self.cleanup_git}, artifacts={self.artifacts}, partition={self.partition}, cpus={self.cpus}, gpus={self.gpus}, memory={self.memory}, time={self.time}, nodelist={self.nodelist})"

