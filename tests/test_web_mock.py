from __future__ import annotations

import pytest
from fastapi import HTTPException

from web.models import ClusterData
from web.routers.cluster import api_get_cluster, api_get_nodes
from web.routers.jobs import (
    get_job,
    get_job_logs,
    get_job_remote_artifacts,
    get_job_remote_csv,
    get_job_remote_logs,
    list_jobs,
    serve_job_remote_artifact,
)
from web.routers.tasks import get_task, list_tasks
from web.services.config import parse_wes_files
from web.services.mock import (
    MOCK_TASKS,
    mock_cluster_data,
    mock_enabled,
    mock_tasks,
    mock_user_jobs,
)

VALID_NODE_STATES = {"idle", "alloc", "mix", "drain", "down"}
VALID_JOB_STATES = {"RUNNING", "PENDING", "COMPLETED", "FAILED", "CANCELLED"}


class TestMockClusterData:
    def test_structure(self) -> None:
        data = mock_cluster_data()
        assert data["ssh"] == "mock"
        assert len(data["nodes"]) == 32
        assert len(data["capacity"]) == 32
        assert data["jobs"]

    def test_nodes_shape(self) -> None:
        for node in mock_cluster_data()["nodes"]:
            assert {"name", "partition", "state", "cpus", "gpus", "memory", "reason"} <= node.keys()
            assert node["state"] in VALID_NODE_STATES
            assert node["cpus"].isdigit()
            assert node["gpus"].isdigit()

    def test_capacity_invariants(self) -> None:
        for cap in mock_cluster_data()["capacity"]:
            assert cap["cpu_alloc"] + cap["cpu_free"] == cap["cpu_total"]
            assert cap["mem_alloc_mb"] + cap["mem_free_mb"] == cap["mem_total_mb"]
            assert cap["gpu_alloc"] + cap["gpu_free"] == cap["gpu_total"]
            assert cap["cpu_alloc"] >= 0 and cap["mem_alloc_mb"] >= 0

    def test_jobs_shape(self) -> None:
        for job in mock_cluster_data()["jobs"]:
            assert {
                "job_id",
                "user",
                "name",
                "state",
                "priority",
                "time",
                "nodes",
                "partition",
                "reason",
                "cpus",
                "memory",
            } <= job.keys()
            assert job["state"] in VALID_JOB_STATES
            assert job["job_id"].isdigit()

    def test_node_alloc_consistent_with_running_jobs(self) -> None:
        data = mock_cluster_data()
        by_name = {cap["name"]: cap for cap in data["capacity"]}
        for job in data["jobs"]:
            if job["state"] != "RUNNING":
                continue
            for node_name in job["nodes"].split(","):
                cap = by_name[node_name]
                assert int(job["cpus"]) <= cap["cpu_alloc"]


class TestMockTasks:
    def test_structure(self) -> None:
        tasks = mock_tasks()
        assert len(tasks) == len(MOCK_TASKS)
        assert len(tasks) > 0

    def test_required_fields(self) -> None:
        for task in mock_tasks():
            assert task.name
            assert task.git_url
            assert task.ssh == "mock"
            assert task.job
            assert task.partition in {"gpu", "cpu", "himem", "short"}
            assert task.cpus.isdigit()
            assert task.gpus.isdigit()

    def test_unique_names(self) -> None:
        names = [t.name for t in mock_tasks()]
        assert len(names) == len(set(names))

    def test_status_consistent_with_user_jobs(self) -> None:
        jobs_by_name = {j.task_name: j for j in mock_user_jobs()}
        for task in mock_tasks():
            job = jobs_by_name.get(task.name)
            if job is None:
                assert task.status == ""
                assert task.run_id == ""
            else:
                assert task.status == job.state
                assert task.run_id == job.run_id


class TestMockUserJobs:
    def test_shape(self) -> None:
        jobs = mock_user_jobs()
        assert jobs
        for job in jobs:
            assert job.job_id.isdigit()
            assert job.state in VALID_JOB_STATES
            assert job.ssh == "mock"
            assert job.run_id == f"run-{job.job_id}"

    def test_unique_job_ids(self) -> None:
        job_ids = [j.job_id for j in mock_user_jobs()]
        assert len(job_ids) == len(set(job_ids))

    def test_states_are_static(self) -> None:
        first = [(j.job_id, j.state) for j in mock_user_jobs()]
        second = [(j.job_id, j.state) for j in mock_user_jobs()]
        assert first == second

    def test_known_tasks_have_rich_fields(self) -> None:
        task_names = {t.name for t in mock_tasks()}
        for job in mock_user_jobs():
            if job.task_name in task_names:
                assert job.git_url
                assert job.branch
                assert job.job


class TestMockEnabled:
    def test_enabled(self, monkeypatch) -> None:
        monkeypatch.setenv("WES_MOCK", "1")
        assert mock_enabled()

    def test_disabled_by_default(self, monkeypatch) -> None:
        monkeypatch.delenv("WES_MOCK", raising=False)
        assert not mock_enabled()

    def test_falsey_values(self, monkeypatch) -> None:
        monkeypatch.setenv("WES_MOCK", "0")
        assert not mock_enabled()


