from __future__ import annotations

import yaml

from wes.cache import JobCache
from wes.states import State
from wes.tasks import Task


def test_cache_empty_on_start() -> None:
    cache = JobCache()
    try:
        assert cache.get_all() == {}
    finally:
        cache.close()


def test_cache_set_and_get() -> None:
    cache = JobCache()
    try:
        cache.set("job-1", {"state": "RUNNING", "jobs_ids": ["123"]})

        result = cache.get_all()
        assert "job-1" in result
        assert result["job-1"]["state"] == "RUNNING"
        assert result["job-1"]["jobs_ids"] == ["123"]
    finally:
        cache.close()


def test_cache_remove() -> None:
    cache = JobCache()
    try:
        cache.set("job-1", {"state": "RUNNING"})
        cache.remove("job-1")

        assert cache.get_all() == {}
    finally:
        cache.close()


def test_cache_remove_nonexistent() -> None:
    cache = JobCache()
    try:
        cache.remove("nonexistent")
    finally:
        cache.close()


def test_cache_persists_to_disk() -> None:
    cache = JobCache()
    try:
        cache.set("job-1", {"state": "PENDING"})
        assert cache._cache_file.exists()
        loaded = yaml.safe_load(cache._cache_file.read_text(encoding="utf-8"))
        assert "job-1" in loaded.get("tasks", {})
    finally:
        cache.close()


def test_cache_overwrites() -> None:
    cache = JobCache()
    try:
        cache.set("job-1", {"state": "PENDING"})
        cache.set("job-1", {"state": "RUNNING"})

        assert cache.get_all()["job-1"]["state"] == "RUNNING"
    finally:
        cache.close()


def test_task_to_cache_data() -> None:
    task = Task(
        name="test",
        git_url="ssh://git@example.com/repo.git",
        path=".",
        ssh_config="hpc",
        branch="main",
        job="job.sh",
        run=["setup.sh"],
        post="cleanup.sh",
        artifacts=["results"],
        cleanup=True,
        state=State.RUNNING,
        active_jobs=["12345"],
    )

    data = JobCache.task_to_cache_data(task)
    assert data["state"] == "RUNNING"
    assert data["jobs_ids"] == ["12345"]
    assert data["git_url"] == "ssh://git@example.com/repo.git"
    assert data["ssh"] == "hpc"
    assert data["branch"] == "main"
    assert data["job"] == "job.sh"
    assert data["run"] == ["setup.sh"]
    assert data["post"] == "cleanup.sh"
    assert data["artifacts"] == ["results"]
    assert data["cleanup"] is True


def test_cached_task_roundtrip() -> None:
    original = Task(
        name="roundtrip",
        git_url="ssh://git@example.com/repo.git",
        path="/scratch",
        ssh_config="gpu",
        branch="develop",
        job="train.sh",
        run=["a.sh", "b.sh"],
        post="cleanup.sh",
        artifacts=["results"],
        cleanup=True,
        state=State.RUNNING,
        active_jobs=["999"],
    )

    data = JobCache.task_to_cache_data(original)
    restored = JobCache.cached_task("roundtrip", data)

    assert restored.name == "roundtrip"
    assert restored.git_url == original.git_url
    assert restored.branch == original.branch
    assert restored.path == original.path
    assert restored.ssh_config == original.ssh_config
    assert restored.job == original.job
    assert restored.run == original.run
    assert restored.post == original.post
    assert restored.artifacts == original.artifacts
    assert restored.cleanup_git is original.cleanup_git
    assert restored.status is State.RUNNING
    assert restored.jobs_ids == ["999"]
