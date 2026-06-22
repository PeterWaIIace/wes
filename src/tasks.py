import re
import subprocess
import sys
from pathlib import Path
from shutil import get_terminal_size

from .states import State

SEP = "─"
_ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x1b]*\x1b\\")


def _strip_ansi(text):
    return _ANSI.sub("", text)


def _sep(label=""):
    w = get_terminal_size().columns
    if label:
        left = f" {label} "
        right = SEP * (w - len(left) - 2)
        return f" {left}{right}"
    return SEP * w


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
            self.__sync_artifacts()
            self.status = self.__health_check()
        if self.status in [State.COMPLETED, State.FAILED]:
            self.jobs_ids = []
            self.__execute_post_script()
            self.__sync_artifacts()
            if self.cleanup_git:
                self.__cleanup_repository()
        return self.status

    def execute_remote_job(self):
        return self.__execute_job()

    def _log(self, msg, kind="•"):
        print(f"  {kind} {msg}")

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
        if self.branch:
            update_cmd = (
                f"cd {git_name} && git fetch origin && git reset --hard origin/{self.branch}"
            )
            clone_cmd = f"git clone -b {self.branch} {self.git_url}"
        else:
            update_cmd = f"cd {git_name} && git pull --ff-only"
            clone_cmd = f"git clone {self.git_url}"
        cmd = f"if [ -d {git_name}/.git ]; then {update_cmd}; else {clone_cmd}; fi"
        subprocess.run(
            ["ssh", self.ssh_config, cmd],
            capture_output=True,
            text=True,
            check=True,
        )

    def __scp_to(self, file, r=False):
        if not file:
            self._log("no file specified for SCP", "⚠")
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
            dest = Path("results") / self.name / path
            dest.mkdir(parents=True, exist_ok=True)
            self.__scp_from(path, tfile + "/.", str(dest), r=True)

    def __scp_from(self, path, tfile, cfile, r=False):
        if not tfile or not cfile:
            print("No file specified for SCP", file=sys.stderr)
            return
        src = f"{self.ssh_config}:~/{path}/{tfile}"
        cmd = ["rsync", "-e", "ssh", src, cfile]
        if r:
            cmd = ["rsync", "-r", "--no-inc-recursive", "-e", "ssh", src, cfile]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(
                "Warning: rsync from remote failed"
                f" (return code {result.returncode}): {result.stderr.strip()}",
                file=sys.stderr,
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
        self._log("cloning repository", "▶")
        self.__clone_repository()
        self._log("submitting job via sbatch", "▶")
        script_lines = []
        for frun in self.run:
            try:
                with open(frun, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("#") or not line:
                            continue
                        script_lines.append(line)
            except FileNotFoundError:
                self._log(f"run script not found: {frun}", "⚠")
        script_lines.append(f"sbatch --parsable {Path(self.path, Path(self.job).name)}")
        full_script = "exec > pre_run_output.txt 2>&1\n" + "\n".join(script_lines)

        try:
            result = subprocess.run(
                ["ssh", self.ssh_config, "bash -ls"],
                input=full_script,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            self._log(f"sbatch failed:\n{e.stderr}", "✗")
            return State.FAILED
        raw = result.stdout.strip()
        job_id = raw.split(";")[0]
        self._log(f"job {job_id} submitted", "✓")
        self.jobs_ids.append(job_id)
        return State.RUNNING

    def has_alive_jobs(self) -> bool:
        if not self.jobs_ids:
            return False
        for job_id in self.jobs_ids:
            try:
                result = subprocess.run(
                    ["ssh", self.ssh_config, f'squeue -h -j {job_id} -o "%T"'],
                    text=True,
                    capture_output=True,
                    check=True,
                )
                if result.stdout.strip():
                    return True
            except subprocess.CalledProcessError:
                pass
        return False

    def __health_check(self):
        for job_id in self.jobs_ids:
            try:
                result = subprocess.run(
                    ["ssh", self.ssh_config, f'squeue -h -j {job_id} -o "%T"'],
                    text=True,
                    capture_output=True,
                    check=True,
                )
                raw = result.stdout.strip()
                if raw:
                    self._log(f"job {job_id}: {raw}", "◌")
                else:
                    self._log(f"job {job_id}: completed", "✓")
                    return State.COMPLETED
            except subprocess.CalledProcessError:
                self._log(f"job {job_id}: completed", "✓")
                return State.COMPLETED
        return State.RUNNING

    def __fetch_output(self, remote_file):
        local_dir = Path("results") / self.name
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / remote_file
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
            print(f"\n{_sep('pre')}")
            print(_strip_ansi(raw))
            print(f"{_sep()}")

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
            print(f"\n{_sep('out')}")
            print(_strip_ansi(raw))
            print(f"{_sep()}")

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
            print(f"\n{_sep('err')}")
            print(_strip_ansi(raw))
            print(f"{_sep()}")
