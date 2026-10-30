from __future__ import annotations

from unittest.mock import MagicMock, patch

from wes.jobs.job import Job, JobInfo
from wes.jobs.status import STATUS_FILENAME, JobStatus, StatusFile, slurm_state
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


def _job(monkeypatch, tmp_path) -> tuple[Job, MagicMock]:
    """Build a Job with every ssh call mocked; returns (job, shared runner mock)."""
    monkeypatch.chdir(tmp_path)

    runner_cls = MagicMock()
    monkeypatch.setattr("wes.jobs.job.SshRunner", runner_cls)
    monkeypatch.setattr("wes.jobs.status.SshRunner", runner_cls)

    runner = runner_cls.return_value
    runner.run_command.side_effect = _run
    return Job(_task(), "hpc"), runner


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


def test_status_text_omits_empty_fields() -> None:
    text = JobStatus(task="t", namespace="n", job_name="j", ssh="hpc", updated="now").to_text()
    assert text.splitlines() == [
        "task=t",
        "namespace=n",
        "job_name=j",
        "ssh=hpc",
        "state=PENDING",
        "updated=now",
    ]


def test_status_from_text_unknown_state_is_pending() -> None:
    parsed = JobStatus.from_text("state=WAT")
    assert parsed.state is State.PENDING


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
    assert runner.run_command.call_args.kwargs["script"].startswith("task=t")


def test_status_file_read_returns_none_when_missing() -> None:
    with patch("wes.jobs.status.SshRunner") as runner_cls:
        runner_cls.return_value.run_command.return_value = (False, [])
        assert StatusFile("task/ns", "hpc").read() is None


def test_execute_job_writes_pending_with_job_id(monkeypatch, tmp_path) -> None:
    job, runner = _job(monkeypatch, tmp_path)
    state = job.execute_job()

    assert state is State.PENDING
    assert job.task.jobs_ids == ["4242"]
    writes = _status_writes(runner)
    assert len(writes) == 1
    assert writes[0].state is State.PENDING
    assert writes[0].job_id == "4242"


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


def test_execute_job_writes_failed_when_sbatch_fails(monkeypatch, tmp_path) -> None:
    job, runner = _job(monkeypatch, tmp_path)
    runner.run_command.side_effect = lambda cmd, script=None, **kw: (
        (False, ["nope"]) if "sbatch" in cmd else (True, [""])
    )

    assert job.execute_job() is State.FAILED
    writes = _status_writes(runner)
    assert writes[-1].state is State.FAILED
    assert writes[-1].message == "sbatch submission failed"


def test_set_info_writes_only_on_change(monkeypatch, tmp_path) -> None:
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

    writes = _status_writes(runner)
    assert len(writes) == 1
    assert writes[0].state is State.RUNNING
    assert writes[0].node == "h86"
    assert writes[0].partition == "gpu"
