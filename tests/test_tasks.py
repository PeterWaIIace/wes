from __future__ import annotations

from wes.jobs.query import JobsQuery
from wes.states import State
from wes.tasks import Task, _strip_ansi


def test_task_defaults() -> None:
    task = Task(name="test", git_url="ssh://git@example.com/repo.git", path=".")
    assert task.name == "test"
    assert task.ssh_config == ""
    assert task.branch == ""
    assert task.job_script is None
    assert task.pre_script is None
    assert task.cleanup_git is False
    assert task.status is State.PENDING
    assert task.jobs_ids == []
    assert task.artifacts == []


def test_task_custom_fields() -> None:
    task = Task(
        name="train",
        git_url="ssh://git@example.com/repo.git",
        path="/scratch",
        ssh_config="gpu",
        branch="main",
        job_script="train.sh",
        pre_script="setup.sh",
        artifacts=["results", "checkpoints"],
        cleanup=True,
    )
    assert task.ssh_config == "gpu"
    assert task.branch == "main"
    assert task.job_script == "train.sh"
    assert task.pre_script == "setup.sh"
    assert task.artifacts == ["results", "checkpoints"]
    assert task.cleanup_git is True


def test_task_with_initial_state() -> None:
    task = Task(
        name="resumed",
        git_url="ssh://git@example.com/repo.git",
        path=".",
        active_jobs=["12345"],
        state=State.RUNNING,
    )
    assert task.status is State.RUNNING
    assert task.jobs_ids == ["12345"]


def test_no_alive_jobs_empty() -> None:
    query = JobsQuery("fake-ssh")
    assert query.has_alive_jobs([]) is False


def test_no_alive_jobs_no_ids() -> None:
    query = JobsQuery("fake-ssh")
    assert query.has_alive_jobs(["12345"]) is False


def test_strip_ansi() -> None:
    assert _strip_ansi("hello") == "hello"
    assert _strip_ansi("\x1b[31mred\x1b[0m") == "red"
    assert _strip_ansi("\x1b[1;32mbold green\x1b[0m") == "bold green"
    assert _strip_ansi("") == ""


def test_task_slurm_fields_default_empty() -> None:
    task = Task(name="test", git_url="ssh://git@example.com/repo.git", path=".")
    assert task.partition == ""
    assert task.cpus == ""
    assert task.gpus == ""
    assert task.memory == ""
    assert task.time == ""
    assert task.nodelist == ""


def test_task_slurm_fields_set() -> None:
    task = Task(
        name="gpu-job",
        git_url="ssh://git@example.com/repo.git",
        path=".",
        partition="gpu",
        cpus="8",
        gpus="2",
        memory="32G",
        time="4:00:00",
        nodelist="gpu0,gpu1",
    )
    assert task.partition == "gpu"
    assert task.cpus == "8"
    assert task.gpus == "2"
    assert task.memory == "32G"
    assert task.time == "4:00:00"
    assert task.nodelist == "gpu0,gpu1"
