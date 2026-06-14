import subprocess
import sys
from pathlib import Path

from .states import State


class Task:
    def __init__(
        self,
        name: str,
        git_url: str,
        path: str,
        run: list[str] = None,
        post: str = "",
        ssh_config: str = "",
        job: str = None,
        cleanup: bool = False,
        artifacts: list[str] = None,
        active_jobs: list[str] = None,
        state: State = State.PENDING,
    ):
        self.name = name
        self.ssh_config = ssh_config
        self.git_url = git_url
        self.path = path
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
            if self.cleanup_git:
                self.__cleanup_repository()
        if self.status in [State.COMPLETED, State.FAILED]:
            self.__sync_artifacts()
        return self.status

    def execute_remote_job(self):
        self.__clone_repository()
        return self.__execute_job()

    def __cleanup_repository(self):
        repo_name = self.git_url.split("/")[-1].replace(".git", "")
        result = subprocess.run(
            ["ssh", self.ssh_config, "rm", "-rf", repo_name],
            capture_output=True,
            text=True,
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
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.returncode != 0:
            print(result.stderr, end="", file=sys.stderr)

    def __scp_to(self, file):
        if not file:
            print("No file specified for SCP", file=sys.stderr)
            return
        result = subprocess.run(
            ["scp", file, f"{self.ssh_config}:{self.path}"],
            capture_output=True,
            text=True,
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
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.returncode != 0:
            print(result.stderr, end="", file=sys.stderr)

    def __execute_post_script(self):
        if not self.post:
            return
        post_script = Path(self.post).read_text(encoding="utf-8")
        if not post_script.strip():
            return
        result = subprocess.run(
            ["ssh", self.ssh_config, "bash -s"],
            input=post_script,
            text=True,
            capture_output=True,
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.returncode != 0:
            print(result.stderr, end="", file=sys.stderr)

    def __execute_job(self):
        print(f"Submitting job: {self.run}")
        commands = []
        for frun in self.run:
            try:
                with open(frun, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("#") or not line:
                            continue
                        commands.append(f"{line} >> pre_run_output.txt")
            except FileNotFoundError:
                print(f"Run script not found: {frun}", file=sys.stderr)
        if commands:
            commands += ["&&"]
        commands += [f"sbatch --parsable {self.job}"]
        final_payload = '"' + " ".join(commands) + '"'

        print(f"executing: {commands}")
        result = subprocess.run(
            ["ssh", self.ssh_config, "bash -lc", final_payload],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"Failed to submit job:\n{result.stderr}", file=sys.stderr)
            return State.FAILED
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
            )
            raw = result.stdout.strip()
            if raw:
                print(f"Health check - job {job_id}: {raw}")
            else:
                return State.COMPLETED
        return State.RUNNING

    def __check_pre_run(self):
        result = subprocess.run(
            ["ssh", self.ssh_config, "cat pre_run_output.txt"],
            text=True,
            capture_output=True,
        )
        raw = result.stdout.strip()
        if raw:
            print(f"Prerun output:\n{raw}")

    def __check_stdout(self):
        result = subprocess.run(
            ["ssh", self.ssh_config, "cat job_output.txt"],
            text=True,
            capture_output=True,
        )
        raw = result.stdout.strip()
        if raw:
            print(f"Job stdout:\n{raw}")

    def __check_stderr(self):
        result = subprocess.run(
            ["ssh", self.ssh_config, "cat job_error.txt"],
            text=True,
            capture_output=True,
        )
        raw = result.stdout.strip()
        if raw:
            print(f"Job stderr:\n{raw}")
