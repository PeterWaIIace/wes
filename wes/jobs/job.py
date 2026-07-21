from __future__ import annotations

from dataclasses import dataclass, field


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
