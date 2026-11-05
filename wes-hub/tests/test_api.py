from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from weshub.app import create_app
from weshub.config import Settings

WES_YAML = """sequence:
  - demo_task:
      git_url: ssh://git@example.com/user/demo.git
      branch: main
      ssh: hpc
      job: job.sh
      artifacts: [results]
"""

ASSETS = {"job.sh": "#!/bin/bash\necho hello\n"}


class FakeStatus:
    def __init__(self, namespace):
        self.task = "demo_task"
        self.namespace = namespace
        self.job_name = "demo_task_" + namespace
        self.ssh = "hpc"
        self.state = SimpleNamespace(value="RUNNING")
        self.job_id = "42"
        self.node = "h86"
        self.partition = "gpu"
        self.message = ""
        self.updated = "2026-01-15 04:30:00"


class FakeJob:
    """Stands in for wes.jobs.job.Job so no ssh is attempted."""

    instances: list[FakeJob] = []

    def __init__(self, task, ssh_config, namespace=None):
        self.task = task
        self.ssh_config = ssh_config
        self.namespace = namespace or "ns_1"
        self.job_name = f"{task.name}_{self.namespace}"
        self.artifacts = []
        self.status_files = []
        self.status = FakeStatus(self.namespace)
        FakeJob.instances.append(self)

    def upload_scripts(self):
        pass

    def execute_job(self):
        class S:
            value = "PENDING"

        return S()

    def pull_status(self):
        self.status.state = SimpleNamespace(value="COMPLETED")


class FakeScanner:
    def __init__(self, ssh_config):
        pass

    def scan(self):
        return []


class FakeCluster:
    def __init__(self, ssh_config):
        pass

    def get_nodes(self):
        return []

    def get_jobs(self):
        return []


def make_client(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    app = create_app(settings)
    app.state.disable_lifecycle = True
    return TestClient(app), app


@pytest.fixture(autouse=True)
def _chdir(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(data)


def test_root_serves_ui(tmp_path):
    client, _ = make_client(tmp_path)
    res = client.get("/")
    assert res.status_code == 200
    assert "wes" in res.text


def test_create_pipeline_valid(tmp_path):
    client, _ = make_client(tmp_path)
    res = client.post(
        "/api/pipelines",
        json={"name": "demo", "wes_yaml": WES_YAML, "ssh": "hpc", "assets": ASSETS},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "demo"
    assert (tmp_path / "data" / "pipelines" / "1" / "pipeline.wes").exists()


def test_create_pipeline_invalid_yaml(tmp_path):
    client, _ = make_client(tmp_path)
    res = client.post("/api/pipelines", json={"name": "x", "wes_yaml": "not: [valid"})
    assert res.status_code == 400


def test_create_pipeline_missing_assets(tmp_path):
    client, _ = make_client(tmp_path)
    res = client.post("/api/pipelines", json={"name": "demo", "wes_yaml": WES_YAML})
    assert res.status_code == 400
    assert "job.sh" in res.json()["detail"]


def test_create_pipeline_bad_cron(tmp_path):
    client, _ = make_client(tmp_path)
    res = client.post(
        "/api/pipelines",
        json={"name": "demo", "wes_yaml": WES_YAML, "assets": ASSETS, "cron": "sometimes"},
    )
    assert res.status_code == 400


def test_dispatch_and_monitor(tmp_path):
    client, app = make_client(tmp_path)
    client.post(
        "/api/pipelines",
        json={
            "name": "demo",
            "wes_yaml": WES_YAML,
            "ssh": "hpc",
            "assets": ASSETS,
            "cron": "0 4 * * *",
        },
    )
    with (
        patch("weshub.manager.Job", FakeJob),
        patch("weshub.manager.JobScanner", FakeScanner),
        patch("weshub.manager.Cluster", FakeCluster),
    ):
        FakeJob.instances.clear()
        res = client.post("/api/pipelines/1/dispatch")
        assert res.status_code == 201, res.text
        run = res.json()
        for _ in range(50):
            jobs = client.get("/api/jobs").json()
            if jobs:
                break
            time.sleep(0.05)
        assert jobs and jobs[0]["run_id"] == run["id"]
        assert jobs[0]["task"] == "demo_task"

        # run the monitor once: status becomes COMPLETED, results marked pulled
        from weshub import api as api_mod

        api_hub = api_mod.get_hub()
        api_hub.monitor_tick()
        jobs = client.get("/api/jobs").json()
        assert jobs[0]["state"] == "COMPLETED"
        assert jobs[0]["artifacts_pulled"] == 1

        run = client.get(f"/api/runs/{run['id']}").json()
        assert run["status"] == "success"
        assert run["finished_at"] is not None


def test_state_endpoint(tmp_path):
    client, _ = make_client(tmp_path)
    client.post("/api/pipelines", json={"name": "demo", "wes_yaml": WES_YAML, "assets": ASSETS})
    state = client.get("/api/state").json()
    assert len(state["pipelines"]) == 1
    assert state["pipelines"][0]["name"] == "demo"
