from __future__ import annotations

from pydantic import BaseModel


class TaskSummary(BaseModel):
    name: str
    status: str
    git_url: str
    branch: str
    ssh: str
    job_ids: list[str]
    job: str | None = None
    artifacts: list[str] = []


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


class RunRequest(BaseModel):
    config: str


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
