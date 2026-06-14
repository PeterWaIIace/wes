#!/usr/bin/env python3
import subprocess
import sys
from enum import Enum
from pathlib import Path

import yaml
from dotenv import load_dotenv

prejob = """
git clone {git_urlr}
# preactions
{actions}
"""

postjob = """
scp {ssh_target} {to_path}
"""


class HealthCheckCtx:
    def __init__(self):
        self.default_path = "active_processes.yml"
        self.data = self.load()

    def load(self) -> dict:
        """Load health check data from YAML file."""
        if not Path(self.default_path).exists():
            return {}
        with open(self.default_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def add(self, task_name: str, task_process: str):
        """Add a new task to the health check data."""
        loaded_data = self.load()
        self.data[task_name] = {"id": task_process}
        self.data |= loaded_data
        with open(self.default_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.data, f)

    def get_processes(self):
        return self.data


class State(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETING = "COMPLETING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"


class Task:
    def __init__(
        self,
        name: str,
        git_url: str,
        path: str,
        run: str = "",
        post: str = "",
        ssh_config: str = "",
        job: str = None,
        command: str = "",
        cleanup: bool = False,
        artifacts: list[int] = None,
        active_jobs: list[int] = None,
        state: State = State.PENDING,
    ):
        self.name = name
        self.ssh_config = ssh_config
        self.git_url = git_url
        self.path = path
        self.command = command
        self.job = job
        self.run = run
        self.post = post
        self.cleanup_git = cleanup
        self.status = state
        self.jobs_ids = active_jobs if active_jobs is not None else []
        self.artifacts = artifacts if artifacts is not None else []

    def execute(self):
        if self.status == State.PENDING:
            self.__scp_to(self.job)
            self.status = self.execute_remote_job()
        elif self.status == State.RUNNING:
            self.__check_pre_run()
            self.__check_stderr()
            self.__check_stdout()
            self.status = self.__health_check()
        elif self.status in [State.COMPLETED, State.FAILED]:
            self.jobs_ids = []
            self.__execute_post_script()
            # if self.cleanup_git:
            #     self.__cleanup_repository()
        self.__sync_artifacts()
        return self.status

    def execute_remote_job(self):
        self.__clone_repository()
        self.__execture_job()
        return State.RUNNING

    def __cleanup_repository(self):
        repo_name = self.git_url.split("/")[-1].replace(".git", "")
        result = subprocess.run(
            ["ssh", self.ssh_config, "rm", "-rf", repo_name],
            capture_output=True,
            text=True,
            check=True,
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.returncode != 0:
            print(result.stderr, end="", file=sys.stderr)

    def __clone_repository(self):
        git_name = self.git_url.split("/")[-1].replace(".git", "")
        result = subprocess.run(
            ["ssh", self.ssh_config, f"[ -d {git_name}/.git ]", "||", "git", "clone", self.git_url],
            capture_output=True,
            text=True,
            check=True,
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.returncode != 0:
            print(result.stderr, end="", file=sys.stderr)

    def __scp_to(self, file):
        result = subprocess.run(
            ["scp", file, f"{self.ssh_config}:{self.path}"],
            capture_output=True,
            text=True,
            check=True,
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.returncode != 0:
            print(result.stderr, end="", file=sys.stderr)

    def __sync_artifacts(self):
        Path(self.name).mkdir(exist_ok=True)
        for artifact in self.artifacts:
            file_name = artifact.split("/")[-1]
            tfile = "/".join(artifact.split("/")[1:])
            path = artifact.split("/")[0]
            self.__scp_from(path, tfile, f"{self.name}/{file_name}")

    def __scp_from(self, path, tfile, cfile):
        result = subprocess.run(
            ["scp", f"{self.ssh_config}:~/{path}/{tfile}", cfile],
            capture_output=True,
            text=True,
            check=True,
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.returncode != 0:
            print(result.stderr, end="", file=sys.stderr)

    def __execute_post_script(self):
        post_script = Path(self.post).read_text(encoding="utf-8")
        subprocess.run(
            ["ssh", self.ssh_config, "bash -s"],
            input=post_script,  # sends local script content to remote bash stdin
            text=True,
            capture_output=True,
            check=True,
        )

    def __execture_job(self):
        print(f"Submitting job: {self.run}")
        commands = []
        for frun in self.run:
            with open(frun, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or not line:
                        continue
                    if line:
                        commands.append(f"{line} >> pre_run_output.txt")
        commands += ["&&"]

        commands += [f"sbatch --parsable {self.job}"]
        final_payload = '"' + " ".join(commands) + '"'

        print(f"executing: {commands}")
        result = subprocess.run(
            ["ssh", self.ssh_config, "bash -lc", final_payload],
            capture_output=True,
            text=True,
            check=True,
        )
        raw = result.stdout.strip()
        job_id = raw.split(";")[0]
        print(f"Submitted job with ID: {job_id}")
        self.jobs_ids.append(job_id)
        return State.RUNNING

    def __health_check(self):
        for job_id in self.jobs_ids:
            result = subprocess.run(
                ["ssh", self.ssh_config, f'squeue -h -j {job_id} -o "%T"'],
                text=True,
                capture_output=True,
                check=True,
            )
            raw = result.stdout.strip()
            print(f"Health check output:\n{raw}")
            if raw == "":
                return State.COMPLETED

    def __check_pre_run(self):
        result = subprocess.run(
            ["ssh", self.ssh_config, "cat pre_run_output.txt"],
            text=True,
            capture_output=True,
            check=True,
        )
        raw = result.stdout.strip()
        print(f"Prerun check output:\n{raw}")

    def __check_stdout(self):
        for _ in self.jobs_ids:
            result = subprocess.run(
                ["ssh", self.ssh_config, "cat job_output.txt"],
                text=True,
                capture_output=True,
                check=True,
            )
            raw = result.stdout.strip()
            print(f"Error check output:\n{raw}")

    def __check_stderr(self):
        for _ in self.jobs_ids:
            result = subprocess.run(
                ["ssh", self.ssh_config, "cat job_error.txt"],
                text=True,
                capture_output=True,
                check=True,
            )
            raw = result.stdout.strip()
            print(f"Stdout check output:\n{raw}")


class WESParser:
    def __init__(self):
        self.file_to_process = ""
        self.task_count = 0

    def get_next_task(self, data: dict) -> dict:
        sequence = data.get("sequence", None)
        if sequence is None:
            name = list(sequence.keys())[0]
            task = sequence[name]
            task["name"] = name
            return task  # get first and only task
        name = list(sequence.keys())[self.task_count]
        task = sequence[name]
        task["name"] = name
        return task

    def parse(self, config_file: str) -> list[Task]:
        """Parse WES configuration file and return list of Task objects."""
        tasks = []
        with open(config_file, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            task = self.get_next_task(data)
            tasks.append(self.process_task(task))
        return tasks

    def process_task(self, task_data: dict) -> Task:
        """Convert task data from WES format to Task object."""
        name = task_data.get("name", "Unnamed Task")
        git_url = task_data.get("git_url")
        path = task_data.get("path", ".")
        command = task_data.get("command", "")
        ssh_config = task_data.get("ssh", "")
        job = task_data.get("job", "")
        run = task_data.get("run", "")
        post = task_data.get("post", "")
        artifacts = task_data.get("artifacts", [])
        cleanup = task_data.get("cleanup", False)

        return Task(
            name=name,
            git_url=git_url,
            path=path,
            ssh_config=ssh_config,
            command=command,
            cleanup=cleanup,
            run=run,
            job=job,
            post=post,
            artifacts=artifacts,
        )


def main():
    """Main entry point."""
    # Load environment variables from .env file
    load_dotenv()

    config_file = sys.argv[1] if len(sys.argv) > 1 else "tasks.wes"

    wes = WESParser()
    tasks = wes.parse(config_file)

    for task in tasks:
        print(f"\nProcessing sequence: {task.name} ({task.git_url})")
        task.execute()
        task.execute()
        task.execute()


if __name__ == "__main__":
    main()
