from __future__ import annotations

from tasks.tasks import Task
from dataclasses import dataclass

from pathlib import Path

from wes.states import State
from wes.remote.runner import SshRunner

import secrets

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

class MirrorItem:
    def __init__(self, h_path: str, r_path: str):
        self.h_path = "/".join(h_path.split("/")[:-1])
        self.r_path = "/".join(r_path.split("/")[:-1])
        self.h_name = h_path.split("/")[-1]
        self.r_name = r_path.split("/")[-1]

    def copy(self):
        pass

    def sync(self):
        pass

class SshItem(MirrorItem):

    def __init__(self, h_path: str, r_path: str, ssh_config: str):
        self.ssh = SshRunner(ssh_config)
        super().__init__(h_path, r_path)

    def copy(self):
        self.ssh.scp_to(self.r_path, self.h_path + "/" + self.h_name)

    def sync(self):
        self.ssh.scp_from(self.r_path, self.r_name, self.h_path + "/" + self.h_name, r=True)


class ClientItem():
    def __init__(self, job_path: str):
        self.job_path = job_path

    def cmd(self):
        raise NotImplementedError("cmd() must be implemented in subclasses")

class ClientSsh(ClientItem):

    def __init__(self, job_path: str, ssh_config: str):
        self.ssh = SshRunner(ssh_config)
        self.ssh.create_dir(job_path)
        super().__init__(job_path)

    def cmd(self, cmd):
        if self.job_path:
            cmd = f"cd {self.job_path} && {cmd}"

        print(f"executing cmd: {cmd}")
        ok, result = self.ssh.run_command(cmd)
        return ok, result

class Job:
    def __init__(self, task: Task, ssh_config: str):
        self.ssh_config = ssh_config

        self.task = task 
        self.namespace = secrets.token_urlsafe(8)
        self.job_name = f"{self.task.name}_{self.namespace}"

        self.job_dir = self.task.name + "/" + self.namespace
        self.repo_dir = self.job_dir + "/" +  self.task.git_url.split("/")[-1].split(".")[0]

        self.artifacts = []
        self.script = None

        self.job_ssh_client = ClientSsh(self.job_dir, ssh_config)

        self._setup_artifacts()
        self._setup_scripts()

    def _setup_artifacts(self):
        self.artifacts = [] 
        for path in self.task.artifacts:
            h_path = f"{self.repo_dir}/{path}"
            r_path = f"results/{self.repo_dir}/{path}"
            self.artifacts.append(
                SshItem(
                    h_path=h_path, 
                    r_path=r_path, 
                    ssh_config=self.ssh_config
                )
            )

    def _setup_scripts(self):
        job_script = self.task.job_script.split("/")[-1]
        r_path = f"{self.job_dir}/{job_script}"
        h_path = f"{self.task.job_script}"
        print(f"Setting up script: {h_path} to {r_path}")
        self.script = SshItem(
            h_path=h_path, #
            r_path=r_path, 
            ssh_config=self.ssh_config
        )

    def sync(self) -> None:
        for artifact in self.artifacts:
            artifact.sync()

    def upload_scripts(self) -> None:
        self.script.copy()

    def execute_job(self) -> State:

        job_path = self.script.r_path
        sbatch_cmd = f"sbatch --parsable --job-name={self.job_name}"
        sbatch_cmd += f" ./{self.script.r_name}"

        print(sbatch_cmd)
        ok, result = self.job_ssh_client.cmd(sbatch_cmd)