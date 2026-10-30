from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from wes.remote.runner import SshRunner
from wes.states import State

STATUS_FILENAME = "wes.status"


_SLURM_STATES = {
    "PENDING": State.PENDING,
    "CONFIGURING": State.PENDING,
    "REQUEUED": State.PENDING,
    "RESIZING": State.PENDING,
    "SUSPENDED": State.PENDING,
    "RUNNING": State.RUNNING,
    "COMPLETING": State.RUNNING,
    "STAGE_OUT": State.RUNNING,
    "COMPLETED": State.COMPLETED,
    "FAILED": State.FAILED,
    "TIMEOUT": State.FAILED,
    "OUT_OF_MEMORY": State.FAILED,
    "NODE_FAIL": State.FAILED,
    "BOOT_FAIL": State.FAILED,
    "DEADLINE": State.FAILED,
    "REVOKED": State.FAILED,
    "CANCELLED": State.CANCELLED,
    "PREEMPTED": State.CANCELLED,
    "SPECIAL_EXIT": State.FAILED,
}


def slurm_state(raw: str) -> State:
    """Map a SLURM job state (e.g. ``CANCELLED by 1000``) to a WES state."""
    name = (raw or "").strip().split(" ")[0].split("+")[0].upper()
    return _SLURM_STATES.get(name, State.PENDING)


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class JobStatus:
    """Plain key=value status of a single scheduled task, kept on the server."""

    task: str
    namespace: str
    job_name: str
    ssh: str
    state: State = State.PENDING
    job_id: str = ""
    node: str = ""
    partition: str = ""
    updated: str = ""
    message: str = ""

    def to_text(self) -> str:
        lines = [
            f"task={self.task}",
            f"namespace={self.namespace}",
            f"job_name={self.job_name}",
            f"ssh={self.ssh}",
            f"state={self.state.value}",
            f"updated={self.updated}",
        ]
        for key in ("job_id", "node", "partition", "message"):
            value = getattr(self, key)
            if value:
                lines.append(f"{key}={value}")
        return "\n".join(lines) + "\n"

    @classmethod
    def from_text(cls, text: str) -> JobStatus:
        data: dict[str, str] = {}
        for line in (text or "").splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            key, _, value = line.partition("=")
            data[key.strip()] = value.strip()
        try:
            state = State(data.get("state", State.PENDING.value))
        except ValueError:
            state = State.PENDING
        return cls(
            task=data.get("task", ""),
            namespace=data.get("namespace", ""),
            job_name=data.get("job_name", ""),
            ssh=data.get("ssh", ""),
            state=state,
            job_id=data.get("job_id", ""),
            node=data.get("node", ""),
            partition=data.get("partition", ""),
            updated=data.get("updated", ""),
            message=data.get("message", ""),
        )


class StatusFile:
    """Reads and writes ``wes.status`` inside a remote job directory."""

    def __init__(self, job_dir: str, ssh_config: str) -> None:
        self.job_dir = job_dir
        self.ssh_config = ssh_config
        self.runner = SshRunner(ssh_config)

    @property
    def path(self) -> str:
        return f"{self.job_dir}/{STATUS_FILENAME}"

    def write(self, status: JobStatus) -> bool:
        tmp = f"{STATUS_FILENAME}.tmp"
        cmd = f"cd {self.job_dir} && cat > {tmp} && mv {tmp} {STATUS_FILENAME}"
        ok, _ = self.runner.run_command(cmd, script=status.to_text())
        if not ok:
            print(f"  ✗ could not write {self.path}")
        return ok

    def read(self) -> JobStatus | None:
        ok, lines = self.runner.run_command(f"cd {self.job_dir} && cat {STATUS_FILENAME}")
        if not ok or not lines:
            return None
        return JobStatus.from_text("\n".join(lines))
