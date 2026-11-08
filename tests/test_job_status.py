from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import yaml

from wes.jobs.job import Job, JobInfo
from wes.jobs.status import (
    STATUS_FILENAME,
    STATUS_HELPER_NAME,
    STATUS_HELPER_SCRIPT,
    JobStatus,
    StatusFile,
    inject_job_status,
    inject_pre_status,
    slurm_state,
)
from wes.states import State
from wes.tasks import Task


def _task() -> Task:
    return Task(
        name="my_task",
        git_url="git@github.com:user/repo.git",
        path=".",
        ssh_config="hpc",
        job_script="job.sh",
    )


def _run(cmd: str, script: str | None = None, **kwargs):
    if "sbatch" in cmd:
        return True, ["4242"]
    if "git clone" in cmd:
        return True, ["cloning"]
    return True, [""]


def _job(monkeypatch, tmp_path, task: Task | None = None) -> tuple[Job, MagicMock]:
    """Build a Job with every ssh call mocked; returns (job, shared runner mock)."""
    monkeypatch.chdir(tmp_path)

    runner_cls = MagicMock()
    monkeypatch.setattr("wes.jobs.job.SshRunner", runner_cls)
    monkeypatch.setattr("wes.jobs.status.SshRunner", runner_cls)

    runner = runner_cls.return_value
    runner.run_command.side_effect = _run
    return Job(task or _task(), "hpc"), runner


def _cmds(runner: MagicMock) -> list[str]:
    return [
        c.args[0] if c.args else c.kwargs.get("cmd", "") for c in runner.run_command.call_args_list
    ]


def _status_writes(runner: MagicMock) -> list[JobStatus]:
    writes = []
    for call in runner.run_command.call_args_list:
        cmd = call.args[0] if call.args else call.kwargs.get("cmd", "")
        script = call.kwargs.get("script")
        if STATUS_FILENAME in cmd and script:
            writes.append(JobStatus.from_text(script))
    return writes


def test_status_roundtrip() -> None:
    status = JobStatus(
        task="my_task",
        namespace="ns",
        job_name="my_task_ns",
        ssh="hpc",
        state=State.RUNNING,
        job_id="4242",
        node="h86",
        partition="gpu",
        updated="2026-09-22 10:00:00",
        message="",
    )
    parsed = JobStatus.from_text(status.to_text())
    assert parsed == status


def test_status_text_is_yaml_and_omits_empty_fields() -> None:
    text = JobStatus(task="t", namespace="n", job_name="j", ssh="hpc", updated="now").to_text()
    assert yaml.safe_load(text) == {
        "task": "t",
        "namespace": "n",
        "job_name": "j",
        "ssh": "hpc",
        "state": "PENDING",
        "updated": "now",
    }


def test_status_roundtrip_with_wes_file() -> None:
    status = JobStatus(
        task="my_task",
        namespace="ns",
        job_name="my_task_ns",
        ssh="hpc",
        wes_file="ncpu_adder.wes",
        state=State.RUNNING,
        updated="2026-09-22 10:00:00",
    )
    text = status.to_text()
    assert "task: my_task" in text
    assert "wes_file: ncpu_adder.wes" in text
    assert JobStatus.from_text(text) == status


def test_status_from_text_unknown_state_is_pending() -> None:
    parsed = JobStatus.from_text("state: WAT")
    assert parsed.state is State.PENDING


def test_status_from_text_legacy_key_value_still_parses() -> None:
    parsed = JobStatus.from_text(
        "task=t\nnamespace=n\njob_name=j\nssh=hpc\nstate=RUNNING\njob_id=4242\n"
        "updated=2026-09-22 10:00:00\n"
    )
    assert parsed.task == "t"
    assert parsed.state is State.RUNNING
    assert parsed.job_id == "4242"


def test_slurm_state_mapping() -> None:
    assert slurm_state("RUNNING") is State.RUNNING
    assert slurm_state("COMPLETING") is State.RUNNING
    assert slurm_state("CANCELLED by 1000") is State.CANCELLED
    assert slurm_state("TIMEOUT") is State.FAILED
    assert slurm_state("OUT_OF_MEMORY") is State.FAILED
    assert slurm_state("WAT") is State.PENDING


def test_status_file_writes_atomically(monkeypatch) -> None:
    with patch("wes.jobs.status.SshRunner") as runner_cls:
        runner = runner_cls.return_value
        runner.run_command.return_value = (True, [])
        status_file = StatusFile("task/ns", "hpc")
        assert status_file.write(JobStatus(task="t", namespace="n", job_name="j", ssh="hpc"))

    cmd = runner.run_command.call_args.args[0]
    tmp = f"{STATUS_FILENAME}.tmp"
    assert cmd == f"cd task/ns && cat > {tmp} && mv {tmp} {STATUS_FILENAME}"
    script = runner.run_command.call_args.kwargs["script"]
    assert yaml.safe_load(script)["task"] == "t"


