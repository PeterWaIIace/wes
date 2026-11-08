"""Path-based job discovery over ssh, exercised against the mock cluster.

The mock runner executes the find/cat commands locally inside the sandbox
cluster dir, so the recursive wes.status search is tested for real:
hidden dirs are skipped, a dir containing wes.status is not descended into,
and the status file is read and stored on adoption.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from weshub import mock as weshub_mock
from weshub.config import Settings
from weshub.manager import Hub


def _write_status(cluster: Path, rel: str, ns: str, task: str = "demo", state: str = "COMPLETED"):
    d = cluster / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / "wes.status").write_text(
        f"task={task}\n"
        f"namespace={ns}\n"
        f"job_name={task}_{ns}\n"
        f"ssh=mock\n"
        f"state={state}\n"
        f"job_id=7\n"
        f"node=mock-node1\n"
        f"updated=2026-01-01 00:00:00\n"
    )


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


def _cluster() -> Path:
    return Path(weshub_mock.mock_config()["cluster_dir"])


def test_discover_path_finds_status_dirs_and_stops_branches(mock_hub):
    cluster = _cluster()
    _write_status(cluster, "jobs/alpha", "ns_alpha")
    _write_status(cluster, "jobs/alpha/nested", "ns_nested")  # branch must be pruned
    _write_status(cluster, "jobs/.hidden", "ns_hidden")  # hidden must be skipped
    _write_status(cluster, "jobs/beta/gamma", "ns_gamma")
    (cluster / "jobs/beta/README.md").write_text("not a job\n")

    adopted = mock_hub.discover("mock", "jobs")
    assert set(adopted) == {"ns_alpha", "ns_gamma"}

    jobs = {j["namespace"]: j for j in mock_hub.store.list_jobs()}
    assert set(jobs) == {"ns_alpha", "ns_gamma"}
    assert jobs["ns_alpha"]["discovered"] == 1
    assert jobs["ns_alpha"]["state"] == "COMPLETED"
    assert jobs["ns_alpha"]["job_id"] == "7"
    assert jobs["ns_alpha"]["node"] == "mock-node1"
    assert jobs["ns_gamma"]["task"] == "demo"

    # already-known jobs are not re-adopted
    assert mock_hub.discover("mock", "jobs") == []


def test_discover_path_base_dir_itself_is_job_dir(mock_hub):
    cluster = _cluster()
    _write_status(cluster, "solo", "ns_solo")
    _write_status(cluster, "solo/inner", "ns_inner")  # must not be reached

    adopted = mock_hub.discover("mock", "solo")
    assert adopted == ["ns_solo"]
    assert mock_hub.store.get_job("ns_inner") is None


def test_discover_path_dot_skips_hidden(mock_hub):
    cluster = _cluster()
    _write_status(cluster, "visible", "ns_vis")
    _write_status(cluster, ".mock/secret", "ns_secret")  # .mock is the mock state dir

    adopted = mock_hub.discover("mock", ".")
    assert adopted == ["ns_vis"]


def test_discover_path_absolute(mock_hub):
    cluster = _cluster()
    _write_status(cluster, "abs/a", "ns_a", state="RUNNING")
    _write_status(cluster, "abs/b/c", "ns_c", state="FAILED")

    adopted = mock_hub.discover("mock", str(cluster / "abs"))
    assert set(adopted) == {"ns_a", "ns_c"}
    jobs = {j["namespace"]: j for j in mock_hub.store.list_jobs()}
    assert jobs["ns_a"]["state"] == "RUNNING"
    assert jobs["ns_c"]["state"] == "FAILED"


def test_discover_path_missing_dir(mock_hub):
    assert mock_hub.discover("mock", "does/not/exist") == []


def test_discover_without_path_keeps_config_scan(mock_hub):
    # no wes.status / *_config.json anywhere -> legacy scan adopts nothing
    assert mock_hub.discover("mock") == []


def test_discovery_api_with_path(mock_hub):
    from fastapi.testclient import TestClient

    from weshub.app import create_app

    cluster = _cluster()
    _write_status(cluster, "api_jobs/x", "ns_x")

    app = create_app(mock_hub.settings)
    app.state.disable_lifecycle = True
    client = TestClient(app)

    res = client.post("/api/discovery/mock", params={"path": "api_jobs"})
    assert res.status_code == 200, res.text
    assert res.json()["adopted"] == ["ns_x"]

    # without path the endpoint keeps the legacy config scan
    res = client.post("/api/discovery/mock")
    assert res.status_code == 200
    assert res.json()["adopted"] == []


def test_cli_discover_subcommand(tmp_path, monkeypatch, capsys):
    from weshub import cli

    monkeypatch.chdir(tmp_path)  # cli.main chdirs into the data dir; restore on teardown
    data = tmp_path / "data"
    argv = [
        "wes-hub",
        "discover",
        "--ssh",
        "mock",
        "--path",
        "jobs",
        "--data-dir",
        str(data),
        "--mock",
    ]
    monkeypatch.setattr("sys.argv", argv)
    cli.main()  # sets up the empty mock sandbox, finds nothing
    assert "no new jobs" in capsys.readouterr().out

    _write_status(_cluster(), "jobs/x", "ns_x")
    cli.main()
    out = capsys.readouterr().out
    assert "adopted 1 job(s)" in out
    assert "ns_x" in out
    weshub_mock.deactivate()