class TestRouter:
    def test_cluster_mock_when_enabled(self, monkeypatch) -> None:
        monkeypatch.setenv("WES_MOCK", "1")
        data = api_get_cluster(ssh="")
        assert data["ssh"] == "mock"
        assert data["nodes"]
        assert "error" not in data or not data["error"]

    def test_nodes_mock_when_enabled(self, monkeypatch) -> None:
        monkeypatch.setenv("WES_MOCK", "1")
        result = api_get_nodes(ssh="")
        assert isinstance(result, ClusterData)
        assert result.ssh == "mock"
        assert len(result.nodes) == 32
        assert result.error == ""

    def test_cluster_without_ssh_errors_when_disabled(self, monkeypatch) -> None:
        monkeypatch.delenv("WES_MOCK", raising=False)
        data = api_get_cluster(ssh="")
        assert data["error"]

    def test_nodes_without_ssh_errors_when_disabled(self, monkeypatch) -> None:
        monkeypatch.delenv("WES_MOCK", raising=False)
        result = api_get_nodes(ssh="")
        assert result.error

    def test_tasks_mock_when_enabled(self, monkeypatch) -> None:
        monkeypatch.setenv("WES_MOCK", "1")
        tasks = list_tasks()
        assert tasks == mock_tasks()
        assert tasks

    def test_get_task_mock_when_enabled(self, monkeypatch) -> None:
        monkeypatch.setenv("WES_MOCK", "1")
        name = mock_tasks()[0].name
        task = get_task(name)
        assert task.name == name
        assert task.ssh == "mock"

    def test_get_task_unknown_mock_when_enabled(self, monkeypatch) -> None:
        monkeypatch.setenv("WES_MOCK", "1")
        with pytest.raises(HTTPException) as exc:
            get_task("no_such_task")
        assert exc.value.status_code == 404

    def test_tasks_mock_even_without_wes_files(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("WES_MOCK", "1")
        monkeypatch.chdir(tmp_path)
        assert parse_wes_files() == mock_tasks()

    def test_jobs_mock_when_enabled(self, monkeypatch) -> None:
        monkeypatch.setenv("WES_MOCK", "1")
        jobs = list_jobs()
        assert jobs == mock_user_jobs()
        assert jobs

    def test_get_job_mock_when_enabled(self, monkeypatch) -> None:
        monkeypatch.setenv("WES_MOCK", "1")
        job_id = mock_user_jobs()[0].job_id
        job = get_job(job_id)
        assert job.job_id == job_id
        assert job.ssh == "mock"
        assert job.state in VALID_JOB_STATES

    def test_get_job_unknown_mock_when_enabled(self, monkeypatch) -> None:
        monkeypatch.setenv("WES_MOCK", "1")
        with pytest.raises(HTTPException) as exc:
            get_job("999999999")
        assert exc.value.status_code == 404


class TestMockJobDetails:
    def test_logs_mock_when_enabled(self, monkeypatch) -> None:
        monkeypatch.setenv("WES_MOCK", "1")
        job_id = mock_user_jobs()[0].job_id
        logs = get_job_remote_logs(job_id)
        assert {"stdout", "stderr", "pre_run"} <= logs.keys()
        assert job_id in logs["stdout"]

    def test_remote_logs_unknown_404_when_enabled(self, monkeypatch) -> None:
        monkeypatch.setenv("WES_MOCK", "1")
        with pytest.raises(HTTPException) as exc:
            get_job_remote_logs("999999999")
        assert exc.value.status_code == 404

    def test_local_logs_mock_when_enabled(self, monkeypatch) -> None:
        monkeypatch.setenv("WES_MOCK", "1")
        job_id = mock_user_jobs()[0].job_id
        logs = get_job_logs(job_id)
        assert logs.stdout
        assert job_id in logs.stdout

    def test_artifacts_mock_when_enabled(self, monkeypatch) -> None:
        monkeypatch.setenv("WES_MOCK", "1")
        job_id = mock_user_jobs()[0].job_id
        artifacts = get_job_remote_artifacts(job_id)
        assert artifacts
        for a in artifacts:
            assert {"name", "kind", "path", "size"} <= a.keys()
            assert a["name"]
            assert a["kind"]
            assert isinstance(a["size"], int)
            assert a["size"] > 0

    def test_artifact_content_mock_when_enabled(self, monkeypatch) -> None:
        monkeypatch.setenv("WES_MOCK", "1")
        job_id = mock_user_jobs()[0].job_id
        artifacts = get_job_remote_artifacts(job_id)
        csv_path = next(a["path"] for a in artifacts if a["path"].endswith(".csv"))
        resp = serve_job_remote_artifact(job_id, csv_path)
        assert resp.status_code == 200
        assert resp.media_type == "text/csv"
        assert b"reward" in resp.body

        png_path = next(a["path"] for a in artifacts if a["path"].endswith(".png"))
        resp = serve_job_remote_artifact(job_id, png_path)
        assert resp.status_code == 200
        assert resp.media_type == "image/png"

    def test_artifact_unknown_404_when_enabled(self, monkeypatch) -> None:
        monkeypatch.setenv("WES_MOCK", "1")
        with pytest.raises(HTTPException) as exc:
            serve_job_remote_artifact("999999999", "results/metrics.csv")
        assert exc.value.status_code == 404

    def test_progress_csv_mock_when_enabled(self, monkeypatch) -> None:
        monkeypatch.setenv("WES_MOCK", "1")
        job_id = mock_user_jobs()[0].job_id
        progress = get_job_remote_csv(job_id)
        assert progress.columns
        assert progress.rows
        assert any("timestep" in c for c in progress.columns)
        assert any("reward" in c for c in progress.columns)
        assert all(len(r) == len(progress.columns) for r in progress.rows)