def test_status_file_read_returns_none_when_missing() -> None:
    with patch("wes.jobs.status.SshRunner") as runner_cls:
        runner_cls.return_value.run_command.return_value = (False, [])
        assert StatusFile("task/ns", "hpc").read() is None


def test_status_helper_script_writes_status_file() -> None:
    assert STATUS_FILENAME in STATUS_HELPER_SCRIPT
    assert "SLURM_JOB_ID" in STATUS_HELPER_SCRIPT
    assert 'mv "$tmp" "$status"' in STATUS_HELPER_SCRIPT
    # the script-created file also records the source .wes file and task name
    assert 'json_get "$cfg" wes_file' in STATUS_HELPER_SCRIPT
    assert 'json_get "$cfg" name' in STATUS_HELPER_SCRIPT


def test_status_file_write_helper_uploads_executable(monkeypatch) -> None:
    with patch("wes.jobs.status.SshRunner") as runner_cls:
        runner = runner_cls.return_value
        runner.run_command.return_value = (True, [])
        assert StatusFile("task/ns", "hpc").write_helper()

    call = runner.run_command.call_args
    tmp = f"{STATUS_HELPER_NAME}.tmp"
    assert call.args[0] == (
        f"cd task/ns && cat > {tmp} && mv {tmp} {STATUS_HELPER_NAME} "
        f"&& chmod +x {STATUS_HELPER_NAME}"
    )
    assert call.kwargs["script"] == STATUS_HELPER_SCRIPT


def test_job_status_and_config_carry_wes_file(monkeypatch, tmp_path) -> None:
    task = _task()
    task.wes_file = "ncpu_adder.wes"
    job, _runner = _job(monkeypatch, tmp_path, task=task)

    assert job.status.wes_file == "ncpu_adder.wes"
    assert job.status.task == "my_task"
    cfg_path = tmp_path / "results" / job.job_name / f"{task.name}_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert cfg["task"]["wes_file"] == "ncpu_adder.wes"
    assert cfg["task"]["name"] == "my_task"


def test_upload_scripts_also_uploads_status_helper(monkeypatch, tmp_path) -> None:
    (tmp_path / "job.sh").write_text(SAMPLE_JOB_SH)
    job, runner = _job(monkeypatch, tmp_path)
    job.upload_scripts()
    job.execute_job()

    calls = runner.run_command.call_args_list
    helper_idx = next(
        i
        for i, c in enumerate(calls)
        if STATUS_HELPER_NAME in (c.args[0] if c.args else "")
        and c.kwargs.get("script") == STATUS_HELPER_SCRIPT
    )
    sbatch_idx = next(i for i, cmd in enumerate(_cmds(runner)) if "sbatch" in cmd)
    assert helper_idx < sbatch_idx


def test_execute_job_leaves_status_file_to_the_scripts(monkeypatch, tmp_path) -> None:
    job, runner = _job(monkeypatch, tmp_path)
    state = job.execute_job()

    assert state is State.PENDING
    assert job.task.jobs_ids == ["4242"]
    # pre.sh/job.sh create and update wes.status on the server, not the client
    assert _status_writes(runner) == []


def test_execute_job_writes_failed_when_clone_fails(monkeypatch, tmp_path) -> None:
    job, runner = _job(monkeypatch, tmp_path)
    runner.run_command.side_effect = lambda cmd, script=None, **kw: (
        (False, ["nope"]) if "git clone" in cmd else (True, [""])
    )

    assert job.execute_job() is State.FAILED
    writes = _status_writes(runner)
    assert len(writes) == 1
    assert writes[0].state is State.FAILED
    assert writes[0].message == "git clone failed"


def test_execute_job_writes_failed_when_pre_script_fails(monkeypatch, tmp_path) -> None:
    task = _task()
    task.pre_script = "pre.sh"
    job, runner = _job(monkeypatch, tmp_path, task=task)
    runner.run_command.side_effect = lambda cmd, script=None, **kw: (
        (False, ["nope"]) if "pre.sh" in cmd else (True, [""])
    )

    assert job.execute_job() is State.FAILED
    writes = _status_writes(runner)
    assert len(writes) == 1
    assert writes[0].state is State.FAILED
    assert writes[0].message == "pre-script failed"


def test_execute_job_writes_failed_when_sbatch_fails(monkeypatch, tmp_path) -> None:
    job, runner = _job(monkeypatch, tmp_path)
    runner.run_command.side_effect = lambda cmd, script=None, **kw: (
        (False, ["nope"]) if "sbatch" in cmd else (True, [""])
    )

    assert job.execute_job() is State.FAILED
    writes = _status_writes(runner)
    assert len(writes) == 1
    assert writes[-1].state is State.FAILED
    assert writes[-1].message == "sbatch submission failed"


