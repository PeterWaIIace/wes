from __future__ import annotations

from pathlib import Path

from wes.states import State
from wes.remote.runner import RemoteRunner


class JobController:

    def __init__(self, runner: RemoteRunner) -> None:
        self.runner = runner

    def sync_artifacts(self, task, target_dir: str, artifacts: list[str]) -> None:
        for artifact in artifacts:
            parts = artifact.split("/")
            path = parts[0]
            tfile = "/".join(parts[1:])
            dest = Path("results") / task.name / task.run_id / path
            dest.mkdir(parents=True, exist_ok=True)
            remote = f"{target_dir}/{path}"
            print(f"obtaining file from remote: {remote} tfile: {tfile} to {dest}")
            self.runner.scp_from(remote, tfile + "/.", str(dest), r=True)

    def upload_scripts(self, task) -> None:
        remote_dir = f"{task._run_dir}/scripts"
        self.runner.create_dir(remote_dir)
        for script in [task.job, task.post, *task.run]:
            if script:
                self.runner.scp_to(remote_dir, script, r=True)
        self.runner.log(f"scripts uploaded to {remote_dir}", "✓")

    def execute_post_script(self, task) -> None:
        if not task.post:
            return
        script_path = f"{task._run_dir}/scripts/{Path(task.post).name}"
        self.runner.log(f"running post script {task.post}", "▶")
        ok, _ = self.runner.run_command(f"bash {script_path}")
        if not ok:
            self.runner.log(f"post script failed: {task.post}", "✗")

    def _read_script(self, path: str) -> list[str]:
        script_lines: list[str] = []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or not line:
                        continue
                    script_lines.append(line)
        except FileNotFoundError:
            self.runner.log(f"run script not found: {path}", "⚠")
        return script_lines

    def execute_job(self, task) -> State:
        if task.job is None:
            self.runner.log("no job script specified", "✗")
            return State.FAILED

        self.runner.log(f"submitting job ({task.run_id}) via sbatch", "▶")

        for run_script in task.run:
            script_name = Path(run_script).name
            remote_script = f"{task._run_dir}/scripts/{script_name}"
            self.runner.run_command(
                f"bash {remote_script} >> pre_run_output.txt 2>&1"
            )

        job_name = Path(task.job).name
        job_path = f"{task._run_dir}/scripts/{job_name}"
        sbatch_cmd = f"sbatch --parsable --job-name={task.run_id}"
        overrides = task._sbatch_overrides()
        if overrides:
            sbatch_cmd += f" {overrides}"
        sbatch_cmd += f" {job_path}"

        ok, result = self.runner.run_command(sbatch_cmd)

        if not ok or not result:
            self.runner.log("sbatch submission failed", "✗")
            return State.FAILED

        raw = result[0].strip()
        job_id = raw.split(";")[0].strip()
        if not job_id or not job_id.isdigit():
            self.runner.log(f"unexpected sbatch output: {raw}", "✗")
            return State.FAILED

        task.jobs_ids.append(job_id)
        self.runner.log(f"job {job_id} submitted", "✓")
        return State.RUNNING
