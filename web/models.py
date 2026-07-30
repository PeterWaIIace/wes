from __future__ import annotations

from pydantic import BaseModel


class TaskInfo(BaseModel):
    name: str
    git_url: str
    branch: str = ""
    ssh: str = ""
    job: str = ""
    path: str = "."
    run: list[str] = []
    pre: str = ""
    post: str = ""
    artifacts: list[str] = []
    cleanup: bool = False
    partition: str = ""
    cpus: str = ""
    gpus: str = ""
    memory: str = ""
    time: str = ""
    nodelist: str = ""
    status: str = ""
    run_id: str = ""


class JobSummary(BaseModel):
    job_id: str
    task_name: str
    state: str
    run_id: str = ""
    jobs_ids: list[str] = []
    git_url: str = ""
    branch: str = ""
    ssh: str = ""
    job: str = ""
    partition: str = ""
    cpus: str = ""
    gpus: str = ""
    memory: str = ""
    time: str = ""
    nodelist: str = ""
    priority: str = ""


class CreateTaskRequest(BaseModel):
    name: str
    git_url: str = ""
    branch: str = ""
    ssh: str = ""
    job: str = ""
    partition: str = ""
    cpus: str = ""
    gpus: str = ""
    memory: str = ""
    time: str = ""
    nodelist: str = ""


class LogData(BaseModel):
    stdout: str = ""
    stderr: str = ""
    pre_run: str = ""


class ArtifactEntry(BaseModel):
    name: str
    kind: str
    path: str
    size: int


class ProgressData(BaseModel):
    columns: list[str] = []
    rows: list[list[str]] = []


class NodeInfo(BaseModel):
    name: str
    partition: str
    state: str
    cpus: str
    gpus: str
    memory: str
    reason: str = ""


class ClusterData(BaseModel):
    ssh: str
    nodes: list[NodeInfo] = []
    error: str = ""


class SettingsData(BaseModel):
    ssh_hosts: list[str] = []
    form_history: dict[str, list[str]] = {}
    query_interval: int = 10