def test_set_info_does_not_touch_status_file(monkeypatch, tmp_path) -> None:
    job, runner = _job(monkeypatch, tmp_path)
    info = JobInfo(
        job_id="4242",
        user="me",
        name=job.job_name,
        state="RUNNING",
        time="00:10:00",
        nodes="h86",
        partition="gpu",
        reason="None",
        cpus="4",
        memory="16G",
    )

    job.set_info(info)
    job.set_info(info)

    assert job.info is info
    assert _status_writes(runner) == []


def test_pull_status_reads_script_written_file(monkeypatch, tmp_path) -> None:
    job, runner = _job(monkeypatch, tmp_path)
    remote_lines = [
        "task: my_task",
        f"namespace: {job.namespace}",
        f"job_name: {job.job_name}",
        "ssh: hpc",
        "state: RUNNING",
        "updated: '2026-09-22 10:00:00'",
        "job_id: '4242'",
        "node: h86",
        "partition: gpu-l",
    ]

    def _run_remote(cmd: str, script: str | None = None, **kw):
        if script is None and f"cat {STATUS_FILENAME}" in cmd:
            return True, remote_lines
        return _run(cmd, script=script, **kw)

    runner.run_command.side_effect = _run_remote

    assert job.pull_status() is True
    assert job.status.state is State.RUNNING
    assert job.status.job_id == "4242"
    assert job.status.node == "h86"
    assert job.status.partition == "gpu-l"

    # an unchanged write_status after a pull must not push back to the server
    assert job.write_status(State.RUNNING, job_id="4242", node="h86", partition="gpu-l") is True
    assert _status_writes(runner) == []


def test_pull_status_returns_false_when_missing(monkeypatch, tmp_path) -> None:
    job, runner = _job(monkeypatch, tmp_path)
    runner.run_command.side_effect = lambda cmd, script=None, **kw: (
        (False, []) if f"cat {STATUS_FILENAME}" in cmd and script is None else (True, [""])
    )
    assert job.pull_status() is False


SAMPLE_JOB_SH = """#!/bin/bash
#SBATCH --partition=gpu
#SBATCH --time=02:00:00

module load uv
uv run train.py
"""


def test_inject_job_status_after_sbatch_header() -> None:
    out = inject_job_status(SAMPLE_JOB_SH)
    lines = out.splitlines()
    assert lines[0] == "#!/bin/bash"
    sbatch_idx = max(i for i, ln in enumerate(lines) if ln.startswith("#SBATCH"))
    trap_idx = next(i for i, ln in enumerate(lines) if ln.startswith("trap wes_on_exit"))
    body_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "module load uv")
    assert sbatch_idx < trap_idx < body_idx
    # idempotent
    assert inject_job_status(out) == out


def test_inject_job_status_without_header() -> None:
    out = inject_job_status("echo hi\n")
    lines = out.splitlines()
    trap_idx = next(i for i, ln in enumerate(lines) if ln.startswith("trap wes_on_exit"))
    echo_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "echo hi")
    assert trap_idx < echo_idx
    assert inject_job_status(out) == out


def test_inject_pre_status_prepends_after_shebang() -> None:
    out = inject_pre_status("#!/bin/bash\nmodule load uv\n")
    lines = out.splitlines()
    assert lines[0] == "#!/bin/bash"
    assert STATUS_HELPER_NAME in lines[2]
    assert "module load uv" in out
    assert inject_pre_status(out) == out


def test_inject_pre_status_without_shebang() -> None:
    out = inject_pre_status("module load uv\n")
    assert STATUS_HELPER_NAME in out.splitlines()[1]
    assert inject_pre_status(out) == out


def _capture_uploads(runner: MagicMock) -> dict:
    uploaded: dict = {}

    def fake_scp_to(r_path, file, r=False):
        with open(file, encoding="utf-8") as f:
            uploaded[os.path.basename(file)] = f.read()
        return True

    runner.scp_to.side_effect = fake_scp_to
    return uploaded


def test_preprocess_stages_transformed_copy(monkeypatch, tmp_path) -> None:
    (tmp_path / "job.sh").write_text(SAMPLE_JOB_SH)
    job, _runner = _job(monkeypatch, tmp_path)

    staging = str(tmp_path / "staging")
    staged = job._preprocess(job.script, inject_job_status, staging)

    with open(staged, encoding="utf-8") as f:
        content = f.read()
    assert content.splitlines()[0] == "#!/bin/bash"
    assert STATUS_HELPER_NAME in content
    assert os.path.basename(staged) == "job.sh"
    # the original local file is never modified
    assert (tmp_path / "job.sh").read_text() == SAMPLE_JOB_SH


