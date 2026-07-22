
from __future__ import annotations

import re
import subprocess
import sys
import uuid
from pathlib import Path
from shutil import get_terminal_size

from .states import State

SEP = "─"
_ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x1b]*\x1b\\")


def _strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def _sep(label: str = "") -> str:
    w = get_terminal_size().columns
    if label:
        left = f" {label} "
        right = SEP * (w - len(left) - 2)
        return f" {left}{right}"
    return SEP * w

class TaskParams:
    def __init__(
        self,
        name: str,
        git_url: str,
        path: str,
        run: list[str] | None = None,
        post: str = "",
        ssh_config: str = "",
        job: str | None = None,
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
        run_id: str = "",
    ) -> None:
        self.name = name
        self.ssh_config = ssh_config
        self.git_url = git_url
        self.branch = branch
        self.path = path
        self.job = job
        self.run = run if run is not None else []
        self.post = post
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
        self.run_id = run_id or f"{name}-{uuid.uuid4().hex[:8]}"
