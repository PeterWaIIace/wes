from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path

from wes.remote.runner import SshRunner
from wes.states import State
from wes.tasks.tasks import Task


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
        result = self.ssh.scp_to(self.r_path, self.h_path + "/" + self.h_name)
        print(f"Copying {self.h_path}/{self.h_name} to {self.r_path} result: {result}")

    def sync(self):
        print("SSHItem.sync()", self.r_path, self.r_name, "->", self.h_path, self.h_name)
        ok = self.ssh.scp_from(self.r_path, self.r_name, self.h_path + "/" + self.h_name, r=True)
        if not ok:
            print(f"  ✗ rsync failed: {self.ssh.ssh_config}:{self.r_path}/{self.r_name} -> {self.h_path}/{self.h_name}")


class JobConfig(SshItem):
    def __init__(self, job: Job, task: Task, r_path: str, ssh_config: str):
        self.task = task
        self.job = job
        self.h_path = f"results/{self.job.job_name}/{self.task.name}_config.json"
        self._save_job_config_json()
        super().__init__(str(self.h_path), r_path, ssh_config)

    def _save_job_config_json(self):
        config = {
            "job": {
                "namespace": self.job.namespace,
                "job_name": self.job.job_name,
                "ssh_config": self.job.ssh_config,
            },
            "task": {
                "name": self.task.name,
                "git_url": self.task.git_url,
                "path": self.task.path,
                "ssh_config": self.task.ssh_config,
                "job_script": self.task.job_script,
                "pre_script": self.task.pre_script,
                "branch": self.task.branch,
                "cleanup": self.task.cleanup_git,
                "artifacts": self.task.artifacts,
                "partition": self.task.partition,
                "cpus": self.task.cpus,
                "gpus": self.task.gpus,
                "memory": self.task.memory,
                "time": self.task.time,
                "nodelist": self.task.nodelist,
            },
        }

        Path(self.h_path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.h_path, 'w') as f:
            json.dump(config, f, indent=4)


class ClientItem:
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

        ok, result = self.ssh.run_command(cmd)
        return ok, result


class Job:
    def __init__(self, task: Task, ssh_config: str, namespace: str | None = None):
        self.ssh_config = ssh_config

        self.task = task
        self.namespace = namespace or secrets.token_urlsafe(8)
        self.job_name = f"{self.task.name}_{self.namespace}"

        self.job_dir = self.task.name + "/" + self.namespace
        self.repo_dir = self.job_dir + "/" + self.task.git_url.split("/")[-1].split(".")[0]

        self.artifacts = []
        self.script = None
        self.pre_script = None

        self.job_ssh_client = ClientSsh(self.job_dir, ssh_config)

        self._setup_artifacts()
        self._setup_scripts()
        self._setup_pre_script()
        self._setup_job_config()

        self.info = None # lazy init

    def set_info(self, job_info: JobInfo):
        self.info = job_info

    def _setup_artifacts(self):
        self.artifacts = []
        for path in self.task.artifacts:
            h_path = f"results/{self.repo_dir}/{path}"
            Path(h_path).parent.mkdir(parents=True, exist_ok=True)
            r_path = f"{self.repo_dir}/{path}"
            self.artifacts.append(SshItem(h_path=h_path, r_path=r_path, ssh_config=self.ssh_config))
        
        for log_name in ("job_output.txt", "job_error.txt"):
            h_path = f"results/{self.job_dir}/{log_name}"
            Path(h_path).parent.mkdir(parents=True, exist_ok=True)
            r_path = f"{self.job_dir}/{log_name}"
            self.artifacts.append(SshItem(h_path=h_path, r_path=r_path, ssh_config=self.ssh_config))

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

    def _setup_pre_script(self):
        if not self.task.pre_script:
            return
        pre_script = self.task.pre_script.split("/")[-1]
        r_path = f"{self.job_dir}/{pre_script}"
        h_path = f"{self.task.pre_script}"
        print(f"Setting up pre-script: {h_path} to {r_path}")
        self.pre_script = SshItem(
            h_path=h_path,
            r_path=r_path,
            ssh_config=self.ssh_config
        )

    def _setup_job_config(self):
        print(f"{self.job_dir}/{self.task.name}_config.json")
        self.job_conf = JobConfig(self, self.task, f"{self.job_dir}/{self.task.name}_config.json", self.ssh_config)
        self.job_conf.copy()

    def sync(self) -> None:
        for artifact in self.artifacts:
            artifact.sync()

    def cleanup(self) -> None:
        self.job_ssh_client.cmd(f"rm -rf {self.job_dir}")

    def upload_scripts(self) -> None:
        print("====> Uploading scripts for job:", self.job_name)
        self.script.copy()
        if self.pre_script:
            self.pre_script.copy()

    def _clone_repo(self) -> bool:
        git_name = self.task.git_url.split("/")[-1].replace(".git", "")
        if self.task.branch:
            clone_cmd = f"git clone -b {self.task.branch} {self.task.git_url} {git_name}"
        else:
            clone_cmd = f"git clone {self.task.git_url} {git_name}"
        ok, result = self.job_ssh_client.cmd(clone_cmd)
        if not ok:
            print(f"Clone failed: {result}")
        return ok

    def execute_job(self) -> State:
        if not self._clone_repo():
            return State.FAILED

        if self.pre_script:
            ok, result = self.job_ssh_client.cmd(f"ls .")
            ok, result = self.job_ssh_client.cmd(f"./{self.pre_script.r_name}")
            print(f"Pre-script output:\n{result}")
            if not ok:
                print(f"Pre-script failed: {result}")
                return State.FAILED

        job_path = self.script.r_path
        sbatch_cmd = f"sbatch --parsable --job-name={self.job_name}"
        sbatch_cmd += f" ./{self.script.r_name}"

        ok, result = self.job_ssh_client.cmd(sbatch_cmd)