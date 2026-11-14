"""Path-based job discovery over ssh, exercised against the mock cluster.

The mock runner executes the find/cat commands locally inside the sandbox
cluster dir, so the recursive wes.status search is tested for real:
hidden dirs are skipped, a dir containing wes.status is not descended into,
and the status file is read and stored on adoption.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from wes.jobs.status import StatusFile

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


def test_array_directories_are_discovered_as_separate_jobs(mock_hub):
    cluster = _cluster()
    for index in ("2", "3"):
        relative_dir = f"sweep/ns/tasks/{index}"
        _write_status(cluster, relative_dir, "ns")
        with (cluster / relative_dir / "wes.status").open("a") as status_file:
            status_file.write(f"array_index={index}\nparent_namespace=ns\n")

    adopted = mock_hub.discover("mock", "sweep")

    assert set(adopted) == {"ns_array_2", "ns_array_3"}
    for index in ("2", "3"):
        namespace = f"ns_array_{index}"
        record = mock_hub.registry[namespace]
        assert record.job.job_dir == f"sweep/ns/tasks/{index}"
        assert record.job.pull_status()
        assert record.job.status.namespace == namespace
        assert mock_hub.store.get_job(namespace)["state"] == "COMPLETED"
    assert mock_hub.discover("mock", "sweep") == []
    assert mock_hub.store.get_job("ns") is None


def test_array_job_uses_parent_artifacts_from_task_directory(mock_hub):
    cluster = _cluster()
    relative_dir = "sweep/ns/tasks/2"
    _write_status(cluster, relative_dir, "ns_array_2")
    with (cluster / relative_dir / "wes.status").open("a") as status_file:
        status_file.write("array_index=2\nparent_namespace=ns\n")
    (cluster / "sweep/ns/sweep_config.json").write_text(
        '{"task": {"name": "sweep", "git_url": "https://example.com/repo.git", '
        '"artifacts": ["results"], "progress_artifacts": ["results/progress.png"]}}'
    )
    mock_hub.discover("mock", "sweep")
    job = mock_hub.registry["ns_array_2"].job

    assert len(job.artifacts) == 1
    assert job.artifacts[0].r_path == relative_dir
    assert job.artifacts[0].r_name == "results"
    assert job.progress_artifacts[0].r_path == f"{relative_dir}/results"
    assert {entry.r_name for entry in job.status_files} == {
        "wes.status"
    }


def test_array_scan_reads_current_and_legacy_status_dirs(mock_hub):
    cluster = _cluster()
    for relative_dir, index in (
        ("sweep/ns/tasks/2", "2"),
        ("sweep/ns/array-status/100/3", "3"),
    ):
        _write_status(cluster, relative_dir, "ns")
        with (cluster / relative_dir / "wes.status").open("a") as status_file:
            status_file.write(f"array_index={index}\n")
    job = SimpleNamespace(
        job_dir="sweep/ns",
        ssh_config="mock",
        status_file=StatusFile("sweep/ns", "mock"),
    )

    statuses = mock_hub._array_statuses(SimpleNamespace(job=job))

    assert {status.array_index for status in statuses} == {"2", "3"}


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


def test_discover_without_path_adopts_status_only_jobs(mock_hub):
    cluster = _cluster()
    _write_status(cluster, "legacy/job", "ns_legacy")

    assert mock_hub.discover("mock") == ["ns_legacy"]
    assert mock_hub.store.get_job("ns_legacy")["state"] == "COMPLETED"


def test_discover_ignores_config_only_dirs(mock_hub):
    # a job dir with a config but no wes.status on the server is either still
    # being created (runtime-only) or a ghost - it must not be adopted/stored
    cluster = _cluster()
    (cluster / "cfgonly/job").mkdir(parents=True)
    (cluster / "cfgonly/job/demo_config.json").write_text("{}")

    assert mock_hub.discover("mock") == []
    assert mock_hub.store.list_jobs() == []
    assert mock_hub.registry == {}


def test_full_discover_prunes_cached_jobs_missing_on_server(mock_hub, monkeypatch):
    cluster = _cluster()
    _write_status(cluster, "jobs/live", "ns_live")
    mock_hub.store.upsert_job("ns_live", ssh="mock", job_name="live", discovered=1)
    mock_hub.store.upsert_job("ns_ghost", ssh="mock", job_name="ghost", discovered=1)
    monkeypatch.setattr(
        "weshub.manager.Cluster", lambda _ssh: SimpleNamespace(get_jobs=lambda: [])
    )

    adopted = mock_hub.discover("mock")

    assert adopted == ["ns_live"]
    assert mock_hub.store.get_job("ns_live") is not None
    # cached job with no wes.status on the server: removed from cache and UI
    assert mock_hub.store.get_job("ns_ghost") is None


def test_full_discover_keeps_cached_job_still_live_in_slurm(mock_hub, monkeypatch):
    mock_hub.store.upsert_job(
        "ns_live_slurm", ssh="mock", job_name="ghost", job_id="777", discovered=1
    )
    live = SimpleNamespace(job_id="777_3", name="ghost")
    monkeypatch.setattr(
        "weshub.manager.Cluster", lambda _ssh: SimpleNamespace(get_jobs=lambda: [live])
    )

    assert mock_hub.discover("mock") == []
    assert mock_hub.store.get_job("ns_live_slurm") is not None


def test_full_discover_prunes_runtime_job_missing_on_server(mock_hub, monkeypatch):
    from weshub.manager import JobRecord

    cluster = _cluster()
    _write_status(cluster, "jobs/live", "ns_live")
    # runtime-tracked job whose status is gone from the server
    job = SimpleNamespace(
        namespace="ns_ghost",
        job_name="ghost",
        ssh_config="mock",
        task=SimpleNamespace(name="demo", jobs_ids=[]),
        status_file=SimpleNamespace(job_dir_exists=lambda: True),
    )
    rec = JobRecord(job, None, None, discovered=True)
    rec.status_seen = True
    mock_hub.registry["ns_ghost"] = rec
    mock_hub.store.upsert_job("ns_ghost", ssh="mock", job_name="ghost", discovered=1)
    monkeypatch.setattr(
        "weshub.manager.Cluster", lambda _ssh: SimpleNamespace(get_jobs=lambda: [])
    )

    assert mock_hub.discover("mock") == ["ns_live"]

    assert "ns_ghost" not in mock_hub.registry
    assert mock_hub.store.get_job("ns_ghost") is None
    assert mock_hub.store.get_job("ns_live") is not None


def test_full_discover_keeps_in_creation_runtime_job(mock_hub, monkeypatch):
    from weshub.manager import JobRecord

    # dispatched but no wes.status on the server yet: runtime-only, kept
    job = SimpleNamespace(
        namespace="ns_fresh",
        job_name="fresh",
        ssh_config="mock",
        task=SimpleNamespace(name="demo", jobs_ids=[]),
        status_file=SimpleNamespace(job_dir_exists=lambda: True),
    )
    mock_hub.registry["ns_fresh"] = JobRecord(job, 1, 1, discovered=False)
    monkeypatch.setattr(
        "weshub.manager.Cluster", lambda _ssh: SimpleNamespace(get_jobs=lambda: [])
    )

    assert mock_hub.discover("mock") == []

    assert "ns_fresh" in mock_hub.registry
    assert mock_hub.store.get_job("ns_fresh") is None


def test_full_discover_prunes_jobless_runs(mock_hub, monkeypatch):
    monkeypatch.setattr(
        "weshub.manager.Cluster", lambda _ssh: SimpleNamespace(get_jobs=lambda: [])
    )
    pipeline = mock_hub.store.add_pipeline("p", "sequence: {}", "mock", "", True)
    old_run = mock_hub.store.add_run(pipeline["id"], "manual")
    mock_hub.store.update_run(old_run["id"], "COMPLETED", finished_at=1.0)
    mock_hub.store.upsert_job(
        "ns_gone", run_id=old_run["id"], pipeline_id=pipeline["id"],
        ssh="mock", job_name="gone", discovered=1,
    )
    fresh_run = mock_hub.store.add_run(pipeline["id"], "manual")

    mock_hub.discover("mock")

    # finished run whose job is gone from the server: run row removed too
    assert mock_hub.store.get_run(old_run["id"]) is None
    # fresh run within the grace period: kept (dispatch may not have registered)
    assert mock_hub.store.get_run(fresh_run["id"]) is not None


def test_full_discover_keeps_run_with_slurm_live_job(mock_hub, monkeypatch):
    pipeline = mock_hub.store.add_pipeline("p", "sequence: {}", "mock", "", True)
    run = mock_hub.store.add_run(pipeline["id"], "manual")
    mock_hub.store.update_run(run["id"], "RUNNING", finished_at=None)
    mock_hub.store.upsert_job(
        "ns_live", run_id=run["id"], pipeline_id=pipeline["id"],
        ssh="mock", job_name="livejob", job_id="42", discovered=1,
    )
    live = SimpleNamespace(job_id="42_0", name="livejob")
    monkeypatch.setattr(
        "weshub.manager.Cluster", lambda _ssh: SimpleNamespace(get_jobs=lambda: [live])
    )

    mock_hub.discover("mock")

    assert mock_hub.store.get_run(run["id"]) is not None
    assert mock_hub.store.get_job("ns_live") is not None


def test_path_discover_does_not_prune(mock_hub, monkeypatch):
    # a partial-path scan must not prune jobs outside the scanned subtree
    mock_hub.store.upsert_job("ns_other", ssh="mock", job_name="other", discovered=1)
    monkeypatch.setattr(
        "weshub.manager.Cluster", lambda _ssh: SimpleNamespace(get_jobs=lambda: [])
    )

    assert mock_hub.discover("mock", "jobs") == []
    assert mock_hub.store.get_job("ns_other") is not None


def test_discover_without_path_reads_status_before_config_fallback(mock_hub):
    cluster = _cluster()
    _write_status(cluster, "configured/job", "ns_configured", state="RUNNING")
    (cluster / "configured/job/demo_config.json").write_text("{}")

    assert mock_hub.discover("mock") == ["ns_configured"]
    assert mock_hub.store.get_job("ns_configured")["state"] == "RUNNING"


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
    assert res.json()["jobs"] == [
        {**res.json()["jobs"][0], "namespace": "ns_x", "state": "COMPLETED"}
    ]

    # without path, discovery is status-only: the already-adopted job is not
    # re-adopted and config-only dirs are ignored
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
