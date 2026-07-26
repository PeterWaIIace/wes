from __future__ import annotations

import re
import uuid

from .states import State

_ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x1b]*\x1b\\")

class Task:
    def __init__(
        self,
        name: str,
        git_url: str,
        path: str = "",
        ssh_config: str = "",
        job_script: str | None = None,
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
        return f"Task(name={self.name}, git_url={self.git_url}, path={self.path}, ssh_config={self.ssh_config}, job={self.job_script}, branch={self.branch}, cleanup_git={self.cleanup_git}, artifacts={self.artifacts}, partition={self.partition}, cpus={self.cpus}, gpus={self.gpus}, memory={self.memory}, time={self.time}, nodelist={self.nodelist})"


# I am not sure if I like this task manager class 
class TaskManager:
    def __init__(self, tasks: list[Task] | dict[str, Task] | None = None) -> None:
        if tasks is None:
            self.tasks: dict[str, Task] = {}
        elif isinstance(tasks, dict):
            self.tasks = tasks
        else:
            self.tasks = {task.name: task for task in tasks}
        self.creating_cb = lambda task: State.PENDING
        self.pending_cb = lambda task: State.RUNNING
        self.running_cb = lambda task: task.getStatus()
        self.completed_cb = lambda task: State.COMPLETED
        self.failing_cb = lambda task: State.FAILED

    def add_create_cb(self, callback) -> None:
        self.creating_cb = callback

    def add_pending_cb(self, callback) -> None:
        self.pending_cb = callback

    def add_running_cb(self, callback) -> None:
        self.running_cb = callback

    def add_completed_cb(self, callback) -> None:
        self.completed_cb = callback

    def add_failing_cb(self, callback) -> None:
        self.failing_cb = callback

    def _transition(self, task: Task) -> None:
        status = task.getStatus()
        if status == State.PENDING:
            result = self.creating_cb(task)
            if result == State.FAILED:
                task.status = State.FAILED
                self.failing_cb(task)
                return
            task.status = self.pending_cb(task)
            if task.status == State.FAILED:
                self.failing_cb(task)
        elif status == State.RUNNING:
            task.status = self.running_cb(task)
        elif status == State.COMPLETED:
            task.status = self.completed_cb(task)
        elif status == State.FAILED:
            self.failing_cb(task)

    def check(self, name: str | None = None):
        if name is not None:
            task = self.tasks.get(name)
            if task:
                self._transition(task)
        else:
            for task in self.tasks.values():
                self._transition(task)
