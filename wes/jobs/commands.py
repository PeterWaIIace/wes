"""Remote shell commands rendered as strings for SshRunner/ClientSsh.

Each Command subclass builds one command that runs on the ssh host
(e.g. hpc); ``string()`` returns the exact shell line.
"""

from __future__ import annotations

import shlex


class Command:
    """A remote shell command; string() renders what runs on the ssh host."""

    def string(self) -> str:
        raise NotImplementedError("string() must be implemented in subclasses")


class GitCloneCommand(Command):

    def _set_ssh_host_file_to_null(self):
        return "-o UserKnownHostsFile=/dev/null"

    def _do_not_ask_host(self):
        return "-o StrictHostKeyChecking=no"

    def __init__(self, name, url, branch=None):
        self.url = url
        self.name = name
        self.branch = branch
        self.ssh_opts = f"{self._do_not_ask_host()} {self._set_ssh_host_file_to_null()}"

    def string(self) -> str:
        git_ssh = f"GIT_SSH_COMMAND='ssh {self.ssh_opts}'"
        if self.branch:
            return f"{git_ssh} git clone -b {self.branch} {self.url} {self.name}"
        return f"{git_ssh} git clone {self.url} {self.name}"


class SbatchCommand(Command):
    """sbatch with the resource flags taken from the .wes task fields."""

    def __init__(
        self,
        job_name: str,
        script: str,
        partition: str = "",
        cpus: str = "",
        gpus: str = "",
        memory: str = "",
        time: str = "",
        nodelist: str = "",
    ):
        self.job_name = job_name
        self.script = script
        self.partition = partition
        self.cpus = cpus
        self.gpus = gpus
        self.memory = memory
        self.time = time
        self.nodelist = nodelist

    def string(self) -> str:
        cmd = f"sbatch --parsable --job-name={self.job_name}"
        if self.partition:
            cmd += f" --partition={self.partition}"
        if self.cpus:
            cmd += f" --cpus-per-task={self.cpus}"
        if self.gpus:
            cmd += f" --gpus={self.gpus}"
        if self.memory:
            cmd += f" --mem={self.memory}"
        if self.time:
            cmd += f" --time={self.time}"
        if self.nodelist:
            cmd += f" --nodelist={self.nodelist}"
        return cmd + f" ./{self.script}"


class RemoveDirCommand(Command):
    def __init__(self, path: str):
        self.path = path

    def string(self) -> str:
        return f"rm -rf {shlex.quote(self.path)}"


class RunScriptCommand(Command):
    def __init__(self, name: str):
        self.name = name

    def string(self) -> str:
        return f"./{self.name}"
