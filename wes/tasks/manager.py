from __future__ import annotations

import re
import subprocess
import sys
import uuid
from pathlib import Path
from shutil import get_terminal_size

from .states import State

SEP = "─"
_ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x1b]*\x1b\\")


def _strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def _sep(label: str = "") -> str:
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
        run: list[str] | None = None,
        post: str = "",
        ssh_config: str = "",
        job: str | None = None,
        branch: str = "",
        cleanup: bool = False,
        artifacts: list[str] | None = None,
        active_jobs: list[str] | None = None,
        state: State = State.PENDING,
        partition: str = "",
        cpus: str = "",
        gpus: str = "",
        memory: str = "",
        time: str = "",
        nodelist: str = "",
        run_id: str = "",
    ) -> None:
        self.name = name
        self.ssh_config = ssh_config
        self.git_url = git_url
        self.branch = branch
        self.path = path
        self.job = job
        self.run = run if run is not None else []
        self.post = post
        self.cleanup_git = cleanup
        self.status = state
        self.jobs_ids: list[str] = active_jobs if active_jobs is not None else []
        self.artifacts: list[str] = artifacts if artifacts is not None else []
        self.partition = partition
        self.cpus = cpus
        self.gpus = gpus
        self.memory = memory
        self.time = time
        self.nodelist = nodelist
        self.run_id = run_id or f"{name}-{uuid.uuid4().hex[:8]}"

    @property
    def _run_dir(self) -> str:
        return f"runs/{self.run_id}"

    def execute(self) -> State:
        if self.status == State.PENDING:
            self.__create_run_dir()
            self.__clone_repository()
            self.status = self.execute_remote_job()
        elif self.status == State.RUNNING:
            self.__check_pre_run()
            self.__check_stderr()
            self.__check_stdout()
            self.__sync_artifacts()
            self.status = self.__health_check()
        if self.status in (State.COMPLETED, State.FAILED):
            self.jobs_ids = []
            self.__execute_post_script()
            self.__sync_artifacts()
            self.__cleanup_run_dir()
        return self.status

    def execute_remote_job(self) -> State:
        return self.__execute_job()

    def _log(self, msg: str, kind: str = "•") -> None:
        print(f"  {kind} {msg}")

    def _sbatch_overrides(self) -> str:
        parts: list[str] = []
        if self.partition:
            parts.append(f"--partition={self.partition}")
        if self.cpus:
            parts.append(f"--cpus-per-task={self.cpus}")
        if self.gpus:
            parts.append(f"--gres=gpu:{self.gpus}")
        if self.memory:
            parts.append(f"--mem={self.memory}")
        if self.time:
            parts.append(f"--time={self.time}")
        if self.nodelist:
            parts.append(f"--nodelist={self.nodelist}")
        return " ".join(parts)

    def __create_run_dir(self) -> None:
        self._log(f"creating run dir {self._run_dir}", "▶")
        subprocess.run(
            ["ssh", self.ssh_config, f"mkdir -p {self._run_dir}"],
            capture_output=True, text=True, check=True,
        )

    def __cleanup_run_dir(self) -> None:
        self._log(f"cleaning up {self._run_dir}", "▶")
        subprocess.run(
            ["ssh", self.ssh_config, f"rm -rf {self._run_dir}"],
            capture_output=True, text=True, check=False,
        )

    def __clone_repository(self) -> None:
        git_name = self.git_url.split("/")[-1].replace(".git", "")
        run_dir = self._run_dir
        if self.branch:
            clone_cmd = f"git clone -b {self.branch} {self.git_url} {run_dir}/{git_name}"
        else:
            clone_cmd = f"git clone {self.git_url} {run_dir}/{git_name}"
        subprocess.run(
            ["ssh", self.ssh_config, clone_cmd],
            capture_output=True, text=True, check=True,
        )

    def __scp_to(self, file: str | None, r: bool = False) -> None:
        if not file:
            self._log("no file specified for SCP", "⚠")
            return
        dest = f"{self.ssh_config}:{self._run_dir}/"
        cmd = ["scp", file, dest]
        if r:
            cmd = ["scp", "-r", file, dest]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        if result.stdout:
            print(result.stdout, end="")

    def __sync_artifacts(self) -> None:
        for artifact in self.artifacts:
            parts = artifact.split("/")
            path = parts[0]
            tfile = "/".join(parts[1:])
            dest = Path("results") / self.name / self.run_id / path
            dest.mkdir(parents=True, exist_ok=True)
            remote = f"{self._run_dir}/{path}"
            self.__scp_from(remote, tfile + "/.", str(dest), r=True)

    def __scp_from(self, remote_path: str, tfile: str, cfile: str, r: bool = False) -> None:
        if not tfile or not cfile:
            print("No file specified for SCP", file=sys.stderr)
            return
        src = f"{self.ssh_config}:{remote_path}/{tfile}"
        cmd = ["rsync", "-e", "ssh", src, cfile]
        if r:
            cmd = ["rsync", "-r", "--no-inc-recursive", "-e", "ssh", src, cfile]
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )

    def __execute_post_script(self) -> None:
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

    def __execute_job(self) -> State:
        self._log(f"submitting job ({self.run_id}) via sbatch", "▶")
        script_lines: list[str] = []
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
        if self.job is None:
            self._log("no job script specified", "✗")
            return State.FAILED
        overrides = self._sbatch_overrides()
        sbatch_cmd = f"sbatch --parsable --job-name={self.run_id}"
        if overrides:
            sbatch_cmd += f" {overrides}"
        git_name = self.git_url.split("/")[-1].replace(".git", "")
        job_path = f"{git_name}/{self.path}/{self.job}"
        sbatch_cmd += f" {job_path}"
        script_lines.append(sbatch_cmd)
        full_script = "exec > pre_run_output.txt 2>&1\n" + "\n".join(script_lines)

        try:
            result = subprocess.run(
                ["ssh", self.ssh_config, f"cd {self._run_dir} && bash -ls"],
                input=full_script,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            logs = self.fetch_remote_logs()
            self._log(f"sbatch failed (exit {e.returncode}):\n{logs}", "✗")
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

    def __health_check(self) -> State:
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

    def __fetch_output(self, remote_file: str) -> None:
        local_dir = Path("results") / self.name / self.run_id
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / remote_file
        self.__scp_from(self._run_dir, remote_file, str(local_path), r=True)

    def __check_pre_run(self) -> None:
        self.__fetch_output("pre_run_output.txt")
        result = subprocess.run(
            ["ssh", self.ssh_config, f"cat {self._run_dir}/pre_run_output.txt"],
            text=True,
            capture_output=True,
        )
        raw = result.stdout.strip()
        if raw:
            print(f"\n{_sep('pre')}")
            print(_strip_ansi(raw))
            print(f"{_sep()}")

    def __check_stdout(self) -> None:
        self.__fetch_output("job_output.txt")
        result = subprocess.run(
            ["ssh", self.ssh_config, f"cat {self._run_dir}/job_output.txt"],
            text=True,
            capture_output=True,
        )
        raw = result.stdout.strip()
        if raw:
            print(f"\n{_sep('out')}")
            print(_strip_ansi(raw))
            print(f"{_sep()}")

    def __check_stderr(self) -> None:
        self.__fetch_output("job_error.txt")
        result = subprocess.run(
            ["ssh", self.ssh_config, f"cat {self._run_dir}/job_error.txt"],
            text=True,
            capture_output=True,
        )
        raw = result.stdout.strip()
        if raw:
            print(f"\n{_sep('err')}")
            print(_strip_ansi(raw))
            print(f"{_sep()}")

    def fetch_remote_logs(self) -> dict[str, str]:
        logs: dict[str, str] = {}
        for fname in ("pre_run_output.txt", "job_output.txt", "job_error.txt"):
            try:
                result = subprocess.run(
                    ["ssh", self.ssh_config, f"cat {self._run_dir}/{fname}"],
                    text=True,
                    capture_output=True,
                    timeout=10,
                )
                raw = result.stdout.strip()
                if raw:
                    logs[fname] = _strip_ansi(raw)
            except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
                pass
        return logs