def test_upload_scps_given_file_as_is(monkeypatch, tmp_path) -> None:
    (tmp_path / "job.sh").write_text(SAMPLE_JOB_SH)
    job, runner = _job(monkeypatch, tmp_path)
    calls = []
    runner.scp_to.side_effect = lambda r_path, file, r=False: calls.append((r_path, file)) or True

    job._upload(job.script, str(tmp_path / "job.sh"))

    assert calls == [(job.script.r_path, str(tmp_path / "job.sh"))]


def test_upload_scripts_preprocesses_job_script(monkeypatch, tmp_path) -> None:
    (tmp_path / "job.sh").write_text(SAMPLE_JOB_SH)
    job, runner = _job(monkeypatch, tmp_path)
    uploaded = _capture_uploads(runner)

    job.upload_scripts()

    content = uploaded["job.sh"]
    lines = content.splitlines()
    assert lines[0] == "#!/bin/bash"
    assert STATUS_HELPER_NAME in content
    sbatch_idx = max(i for i, ln in enumerate(lines) if ln.startswith("#SBATCH"))
    trap_idx = next(i for i, ln in enumerate(lines) if ln.startswith("trap wes_on_exit"))
    body_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "module load uv")
    assert sbatch_idx < trap_idx < body_idx
    # the original local file is left untouched
    assert (tmp_path / "job.sh").read_text() == SAMPLE_JOB_SH


def test_upload_scripts_preprocesses_pre_script(monkeypatch, tmp_path) -> None:
    (tmp_path / "job.sh").write_text(SAMPLE_JOB_SH)
    (tmp_path / "pre.sh").write_text("module load uv\n")
    task = _task()
    task.pre_script = "pre.sh"
    job, runner = _job(monkeypatch, tmp_path, task=task)
    uploaded = _capture_uploads(runner)

    job.upload_scripts()

    assert f"./{STATUS_HELPER_NAME} PENDING" in uploaded["pre.sh"]
    assert "module load uv" in uploaded["pre.sh"]
    assert (tmp_path / "pre.sh").read_text() == "module load uv\n"


def test_job_honors_namespace_argument(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    runner_cls = MagicMock()
    monkeypatch.setattr("wes.jobs.job.SshRunner", runner_cls)
    monkeypatch.setattr("wes.jobs.status.SshRunner", runner_cls)

    job = Job(_task(), "hpc", namespace="ns_20260101_ab12")

    assert job.namespace == "ns_20260101_ab12"
    assert job.job_name == "my_task_ns_20260101_ab12"
    assert job.job_dir == "my_task/ns_20260101_ab12"
    assert job.status.namespace == "ns_20260101_ab12"


def test_job_construction_has_no_remote_side_effects(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    runner_cls = MagicMock()
    monkeypatch.setattr("wes.jobs.job.SshRunner", runner_cls)
    monkeypatch.setattr("wes.jobs.status.SshRunner", runner_cls)
    runner = runner_cls.return_value
    runner.run_command.side_effect = _run

    job = Job(_task(), "hpc")

    # discovery (JobScanner) constructs Jobs: it must not touch the server
    assert runner.run_command.call_args_list == []
    assert runner.create_dir.call_args_list == []
    assert runner.scp_to.call_args_list == []
    assert runner.scp_from.call_args_list == []

    # the remote dir and config upload happen in upload_scripts() instead
    (tmp_path / "job.sh").write_text(SAMPLE_JOB_SH)
    job.upload_scripts()
    assert runner.create_dir.call_args.args[0] == job.job_dir
    assert runner.scp_to.call_args_list  # config + job.sh


def test_execute_job_passes_resource_flags_to_sbatch(monkeypatch, tmp_path) -> None:
    task = _task()
    task.partition = "gpu"
    task.cpus = "4"
    task.gpus = "1"
    task.memory = "16G"
    task.time = "02:00:00"
    task.nodelist = "h86"
    job, runner = _job(monkeypatch, tmp_path, task=task)

    assert job.execute_job() is State.PENDING
    sbatch_cmd = next(c for c in _cmds(runner) if "sbatch" in c)
    for flag in (
        "--partition=gpu",
        "--cpus-per-task=4",
        "--gpus=1",
        "--mem=16G",
        "--time=02:00:00",
        "--nodelist=h86",
    ):
        assert flag in sbatch_cmd


def test_sync_pulls_status_files_too(monkeypatch, tmp_path) -> None:
    job, runner = _job(monkeypatch, tmp_path)
    pulled = []
    runner.scp_from.side_effect = (
        lambda r_path, tfile, cfile, r=False: pulled.append(f"{r_path}/{tfile}") or True
    )

    job.sync()

    assert f"{job.job_dir}/{STATUS_FILENAME}" in pulled
    assert f"{job.job_dir}/job_output.txt" in pulled
    assert f"{job.job_dir}/job_error.txt" in pulled
