from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field


@dataclass
class NodeInfo:
    name: str
    partition: str
    state: str
    cpus: str
    gpus: str
    memory: str
    reason: str = ""


@dataclass
class NodeCapacity:
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


@dataclass
class JobInfo:
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


@dataclass
class SlurmJob:
    """SLURM job specification for generating sbatch scripts and commands."""

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
    env_vars: dict[str, str] = field(default_factory=dict)
    command: str = ""
    script_path: str = ""

    def sbatch_directives(self) -> str:
        """Generate #SBATCH directive lines."""
        lines: list[str] = []
        d = {
            "--job-name": self.name,
            "--partition": self.partition,
            "--nodes": self.nodes if self.nodes else None,
            "--ntasks": self.ntasks if self.ntasks else None,
            "--cpus-per-task": self.cpus_per_task if self.cpus_per_task else None,
            "--gres": self.gres or None,
            "--mem": self.memory or None,
            "--time": self.time or None,
            "--nodelist": self.nodelist or None,
            "--output": self.output or None,
            "--error": self.error or None,
            "--mail-user": self.email or None,
            "--mail-type": self.mail_type or None,
            "--account": self.account or None,
            "--qos": self.qos or None,
            "--workdir": self.workdir or None,
        }
        for key, val in d.items():
            if val is not None and val != "" and val != 0:
                lines.append(f"#SBATCH {key}={val}")
        return "\n".join(lines)

    def to_script(self) -> str:
        """Generate a complete sbatch shell script."""
        parts: list[str] = ["#!/bin/bash"]
        directives = self.sbatch_directives()
        if directives:
            parts.append(directives)
        if self.env_vars:
            for k, v in self.env_vars.items():
                parts.append(f"export {k}={v}")
        if self.script_path:
            parts.append(f"\nsource {self.script_path}")
        if self.command:
            parts.append(f"\n{self.command}")
        return "\n".join(parts) + "\n"

    def sbatch_args(self) -> list[str]:
        """Generate sbatch CLI arguments (without 'sbatch' itself)."""
        args: list[str] = []
        if self.name:
            args += ["--job-name", self.name]
        if self.partition:
            args += ["--partition", self.partition]
        if self.nodes:
            args += ["--nodes", str(self.nodes)]
        if self.ntasks:
            args += ["--ntasks", str(self.ntasks)]
        if self.cpus_per_task:
            args += ["--cpus-per-task", str(self.cpus_per_task)]
        if self.gres:
            args += ["--gres", self.gres]
        if self.memory:
            args += ["--mem", self.memory]
        if self.time:
            args += ["--time", self.time]
        if self.nodelist:
            args += ["--nodelist", self.nodelist]
        if self.output:
            args += ["--output", self.output]
        if self.error:
            args += ["--error", self.error]
        if self.email:
            args += ["--mail-user", self.email]
        if self.mail_type:
            args += ["--mail-type", self.mail_type]
        if self.account:
            args += ["--account", self.account]
        if self.qos:
            args += ["--qos", self.qos]
        if self.workdir:
            args += ["--workdir", self.workdir]
        for k, v in self.env_vars.items():
            args += ["--export", f"{k}={v}"]
        return args

    def to_dict(self) -> dict[str, str | int | dict[str, str]]:
        """Serialize to a plain dict."""
        return {
            "name": self.name,
            "partition": self.partition,
            "nodes": self.nodes,
            "ntasks": self.ntasks,
            "cpus_per_task": self.cpus_per_task,
            "gres": self.gres,
            "memory": self.memory,
            "time": self.time,
            "nodelist": self.nodelist,
            "output": self.output,
            "error": self.error,
            "email": self.email,
            "mail_type": self.mail_type,
            "account": self.account,
            "qos": self.qos,
            "workdir": self.workdir,
            "env_vars": self.env_vars,
            "command": self.command,
            "script_path": self.script_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str | int | dict[str, str]]) -> SlurmJob:
        """Construct from a dict (e.g. parsed JSON/YAML)."""
        return cls(
            name=str(data.get("name", "wes_job")),
            partition=str(data.get("partition", "")),
            nodes=int(data.get("nodes", 1)),
            ntasks=int(data.get("ntasks", 1)),
            cpus_per_task=int(data.get("cpus_per_task", 1)),
            gres=str(data.get("gres", "")),
            memory=str(data.get("memory", "")),
            time=str(data.get("time", "")),
            nodelist=str(data.get("nodelist", "")),
            output=str(data.get("output", "")),
            error=str(data.get("error", "")),
            email=str(data.get("email", "")),
            mail_type=str(data.get("mail_type", "")),
            account=str(data.get("account", "")),
            qos=str(data.get("qos", "")),
            workdir=str(data.get("workdir", "")),
            env_vars=dict(data.get("env_vars", {})),
            command=str(data.get("command", "")),
            script_path=str(data.get("script_path", "")),
        )


