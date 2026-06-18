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
        branch: str = "",
        cleanup: bool = False,
        artifacts: list[str] = None,
        active_jobs: list[str] = None,
        state: State = State.PENDING,
    ):
        self.name = name
        self.ssh_config = ssh_config
        self.git_url = git_url
        self.branch = branch
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
        subprocess.run(
            ["ssh", self.ssh_config, "rm", "-rf", repo_name],
            capture_output=True,
            text=True,
            check=True,
        )

    def __clone_repository(self):
        git_name = self.git_url.split("/")[-1].replace(".git", "")
        clone_cmd = ["git", "clone"]
        if self.branch:
            clone_cmd += ["-b", self.branch]
        clone_cmd.append(self.git_url)
        subprocess.run(
            ["ssh", self.ssh_config, f"[ -d {git_name}/.git ]", "||", *clone_cmd],
            capture_output=True,
            text=True,
            check=True,
        )

    def __scp_to(self, file, r=False):
        if not file:
            print("No file specified for SCP", file=sys.stderr)
            return
        cmd = ["scp", file, f"{self.ssh_config}:{self.path}"]
        if r:
            cmd = ["scp", "-r", file, f"{self.ssh_config}:{self.path}"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        if result.stdout:
            print(result.stdout, end="")

    def __sync_artifacts(self):
        for artifact in self.artifacts:
            path = artifact.split("/")[0]
            tfile = "/".join(artifact.split("/")[1:])
            dest = Path(self.name) / artifact
            dest.parent.mkdir(parents=True, exist_ok=True)
            self.__scp_from(path, tfile, str(dest))

    def __scp_from(self, path, tfile, cfile, r=False):
        if not tfile or not cfile:
            print("No file specified for SCP", file=sys.stderr)
            return
        cmd = ["scp", f"{self.ssh_config}:~/{path}/{tfile}", cfile]
        if r:
            cmd = ["scp", "-r", f"{self.ssh_config}:~/{path}/{tfile}", cfile]
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )

    def __execute_post_script(self):
        if not self.post:
            return
        post_script = Path(self.post).read_text(encoding="utf-8")
        if not post_script.strip():
            return
        subprocess.run(
            ["ssh", self.ssh_config, "bash -s"],
            input=post_script,
            text=True,
            capture_output=True,
            check=True,
        )

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
        try:
            result = subprocess.run(
                ["ssh", self.ssh_config, "bash -lc", final_payload],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            print(f"Failed to submit job:\n{e.stderr}", file=sys.stderr)
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
                check=True,
            )
            raw = result.stdout.strip()
            if raw:
                print(f"Health check - job {job_id}: {raw}")
            else:
                return State.COMPLETED
        return State.RUNNING

    def __fetch_output(self, remote_file):
        Path(self.name).mkdir(parents=True, exist_ok=True)
        local_path = Path(self.name) / remote_file
        self.__scp_from("", remote_file, str(local_path), r=True)

    def __check_pre_run(self):
        self.__fetch_output("pre_run_output.txt")
        result = subprocess.run(
            ["ssh", self.ssh_config, "cat pre_run_output.txt"],
            text=True,
            capture_output=True,
            check=True,
        )
        raw = result.stdout.strip()
        if raw:
            print(f"Prerun output:\n{raw}")

    def __check_stdout(self):
        self.__fetch_output("job_output.txt")
        result = subprocess.run(
            ["ssh", self.ssh_config, "cat job_output.txt"],
            text=True,
            capture_output=True,
            check=True,
        )
        raw = result.stdout.strip()
        if raw:
            print(f"Job stdout:\n{raw}")

    def __check_stderr(self):
        self.__fetch_output("job_error.txt")
        result = subprocess.run(
            ["ssh", self.ssh_config, "cat job_error.txt"],
            text=True,
            capture_output=True,
            check=True,
        )
        raw = result.stdout.strip()
        if raw:
            print(f"Job stderr:\n{raw}")
