from __future__ import annotations

from web.cache import JobCache, task_to_cache_data


class TestJobCache:
    def test_empty_cache(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        cache = JobCache()
        assert cache.get_all() == {}
        assert cache.get("nonexistent") is None

    def test_set_and_get(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        cache = JobCache()
        data = {"task_name": "test", "state": "RUNNING"}
        cache.set("run-123", data)
        result = cache.get("run-123")
        assert result is not None
        assert result["task_name"] == "test"
        assert result["state"] == "RUNNING"

    def test_remove(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        cache = JobCache()
        cache.set("run-1", {"task_name": "a"})
        cache.remove("run-1")
        assert cache.get("run-1") is None

    def test_persistence(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        cache1 = JobCache()
        cache1.set("run-1", {"task_name": "test", "state": "RUNNING"})
        del cache1

        cache2 = JobCache()
        assert cache2.get("run-1") is not None
        assert cache2.get("run-1")["task_name"] == "test"

    def test_find_by_task_name(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        cache = JobCache()
        cache.set("run-1", {"task_name": "alpha", "state": "RUNNING"})
        cache.set("run-2", {"task_name": "beta", "state": "COMPLETED"})
        cache.set("run-3", {"task_name": "alpha", "state": "PENDING"})

        results = cache.find_by_task_name("alpha")
        assert len(results) == 2
        ids = {r[0] for r in results}
        assert ids == {"run-1", "run-3"}

    def test_clean_for_task_names(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        cache = JobCache()
        cache.set("run-1", {"task_name": "alpha", "state": "RUNNING"})
        cache.set("run-2", {"task_name": "beta", "state": "COMPLETED"})

        removed = cache.clean_for_task_names({"alpha"})
        assert len(removed) == 1
        assert removed[0][0] == "run-1"
        assert cache.get("run-1") is None
        assert cache.get("run-2") is not None

    def test_overwrite(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        cache = JobCache()
        cache.set("run-1", {"task_name": "a", "state": "PENDING"})
        cache.set("run-1", {"task_name": "a", "state": "RUNNING"})
        result = cache.get("run-1")
        assert result["state"] == "RUNNING"


class TestTaskToCacheData:
    def test_basic_conversion(self) -> None:
        task = {
            "name": "my-task",
            "state": "RUNNING",
            "jobs_ids": ["123", "456"],
            "git_url": "ssh://git@example.com/repo.git",
            "branch": "main",
            "ssh": "hpc",
            "path": "/scratch",
            "job": "job.sh",
            "run": ["setup.sh"],
            "post": "cleanup.sh",
            "artifacts": ["results"],
            "cleanup": True,
            "partition": "gpu",
            "cpus": "8",
            "gpus": "2",
            "memory": "32G",
            "time": "4:00:00",
            "nodelist": "gpu0",
            "run_id": "abc123",
        }
        data = task_to_cache_data(task)
        assert data["task_name"] == "my-task"
        assert data["state"] == "RUNNING"
        assert data["jobs_ids"] == ["123", "456"]
        assert data["ssh"] == "hpc"
        assert data["run_id"] == "abc123"
        assert data["run"] == ["setup.sh"]
