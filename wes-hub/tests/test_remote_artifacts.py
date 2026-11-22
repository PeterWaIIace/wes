from pathlib import Path

import pytest
from wes.jobs.status import JobStatus
from wes.states import State
from wes.tasks import Task

from weshub import mock
from weshub.config import Settings
from weshub.manager import DiscoveredJob, Hub, HubError, JobRecord


@pytest.fixture
def artifact_hub(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data")
    settings.ensure_dirs()
    monkeypatch.chdir(settings.data_dir)
    mock.setup(settings)
    mock.activate()
    hub = Hub(settings)
    cluster = Path(mock.mock_config()["cluster_dir"])
    root = "sweep/ns/swarm-gym"
    remote = cluster / root / "results"
    remote.mkdir(parents=True)
    (remote / "status_2.png").write_bytes(b"chart")
    (remote / "report.csv").write_text("value\n1\n")
    (remote / "unselected.bin").write_bytes(b"large results")
    (remote / "nested").mkdir()
    (remote / "nested" / "extra.csv").write_text("extra")
    task = Task(name="sweep", git_url="https://example.com/swarm-gym.git", ssh_config="mock",
                artifacts=["results"], progress_artifacts=["results/status_{array_index}.png"])
    status = JobStatus("sweep", "ns_array_2", "job", "mock", state=State.COMPLETED,
                       array_index="2", parent_namespace="ns", job_id="42", artifact_dir=root)
    job_dir = "sweep/ns/tasks/2"
    directory = cluster / job_dir
    directory.mkdir(parents=True)
    (directory / "wes.status").write_text(status.to_text())
    job = DiscoveredJob(task, "mock", status.namespace, status.job_name, job_dir, status)
    rec = JobRecord(job, None, None, True)
    hub._register(job, rec)
    hub._store_status(rec, status)
    yield hub
    for future in hub._transfers.values():
        future.result(timeout=10)
    hub.stop()
    mock.deactivate()


def test_remote_tree_browses_without_downloading(artifact_hub):
    hub = artifact_hub
    roots = hub.remote_artifact_tree("ns_array_2")
    assert [entry["path"] for entry in roots["entries"]] == ["results"]
    children = hub.remote_artifact_tree("ns_array_2", "results")
    assert {entry["name"] for entry in children["entries"]} == {
        "status_2.png", "report.csv", "unselected.bin", "nested"
    }
    assert not list(hub.settings.results_dir.rglob("report.csv"))
    assert not list(hub.settings.results_dir.rglob("extra.csv"))


def test_selected_pull_downloads_only_requested_file(artifact_hub):
    hub = artifact_hub
    hub.pull_job("ns_array_2", ["results/report.csv"])
    hub._transfers["ns_array_2"].result(timeout=10)
    assert list(hub.settings.results_dir.rglob("report.csv"))
    assert not list(hub.settings.results_dir.rglob("unselected.bin"))
    assert not list(hub.settings.results_dir.rglob("status_2.png"))
    page = hub.remote_artifact_tree("ns_array_2", "results")
    report = next(entry for entry in page["entries"] if entry["name"] == "report.csv")
    assert report["downloaded"]
    assert report["local_path"].endswith("results/report.csv")


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", "other/file.txt"])
def test_remote_tree_rejects_paths_outside_artifacts(artifact_hub, path):
    with pytest.raises(HubError):
        artifact_hub.remote_artifact_tree("ns_array_2", path)


def test_completed_job_refreshes_progress_without_full_result_sync(artifact_hub):
    hub = artifact_hub
    hub.monitor_tick()
    hub._transfers["ns_array_2"].result(timeout=10)
    assert list(hub.settings.results_dir.rglob("status_2.png"))
    assert not list(hub.settings.results_dir.rglob("report.csv"))
    assert not list(hub.settings.results_dir.rglob("unselected.bin"))
    previews = hub.enrich_job(hub.store.get_job("ns_array_2"))["progress_artifacts"]
    assert len(previews) == 1
    assert previews[0]["path"].endswith("status_2.png")


def test_remote_artifact_api_accepts_selected_file_body(artifact_hub):
    from fastapi.testclient import TestClient
    from weshub import api
    from weshub.app import create_app

    app = create_app(artifact_hub.settings)
    app.state.disable_lifecycle = True
    api.set_hub(artifact_hub)
    client = TestClient(app)
    response = client.get("/api/jobs/ns_array_2/artifacts", params={"path": "results"})
    assert response.status_code == 200
    response = client.post("/api/jobs/ns_array_2/pull", json={"paths": ["results/report.csv"]})
    assert response.status_code == 200
    artifact_hub._transfers["ns_array_2"].result(timeout=10)
    assert list(artifact_hub.settings.results_dir.rglob("report.csv"))
