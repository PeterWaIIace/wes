from __future__ import annotations

import json
import os
import secrets
import shlex
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from wes.jobs.status import (
    STATUS_FILENAME,
    JobStatus,
    StatusFile,
    inject_job_status,
    inject_pre_status,
    now,
)
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
    priority: str = ""


class MirrorItem:
    def __init__(self, h_path: str, r_path: str):
        self.h_path = "/".join(h_path.split("/")[:-1])
        self.r_path = "/".join(r_path.split("/")[:-1])
        self.h_name = h_path.split("/")[-1]
        self.r_name = r_path.split("/")[-1]

    def copy(self):
        raise NotImplementedError("copy() must be implemented in subclasses")

    def sync(self):
        raise NotImplementedError("sync() must be implemented in subclasses")


class SshItem(MirrorItem):
    def __init__(self, h_path: str, r_path: str, ssh_config: str):
        self.ssh = SshRunner(ssh_config)
        super().__init__(h_path, r_path)

    def copy(self):
        result = self.ssh.scp_to(self.r_path, self.h_path + "/" + self.h_name)
        print(f"Copying {self.h_path}/{self.h_name} to {self.r_path} result: {result}")

    def sync(self):
        print("SSHItem.sync()", self.r_path, self.r_name, "->", self.h_path, self.h_name)
        Path(self.h_path).mkdir(parents=True, exist_ok=True)
        ok = self.ssh.scp_from(self.r_path, self.r_name, self.h_path + "/", r=True)
        if not ok:
            print(
                f"  ✗ rsync failed: "
                f"{self.ssh.ssh_config}:{self.r_path}/{self.r_name}"
                f" -> {self.h_path}/{self.h_name}"
            )

