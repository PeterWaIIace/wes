"""End-to-end flow test with the mock cluster: no ssh, no real SLURM.

Runs the full loop the mock exists for:
pipeline -> dispatch -> clone -> pre-script -> sbatch -> wes.status
-> monitor tick -> COMPLETED -> artifacts pulled into results/.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
import yaml

from weshub import mock as weshub_mock
from weshub.config import Settings
from weshub.manager import Hub


@pytest.fixture()
def mock_hub(tmp_path, monkeypatch):
    data = tmp_path / "data"
    settings = Settings(data_dir=data, ssh_timeout=10.0)
    settings.ensure_dirs()
    monkeypatch.chdir(data)  # wes resolves results/ against the CWD
    weshub_mock.setup(settings)
    weshub_mock.activate()
    yield Hub(settings)
    weshub_mock.deactivate()


def test_mock_full_flow(mock_hub):
    hub = mock_hub
    pipeline = weshub_mock.seed_demo_pipeline(hub)
    assert pipeline is not None
    assert pipeline["name"] == "mock-demo"

    run = hub.trigger_run(pipeline["id"], trigger="manual")
    assert run["status"] == ""

    # drive the monitor until the run finishes (mock job sleeps ~4s)
    deadline = time.time() + 60
    while time.time() < deadline:
        hub.monitor_tick()
        run_now = hub.store.get_run(run["id"])
        jobs = hub.store.list_jobs(run["id"])
        if run_now["status"] == "COMPLETED" and jobs and jobs[0]["artifacts_pulled"]:
            break
        if run_now["finished_at"]:
            pytest.fail(f"run finished badly: run={run_now} jobs={jobs}")
        time.sleep(0.5)
    else:
        pytest.fail(f"run did not finish: {hub.store.list_jobs(run['id'])}")

    jobs = hub.store.list_jobs(run["id"])
    assert len(jobs) == 1
    job = jobs[0]
    assert job["state"] == "COMPLETED"
    assert job["job_id"], "slurm job id missing"
    assert job["node"] == "mock-node1"
    assert job["updated"], "wes.status never read"

    # cluster snapshot from the mock cluster
    hub._refresh_cluster("mock", max_age=0.0)
    cluster = hub.clusters["mock"]
    assert any(n["name"] == "mock-node1" for n in cluster["nodes"])

    # artifacts landed in the local results tree (server CWD = data dir)
    artifact_files = list((Path() / "results").rglob("summary.txt"))
    assert artifact_files, "no summary.txt pulled into results/"
    content = artifact_files[0].read_text()
    assert "results from mock job" in content

    # discovery finds the job config on the "cluster"
    adopted = hub.discover("mock")
    assert not adopted, "already-tracked job re-adopted"


def test_mock_status_file_matches_wes_protocol(mock_hub):
    hub = mock_hub
    pipeline = weshub_mock.seed_demo_pipeline(hub)
    hub.trigger_run(pipeline["id"])
    deadline = time.time() + 60
    while time.time() < deadline:
        hub.monitor_tick()
        jobs = hub.store.list_jobs(pipeline["id"])
        if jobs and jobs[0]["state"] in ("COMPLETED", "FAILED", "CANCELLED"):
            break
        time.sleep(0.5)
    else:
        pytest.fail(f"job did not complete: {hub.store.list_jobs(pipeline['id'])}")
    assert jobs[0]["state"] == "COMPLETED"

    # the raw wes.status written by the job scripts lives in the sandbox
    cluster = Path(weshub_mock.mock_config()["cluster_dir"])
    status_files = list(cluster.rglob("wes.status"))
    assert status_files
    fields = yaml.safe_load(status_files[0].read_text())
    assert fields["state"] == "COMPLETED"
    assert fields["namespace"]
    assert fields["job_id"]

    # and the job config the discovery protocol uses
    configs = list(cluster.rglob("*_config.json"))
    assert configs
    config = json.loads(configs[0].read_text())
    assert config["job"]["namespace"]
    assert config["task"]["name"] == "example_run"
