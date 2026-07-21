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


class JobInfo(BaseModel):
    job_id: str
    user: str
    name: str
    state: str
    time: str
    nodes: str
    partition: str
    reason: str
    cpus: str
    memory: str


class JobsData(BaseModel):
    ssh: str
    jobs: list[JobInfo] = []
    error: str = ""


class NodeCapacity(BaseModel):
    name: str
    cpu_total: int
    cpu_alloc: int
    cpu_free: int
    mem_total_mb: int
    mem_alloc_mb: int
    mem_free_mb: int
    gpu_total: int
    gpu_alloc: int
    gpu_free: int


class CapacityData(BaseModel):
    ssh: str
    nodes: list[NodeCapacity] = []
    error: str = ""


class SlurmJobSpec(BaseModel):
    name: str = "wes_job"
    partition: str = ""
    nodes: int = 1
    ntasks: int = 1
    cpus_per_task: int = 1
    gres: str = ""
    memory: str = ""
    time: str = ""
    nodelist: str = ""
    output: str = ""
    error: str = ""
    email: str = ""
    mail_type: str = ""
    account: str = ""
    qos: str = ""
    workdir: str = ""
    env_vars: dict[str, str] = {}
    command: str = ""
    script_path: str = ""


class SlurmJobResponse(BaseModel):
    script: str
    args: list[str]


class TaskConfig(BaseModel):
    name: str
    git_url: str
    branch: str = ""
    ssh: str
    job: str
    partition: str = ""
    cpus: str = ""
    gpus: str = ""
    memory: str = ""
    time: str = ""
    nodelist: str = ""


class SubmitRequest(BaseModel):
    name: str
    overrides: dict[str, str] = {}


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


class SettingsData(BaseModel):
    ssh_hosts: list[str] = []
    form_history: dict[str, list[str]] = {}