def _ssh_run(ssh_config: str, cmd: str) -> list[str]:
    """Run a command via SSH and return non-header lines."""
    result = subprocess.run(
        ["ssh", ssh_config, cmd],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [
        line
        for line in result.stdout.strip().splitlines()
        if line.strip() and not line.startswith("JOBID")
    ]


def get_jobs(ssh_config: str) -> list[JobInfo]:
    """Query running/pending SLURM jobs via squeue.

    Args:
        ssh_config: SSH host/config name.

    Returns:
        List of JobInfo with job_id, user, name, state, time, nodes,
        partition, reason, cpus, memory.
    """
    fmt = "%i|%u|%j|%T|%M|%N|%P|%R|%C|%m"
    lines = _ssh_run(ssh_config, f"squeue -o '{fmt}'")

    jobs: list[JobInfo] = []
    for line in lines:
        parts = line.split("|")
        if len(parts) < 10:
            continue
        jobs.append(
            JobInfo(
                job_id=parts[0].strip(),
                user=parts[1].strip(),
                name=parts[2].strip(),
                state=parts[3].strip(),
                time=parts[4].strip(),
                nodes=parts[5].strip(),
                partition=parts[6].strip(),
                reason=parts[7].strip(),
                cpus=parts[8].strip(),
                memory=parts[9].strip(),
            )
        )
    return jobs


def get_nodes(ssh_config: str) -> list[NodeInfo]:
    """Query SLURM node availability via SSH.

    Uses sinfo with explicit format to get clean, parseable output:
      name | partition | state | cpus(alloc/idle/total) | gres | memory | reason

    Args:
        ssh_config: SSH host/config name (e.g. "hpc" or "~/.ssh/config entry")

    Returns:
        List of NodeInfo with name, partition, state, cpus, gpus, memory, reason.
    """
    fmt = "%N|%P|%T|%C|%G|%m|%R"
    lines = _ssh_run(ssh_config, f"sinfo -N -o '{fmt}'")

    nodes: list[NodeInfo] = []
    for line in lines:
        parts = line.split("|")
        if len(parts) < 6:
            continue
        name = parts[0].strip()
        partition = parts[1].strip().rstrip("*")
        state = parts[2].strip()
        cpus = parts[3].strip()
        gres = parts[4].strip()
        memory = parts[5].strip()
        reason = parts[6].strip() if len(parts) > 6 else ""

        gpu_count = _parse_gpu_count(gres)

        nodes.append(
            NodeInfo(
                name=name,
                partition=partition,
                state=state,
                cpus=cpus,
                gpus=gpu_count,
                memory=f"{memory}M",
                reason=reason,
            )
        )
    return nodes


def _parse_gpu_count(gres: str) -> str:
    """Parse GPU count from GRES string like 'gpu:rtx_2070_super:1' or '(null)'."""
    if not gres or gres == "(null)":
        return "-"
    if "gpu" not in gres.lower():
        return "-"
    parts = gres.split(":")
    # last numeric part is the count
    for p in reversed(parts):
        try:
            return str(int(p))
        except ValueError:
            continue
    return gres


def _parse_scontrol_value(line: str, key: str) -> str:
    """Extract a value from a scontrol one-line output like 'Key=Value'."""
    m = re.search(rf"\b{key}=(\S+)", line)
    return m.group(1) if m else ""


def _parse_gres_alloc(gres: str) -> int:
    """Parse allocated GPUs from GRES like 'gpu:rtx_2070_super:2(IDX:0-1)'."""
    if not gres or gres == "(null)":
        return 0
    # match gpu:type:N or gpu:N where N is total
    m = re.search(r"gpu:\w+:(\d+)", gres)
    if not m:
        m = re.search(r"gpu:(\d+)", gres)
    if not m:
        return 0
    # allocated = total - count of free indices
    idx_match = re.search(r"IDX:([\d,-]+)", gres)
    if idx_match:
        allocated = 0
        for part in idx_match.group(1).split(","):
            if "-" in part:
                lo, hi = part.split("-", 1)
                allocated += int(hi) - int(lo) + 1
            else:
                allocated += 1
        return allocated
    # no IDX info, use node state to estimate
    return 0


def get_capacity(ssh_config: str) -> list[NodeCapacity]:
    """Query per-node CPU/GPU/memory capacity via scontrol.

    Uses 'scontrol show node -o' which outputs one node per line with
    key=value pairs like:
        NodeName=node1 CPUAlloc=16 CPULoad=16.00 RealMemory=128000
        AllocMem=128000 FreeMem=0 Gres=gpu:rtx_2070_super:2(IDX:0-1)

    Args:
        ssh_config: SSH host/config name.

    Returns:
        List of NodeCapacity with alloc/free breakdowns.
    """
    result = subprocess.run(
        ["ssh", ssh_config, "scontrol show node -o"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []

    nodes: list[NodeCapacity] = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line or not line.startswith("NodeName="):
            continue

        name = _parse_scontrol_value(line, "NodeName")
        if not name:
            continue

        cpu_total = _parse_int(_parse_scontrol_value(line, "Cpus"), 0)
        # try CPUSockets * CoresPerSocket as fallback
        if cpu_total == 0:
            sockets = _parse_int(_parse_scontrol_value(line, "Sockets"), 0)
            cores = _parse_int(_parse_scontrol_value(line, "CoresPerSocket"), 0)
            cpu_total = sockets * cores

        cpu_alloc = _parse_int(_parse_scontrol_value(line, "CPUAlloc"), 0)
        cpu_free = max(cpu_total - cpu_alloc, 0)

        mem_total = _parse_int(_parse_scontrol_value(line, "RealMemory"), 0)
        mem_alloc = _parse_int(_parse_scontrol_value(line, "AllocMem"), 0)
        mem_free_str = _parse_scontrol_value(line, "FreeMem")
        mem_free = _parse_int(mem_free_str, max(mem_total - mem_alloc, 0))

        gres = _parse_scontrol_value(line, "Gres")
        gpu_total = _parse_int(_parse_gpu_count(gres), 0)
        gpu_alloc = _parse_gres_alloc(gres) if gres else 0
        gpu_free = max(gpu_total - gpu_alloc, 0)

        nodes.append(
            NodeCapacity(
                name=name,
                cpu_total=cpu_total,
                cpu_alloc=cpu_alloc,
                cpu_free=cpu_free,
                mem_total_mb=mem_total,
                mem_alloc_mb=mem_alloc,
                mem_free_mb=mem_free,
                gpu_total=gpu_total,
                gpu_alloc=gpu_alloc,
                gpu_free=gpu_free,
            )
        )
    return nodes


def _parse_int(s: str, default: int) -> int:
    try:
        return int(s)
    except (ValueError, TypeError):
        return default
