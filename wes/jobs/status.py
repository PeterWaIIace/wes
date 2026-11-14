from __future__ import annotations

import shlex
from dataclasses import dataclass
from datetime import datetime

import yaml

from wes.jobs.status_sh_scripts import (
    JOB_STATUS_SNIPPET,
    PRE_STATUS_SNIPPET,
    STATUS_FILENAME,
    STATUS_HELPER_NAME,
    STATUS_HELPER_SCRIPT,
)
from wes.remote.runner import SshRunner
from wes.states import State


def inject_job_status(script_text: str) -> str:
    """Insert the wes status block into a SLURM job script.

    The block lands after the leading comment/#SBATCH header and before the
    first executable line, so sbatch still parses every #SBATCH directive.
    Idempotent: a script already calling wes_status.sh is returned unchanged.
    """
    if STATUS_HELPER_NAME in script_text:
        return script_text
    lines = script_text.splitlines(keepends=True)
    at = len(lines)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            at = i
            break
    head, tail = "".join(lines[:at]), "".join(lines[at:])
    if head and not head.endswith("\n"):
        head += "\n"
    return f"{head}\n{JOB_STATUS_SNIPPET}\n{tail}"


def inject_pre_status(script_text: str) -> str:
    """Prepend the status-file creation to a pre script (after the shebang).

    Idempotent: a script already calling wes_status.sh is returned unchanged.
    """
    if STATUS_HELPER_NAME in script_text:
        return script_text
    lines = script_text.splitlines(keepends=True)
    at = 1 if lines and lines[0].startswith("#!") else 0
    head, tail = "".join(lines[:at]), "".join(lines[at:])
    return f"{head}{PRE_STATUS_SNIPPET}\n{tail}"


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


def _parse_key_value(text: str) -> dict[str, str]:
    """Parse the legacy ``key=value`` wes.status format (pre-YAML files)."""
    data: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip()
    return data


@dataclass
class JobStatus:
    """YAML status of a single scheduled task, kept on the server as wes.status."""

    task: str
    namespace: str
    job_name: str
    ssh: str
    wes_file: str = ""
    state: State = State.PENDING
    job_id: str = ""
    parent_namespace: str = ""
    array_index: str = ""
    node: str = ""
    partition: str = ""
    updated: str = ""
    message: str = ""

    def to_text(self) -> str:
        data = {
            "task": self.task,
            "namespace": self.namespace,
            "job_name": self.job_name,
            "ssh": self.ssh,
            "state": self.state.value,
            "updated": self.updated,
        }
        for key in (
            "wes_file",
            "job_id",
            "parent_namespace",
            "array_index",
            "node",
            "partition",
            "message",
        ):
            value = getattr(self, key)
            if value:
                data[key] = value
        return yaml.safe_dump(data, sort_keys=False)

    @classmethod
    def from_text(cls, text: str) -> JobStatus:
        data = yaml.safe_load(text or "")
        if not isinstance(data, dict):
            # not YAML (empty file or legacy key=value) - fall back to key=value
            data = _parse_key_value(text or "")
        try:
            state = State(str(data.get("state") or State.PENDING.value))
        except ValueError:
            state = State.PENDING
        return cls(
            task=str(data.get("task") or ""),
            namespace=str(data.get("namespace") or ""),
            job_name=str(data.get("job_name") or ""),
            ssh=str(data.get("ssh") or ""),
            wes_file=str(data.get("wes_file") or ""),
            state=state,
            job_id=str(data.get("job_id") or ""),
            parent_namespace=str(data.get("parent_namespace") or ""),
            array_index=str(data.get("array_index") or ""),
            node=str(data.get("node") or ""),
            partition=str(data.get("partition") or ""),
            updated=str(data.get("updated") or ""),
            message=str(data.get("message") or ""),
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

    def write_helper(self) -> bool:
        """Upload the ``wes_status.sh`` helper into the remote job directory."""
        tmp = f"{STATUS_HELPER_NAME}.tmp"
        cmd = (
            f"cd {self.job_dir} && cat > {tmp} && mv {tmp} {STATUS_HELPER_NAME} "
            f"&& chmod +x {STATUS_HELPER_NAME}"
        )
        ok, _ = self.runner.run_command(cmd, script=STATUS_HELPER_SCRIPT)
        if not ok:
            print(f"  ✗ could not write {self.job_dir}/{STATUS_HELPER_NAME}")
        return ok

    def read(self) -> JobStatus | None:
        ok, lines = self.runner.run_command(f"cd {self.job_dir} && cat {STATUS_FILENAME}")
        if not ok or not lines:
            return None
        return JobStatus.from_text("\n".join(lines))

    def job_dir_exists(self) -> bool | None:
        """Whether the remote job dir exists.

        Returns None when the server could not be reached (ssh failure), so
        callers do not prune live jobs on a transient network error.
        """
        ok, lines = self.runner.run_command(
            f"if [ -d {shlex.quote(self.job_dir)} ]; then echo yes; else echo no; fi",
            quiet=True,
        )
        if not ok:
            return None
        return bool(lines and lines[0].strip() == "yes")
