from __future__ import annotations

from wes.states import State
from wes.tasks import Task, _strip_ansi


def test_task_defaults() -> None:
    task = Task(name="test", git_url="ssh://git@example.com/repo.git", path=".")
    assert task.name == "test"
    assert task.ssh_config == ""
    assert task.branch == ""
    assert task.job is None
    assert task.post == ""
    assert task.cleanup_git is False
    assert task.status is State.PENDING
    assert task.jobs_ids == []
    assert task.artifacts == []
    assert task.run == []


def test_task_custom_fields() -> None:
    task = Task(
        name="train",
        git_url="ssh://git@example.com/repo.git",
        path="/scratch",
        ssh_config="gpu",
        branch="main",
        job="train.sh",
        run=["setup.sh", "data.sh"],
        post="cleanup.sh",
        artifacts=["results", "checkpoints"],
        cleanup=True,
    )
    assert task.ssh_config == "gpu"
    assert task.branch == "main"
    assert task.job == "train.sh"
    assert task.run == ["setup.sh", "data.sh"]
    assert task.post == "cleanup.sh"
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


def test_task_no_alive_jobs_empty() -> None:
    task = Task(name="test", git_url="ssh://git@example.com/repo.git", path=".")
    assert task.has_alive_jobs() is False


def test_strip_ansi() -> None:
    assert _strip_ansi("hello") == "hello"
    assert _strip_ansi("\x1b[31mred\x1b[0m") == "red"
    assert _strip_ansi("\x1b[1;32mbold green\x1b[0m") == "bold green"
    assert _strip_ansi("") == ""