class JobConfig(SshItem):
    def __init__(self, job: Job, task: Task, r_path: str, ssh_config: str):
        self.task = task
        self.job = job
        h_file = f"results/{self.job.job_name}/{self.task.name}_config.json"
        self._save_job_config_json(h_file)
        super().__init__(h_file, r_path, ssh_config)

    def _save_job_config_json(self, h_file: str):
        config = {
            "job": {
                "namespace": self.job.namespace,
                "job_name": self.job.job_name,
                "ssh_config": self.job.ssh_config,
            },
            "task": {
                "name": self.task.name,
                "wes_file": self.task.wes_file,
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

        Path(h_file).parent.mkdir(parents=True, exist_ok=True)
        with open(h_file, "w") as f:
            json.dump(config, f, indent=4)


class ClientItem:
    def __init__(self, job_path: str):
        self.job_path = job_path

    def cmd(self):
        raise NotImplementedError("cmd() must be implemented in subclasses")


class ClientSsh(ClientItem):
    def __init__(self, job_path: str, ssh_config: str):
        self.ssh = SshRunner(ssh_config)
        super().__init__(job_path)

    def cmd(self, cmd, retries: int = 0):
        if self.job_path:
            cmd = f"cd {shlex.quote(self.job_path)} && {cmd}"

        ok, result = self.ssh.run_command(cmd, retries=retries)
        return ok, result


class Job:
    def __init__(self, task: Task, ssh_config: str, namespace: str | None = None):
        self.ssh_config = ssh_config

        self.task = task
        # a namespace passed in (e.g. by JobScanner from the remote config)
        # keeps the job's identity stable across discovery; only generate a
        # fresh one for newly dispatched jobs
        self.namespace = namespace or (
            f"{self.task.name}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(2)}"
        )
        self.job_name = f"{self.task.name}_{self.namespace}"

        self.job_dir = self.task.name + "/" + self.namespace
        self.repo_dir = self.job_dir + "/" + self.task.git_url.split("/")[-1].split(".")[0]

        self.status_files = []
        self.artifacts = []
        self.script = None
        self.pre_script = None

        self.job_ssh_client = ClientSsh(self.job_dir, ssh_config)

        self._setup_artifacts()
        self._setup_scripts()
        self._setup_pre_script()
        self._setup_job_config()

        self.info = None  # lazy init
        self.status = JobStatus(
            task=self.task.name,
            namespace=self.namespace,
            job_name=self.job_name,
            ssh=self.ssh_config,
            wes_file=self.task.wes_file,
        )
        self.status_file = StatusFile(self.job_dir, ssh_config)
        self._status_written = False

    def set_info(self, job_info: JobInfo):
        # SLURM metadata only. The wes.status file on the server is owned by
        # the job's shell scripts (pre.sh/job.sh), not by this poll.
        self.info = job_info

    def pull_status(self) -> bool:
        """Read ``wes.status`` from the server into ``self.status``.

        The file is written by the job's own scripts (via wes_status.sh), so
        it is the source of truth for the job state.
        """
        remote = self.status_file.read()
        if remote is None:
            return False
        self.status = remote
        self._status_written = True
        return True

    def _status_signature(self) -> tuple:
        return (
            self.status.state,
            self.status.job_id,
            self.status.node,
            self.status.partition,
            self.status.message,
        )

    def write_status(
        self,
        state: State,
        message: str = "",
        job_id: str = "",
        node: str = "",
        partition: str = "",
    ) -> bool:
        """Push the current status to ``wes.status`` on the server.

        The remote file is only rewritten when something actually changed.
        """
        previous = self._status_signature()
        if job_id:
            self.status.job_id = job_id
        if node:
            self.status.node = node
        if partition:
            self.status.partition = partition
        self.status.state = state
        self.status.message = message
        self.status.updated = now()

        if self._status_written and self._status_signature() == previous:
            return True

        self._status_written = True
        return self.status_file.write(self.status)

    def _setup_artifacts(self):
        self.artifacts = []
        for path in self.task.artifacts:
            h_path = f"results/{self.repo_dir}/{path}"
            Path(h_path).parent.mkdir(parents=True, exist_ok=True)
            r_path = f"{self.repo_dir}/{path}"
            self.artifacts.append(SshItem(h_path=h_path, r_path=r_path, ssh_config=self.ssh_config))

        for log_name in ("job_output.txt", "job_error.txt", STATUS_FILENAME):
            h_path = f"results/{self.job_dir}/{log_name}"
            Path(h_path).parent.mkdir(parents=True, exist_ok=True)
            r_path = f"{self.job_dir}/{log_name}"
            self.status_files.append(
                SshItem(h_path=h_path, r_path=r_path, ssh_config=self.ssh_config)
            )

    def _setup_scripts(self):
        job_script = self.task.job_script.split("/")[-1]
        r_path = f"{self.job_dir}/{job_script}"
        h_path = f"{self.task.job_script}"
        print(f"Setting up script: {h_path} to {r_path}")
        self.script = SshItem(
            h_path=h_path,  #
            r_path=r_path,
            ssh_config=self.ssh_config,
        )

    def _setup_pre_script(self):
        if not self.task.pre_script:
            return
        pre_script = self.task.pre_script.split("/")[-1]
        r_path = f"{self.job_dir}/{pre_script}"
        h_path = f"{self.task.pre_script}"
        print(f"Setting up pre-script: {h_path} to {r_path}")
        self.pre_script = SshItem(h_path=h_path, r_path=r_path, ssh_config=self.ssh_config)

    def _setup_job_config(self):
        # only builds the local config file; the remote copy happens in
        # upload_scripts() so constructing a Job has no remote side effects
        self.job_conf = JobConfig(
            self, self.task, f"{self.job_dir}/{self.task.name}_config.json", self.ssh_config
        )

    def sync(self) -> None:
        for item in (*self.artifacts, *self.status_files):
            item.sync()

    def cleanup(self) -> None:
        self.job_ssh_client.cmd(f"rm -rf {self.job_dir}")

    def _preprocess(self, item: SshItem, transform: Callable[[str], str], staging_dir: str) -> str:
        """Modify the item's local file content with ``transform`` and stage
        the result in ``staging_dir`` under the original name.

        Returns the staged path for _upload(). The original local file is
        never modified.
        """
        with open(os.path.join(item.h_path, item.h_name), encoding="utf-8") as f:
            content = transform(f.read())
        os.makedirs(staging_dir, exist_ok=True)
        staged = os.path.join(staging_dir, item.h_name)
        with open(staged, "w", encoding="utf-8") as f:
            f.write(content)
        return staged

    def _upload(self, item: SshItem, src: str) -> None:
        """Generic upload: scp local file ``src`` into the item's remote dir,
        keeping its basename."""
        result = item.ssh.scp_to(item.r_path, src)
        print(f"Copying {src} to {item.r_path}/{item.h_name} result: {result}")

    def upload_scripts(self) -> None:
        print("====> Uploading scripts for job:", self.job_name)
        # create the remote job dir and push the config file; kept here so
        # that discovering a Job (JobScanner) never writes to the server
        self.job_ssh_client.ssh.create_dir(self.job_dir)
        self.job_conf.copy()
        # one scratch dir for the staged copies; TemporaryDirectory removes it
        # after the uploads so nothing leaks into /tmp
        with tempfile.TemporaryDirectory(prefix="wes_upload_") as staging:
            for item, transform in (
                (self.script, inject_job_status),
                (self.pre_script, inject_pre_status),
            ):
                if item is None:
                    continue
                self._upload(item, self._preprocess(item, transform, staging))
        # the job's shell scripts create/update wes.status on the server via
        # this helper (pre.sh before submit, job.sh while it runs)
        self.status_file.write_helper()

    def _clone_repo(self) -> bool:
        git_name = self.task.git_url.split("/")[-1].replace(".git", "")
        ssh_opts = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
        if self.task.branch:
            clone_cmd = f"GIT_SSH_COMMAND='ssh {ssh_opts}' git clone -b {self.task.branch} {self.task.git_url} {git_name}"
        else:
            clone_cmd = f"GIT_SSH_COMMAND='ssh {ssh_opts}' git clone {self.task.git_url} {git_name}"
        ok, result = self.job_ssh_client.cmd(clone_cmd)
        if not ok:
            print(f"Clone failed: {result}")
        return ok

    def execute_job(self) -> State:
        if not self._clone_repo():
            self.write_status(State.FAILED, "git clone failed")
            return State.FAILED

        if self.pre_script:
            ok, result = self.job_ssh_client.cmd(f"./{self.pre_script.r_name}")
            print(f"Pre-script output:\n{result}")
            if not ok:
                print(f"Pre-script failed: {result}")
                self.write_status(State.FAILED, "pre-script failed")
                return State.FAILED

        sbatch_cmd = f"sbatch --parsable --job-name={self.job_name}"
        if self.task.partition:
            sbatch_cmd += f" --partition={self.task.partition}"
        if self.task.cpus:
            sbatch_cmd += f" --cpus-per-task={self.task.cpus}"
        if self.task.gpus:
            sbatch_cmd += f" --gpus={self.task.gpus}"
        if self.task.memory:
            sbatch_cmd += f" --mem={self.task.memory}"
        if self.task.time:
            sbatch_cmd += f" --time={self.task.time}"
        if self.task.nodelist:
            sbatch_cmd += f" --nodelist={self.task.nodelist}"
        sbatch_cmd += f" ./{self.script.r_name}"

        ok, result = self.job_ssh_client.cmd(sbatch_cmd, retries=3)
        if not ok:
            print(f"Job submission failed: {result}")
            self.write_status(State.FAILED, "sbatch submission failed")
            return State.FAILED

        job_id = result[0].strip().split(";")[0] if result else ""
        if job_id and job_id not in self.task.jobs_ids:
            self.task.jobs_ids.append(job_id)
        return State.PENDING
