from __future__ import annotations

from types import SimpleNamespace

from wes.jobs.status import JobStatus
from wes.states import State
from wes.tasks import Task

from weshub.config import Settings
from weshub.manager import Hub, JobRecord, parent_job_dir, run_status


def test_progress_globs_expand_to_distinct_preview_files(tmp_path, monkeypatch):
    hub = Hub(Settings(data_dir=tmp_path / "data"))
    task = Task(
        name="sweep", git_url="", ssh_config="hpc",
        progress_artifacts=["results/*/reward_chart.png", "results/**/reward_chart.png"],
    )
    job = SimpleNamespace(repo_dir="sweep/ns/tasks/2", task=task)
    hub.registry["ns_array_2"] = JobRecord(job, None, None, discovered=True)
    monkeypatch.setattr(hub, "_task_for_job", lambda row: task)
    monkeypatch.setattr(hub, "job_execution", lambda row: {})
    base = hub.settings.results_dir / job.repo_dir
    for directory in ("run one", "run two", "deep/nested"):
        chart = base / "results" / directory / "reward_chart.png"
        chart.parent.mkdir(parents=True, exist_ok=True)
        chart.write_bytes(b"chart")

    enriched = hub.enrich_job({"namespace": "ns_array_2"})

    previews = enriched["progress_artifacts"]
    assert len(previews) == 3
    assert all(preview["thumbnail"] for preview in previews)
    assert {preview["path"] for preview in previews} == {
        f"{job.repo_dir}/results/{directory}/reward_chart.png"
        for directory in ("run one", "run two", "deep/nested")
    }


def test_run_status_derivation():
    assert run_status([]) == ""
    assert run_status(["PENDING"]) == "PENDING"
    assert run_status(["RUNNING", "PENDING"]) == "RUNNING"
    assert run_status(["COMPLETED", "COMPLETED"]) == "COMPLETED"
    assert run_status(["COMPLETED", "FAILED"]) == "FAILED"
    assert run_status(["COMPLETED", "PENDING", "RUNNING"]) == "RUNNING"
    assert run_status(["CANCELLED", "COMPLETED"]) == "CANCELLED"
    assert run_status(["CANCELLED", "CANCELLED"]) == "CANCELLED"


def test_parent_job_dir_maps_array_task_dirs():
    assert parent_job_dir("sweep/ns/tasks/7") == "sweep/ns"
    assert parent_job_dir("sweep/ns/array-status/100528/7") == "sweep/ns"
    assert parent_job_dir("sweep/ns") == "sweep/ns"
    assert parent_job_dir("/work/tasks/sweep/array-status/100/7") == "/work/tasks/sweep"
    assert parent_job_dir("/work/tasks/sweep/tasks/7") == "/work/tasks/sweep"
    assert parent_job_dir("/work/tasks/sweep/other/7") == "/work/tasks/sweep/other/7"
    assert parent_job_dir("/work/tasks/not-an-index") == "/work/tasks/not-an-index"


def test_discovery_skips_unreadable_status(tmp_path, monkeypatch):
    hub = Hub(Settings(data_dir=tmp_path / "data"))
    monkeypatch.setattr(
        "weshub.manager.JobScanner", lambda ssh: SimpleNamespace(runner=None)
    )
    monkeypatch.setattr("weshub.manager.find_status_dirs", lambda runner, path: ["broken"])
    monkeypatch.setattr("weshub.manager.StatusFile", FailingStatusFile)

    assert hub._discover_path("hpc", ".") == ([], set())


class FailingStatusFile:
    def __init__(self, job_dir, ssh):
        pass

    def read(self):
        raise ValueError("invalid status")


def test_catalog_clusters_exclude_stale_job_ssh_configs(tmp_path):
    hub = Hub(Settings(data_dir=tmp_path / "data"))
    hub.cluster_configs = {"hpc": "hpc-login"}
    hub.store.upsert_job("old-mock", ssh="mock")
    hub.store.upsert_job("current-hpc", ssh="hpc-login")

    assert hub._ssh_configs() == {"hpc-login"}


def test_missing_previously_observed_status_evicts_job(tmp_path, monkeypatch):
    hub = Hub(Settings(data_dir=tmp_path / "data"))
    job = SimpleNamespace(
        namespace="gone",
        job_name="gone",
        ssh_config="hpc",
        task=SimpleNamespace(jobs_ids=[]),
        status_file=SimpleNamespace(job_dir_exists=lambda: True),
        pull_status=lambda: False,
    )
    record = JobRecord(job, None, None, discovered=True)
    record.status_seen = True
    hub.registry["gone"] = record
    hub.store.upsert_job("gone", discovered=1)
    monkeypatch.setattr(
        "weshub.manager.Cluster", lambda _ssh: SimpleNamespace(get_jobs=lambda: [])
    )

    hub._sync_job_status(record)

    assert "gone" not in hub.registry
    assert hub.store.get_job("gone") is None


def test_missing_status_prunes_stale_discovered_job(tmp_path, monkeypatch):
    hub = Hub(Settings(data_dir=tmp_path / "data"))
    job = SimpleNamespace(
        namespace="stale",
        job_name="stale",
        ssh_config="hpc",
        task=SimpleNamespace(jobs_ids=[]),
        status_file=SimpleNamespace(job_dir_exists=lambda: True),
        pull_status=lambda: False,
    )
    record = JobRecord(job, None, None, discovered=True)
    hub.registry["stale"] = record
    hub.store.upsert_job("stale", discovered=1)
    monkeypatch.setattr(
        "weshub.manager.Cluster", lambda _ssh: SimpleNamespace(get_jobs=lambda: [])
    )

    hub._sync_job_status(record)

    assert "stale" not in hub.registry
    assert hub.store.get_job("stale") is None


def test_missing_job_dir_prunes_even_when_slurm_knows_job(tmp_path, monkeypatch):
    hub = Hub(Settings(data_dir=tmp_path / "data"))
    job = SimpleNamespace(
        namespace="gone",
        job_name="gone_array",
        ssh_config="hpc",
        task=SimpleNamespace(jobs_ids=["100528"]),
        status_file=SimpleNamespace(job_dir_exists=lambda: False),
        pull_status=lambda: False,
    )
    record = JobRecord(job, None, None, discovered=True)
    record.status_seen = True
    hub.registry["gone"] = record
    hub.store.upsert_job("gone", discovered=1, job_id="100528")
    live = SimpleNamespace(job_id="100528_5", name="gone_array")
    monkeypatch.setattr(
        "weshub.manager.Cluster", lambda _ssh: SimpleNamespace(get_jobs=lambda: [live])
    )

    hub._sync_job_status(record)

    assert "gone" not in hub.registry
    assert hub.store.get_job("gone") is None


def test_unreachable_server_does_not_prune(tmp_path, monkeypatch):
    hub = Hub(Settings(data_dir=tmp_path / "data"))
    job = SimpleNamespace(
        namespace="flaky",
        job_name="flaky",
        ssh_config="hpc",
        task=SimpleNamespace(jobs_ids=[]),
        status_file=SimpleNamespace(job_dir_exists=lambda: None),
        pull_status=lambda: False,
    )
    record = JobRecord(job, None, None, discovered=True)
    hub.registry["flaky"] = record
    hub.store.upsert_job("flaky", discovered=1)
    monkeypatch.setattr(
        "weshub.manager.Cluster", lambda _ssh: SimpleNamespace(get_jobs=lambda: [])
    )
    monkeypatch.setattr(hub, "_array_statuses", lambda _rec: [])

    hub._sync_job_status(record)

    assert "flaky" in hub.registry
    assert hub.store.get_job("flaky") is not None


def test_missing_status_keeps_live_slurm_array_job(tmp_path, monkeypatch):
    hub = Hub(Settings(data_dir=tmp_path / "data"))
    job = SimpleNamespace(
        namespace="array",
        job_name="swarmnasium_sweep_array",
        ssh_config="hpc",
        task=SimpleNamespace(jobs_ids=["100528"]),
        status_file=SimpleNamespace(job_dir_exists=lambda: True),
        pull_status=lambda: False,
    )
    record = JobRecord(job, None, None, discovered=True)
    record.status_seen = True
    hub.registry["array"] = record
    hub.store.upsert_job("array", discovered=1, job_id="100528")
    live = SimpleNamespace(job_id="100528_5", name="swarmnasium_sweep_array")
    monkeypatch.setattr(
        "weshub.manager.Cluster", lambda _ssh: SimpleNamespace(get_jobs=lambda: [live])
    )

    hub._sync_job_status(record)

    assert hub.registry["array"] is record
    assert hub.store.get_job("array") is not None


def test_array_monitor_reads_only_its_own_status(tmp_path, monkeypatch):
    hub = Hub(Settings(data_dir=tmp_path / "data"))
    job = SimpleNamespace(
        namespace="sweep",
        job_name="sweep",
        ssh_config="hpc",
        status_file=SimpleNamespace(job_dir_exists=lambda: True),
        task=SimpleNamespace(name="task"),
        status=JobStatus("task", "sweep", "sweep", "hpc", state=State.COMPLETED),
        pull_status=lambda: True,
    )
    record = JobRecord(job, None, None, discovered=False)
    hub.store.upsert_job("sweep")
    statuses = [
        JobStatus("task", "sweep", "sweep", "hpc", state=State.COMPLETED, array_index="0"),
        JobStatus("task", "sweep", "sweep", "hpc", state=State.RUNNING, array_index="1"),
    ]
    monkeypatch.setattr(hub, "_array_statuses", lambda _record: statuses)
    monkeypatch.setattr(hub, "_array_slurm_states", lambda _record: [])

    hub._sync_job_status(record)

    assert hub.store.get_job("sweep")["state"] == "COMPLETED"
    assert hub.store.list_array_children("sweep") == []


def test_other_array_tasks_do_not_override_completed_task(tmp_path, monkeypatch):
    hub = Hub(Settings(data_dir=tmp_path / "data"))
    job = SimpleNamespace(
        namespace="sweep",
        job_name="sweep",
        ssh_config="hpc",
        status_file=SimpleNamespace(job_dir_exists=lambda: True),
        task=SimpleNamespace(name="task"),
        status=JobStatus("task", "sweep", "sweep", "hpc", state=State.COMPLETED),
        pull_status=lambda: True,
    )
    record = JobRecord(job, None, None, discovered=False)
    hub.store.upsert_job("sweep")
    statuses = [JobStatus("task", "sweep", "sweep", "hpc", state=State.COMPLETED, array_index="0")]
    monkeypatch.setattr(hub, "_array_statuses", lambda _record: statuses)
    monkeypatch.setattr(hub, "_array_slurm_states", lambda _record: ["PENDING"])

    hub._sync_job_status(record)

    assert hub.store.get_job("sweep")["state"] == "COMPLETED"


class _PendingJob:
    def __init__(self, namespace="sweep", job_name="sweep", jobs_ids=("100528",)):
        self.namespace = namespace
        self.job_name = job_name
        self.ssh_config = "hpc"
        self.task = SimpleNamespace(jobs_ids=list(jobs_ids))
        self.status_file = SimpleNamespace(job_dir_exists=lambda: True)
        self.status = JobStatus("task", namespace, job_name, "hpc", state=State.PENDING)

    def pull_status(self):
        return True


def _sacct(monkeypatch, hub, rows):
    monkeypatch.setattr(hub, "_array_statuses", lambda _rec: [])
    monkeypatch.setattr(
        "weshub.manager.Cluster", lambda _ssh: SimpleNamespace(get_jobs=lambda: [])
    )
    monkeypatch.setattr(
        "weshub.manager.JobsQuery",
        lambda _ssh: SimpleNamespace(get_recent=lambda: rows),
    )


def test_stuck_pending_array_parent_resolves_via_sacct(tmp_path, monkeypatch):
    hub = Hub(Settings(data_dir=tmp_path / "data"))
    rec = JobRecord(_PendingJob(), None, None, discovered=True)
    hub.registry["sweep"] = rec
    hub.store.upsert_job("sweep", discovered=1, job_id="100528")
    _sacct(
        monkeypatch,
        hub,
        [
            SimpleNamespace(job_id="100528_0", name="sweep", state="COMPLETED"),
            SimpleNamespace(job_id="100528_1", name="sweep", state="COMPLETED"),
        ],
    )

    hub._sync_job_status(rec)

    assert hub.store.get_job("sweep")["state"] == "COMPLETED"


def test_sacct_timeout_marks_array_parent_failed(tmp_path, monkeypatch):
    hub = Hub(Settings(data_dir=tmp_path / "data"))
    rec = JobRecord(_PendingJob(), None, None, discovered=True)
    hub.registry["sweep"] = rec
    hub.store.upsert_job("sweep", discovered=1, job_id="100528")
    _sacct(
        monkeypatch,
        hub,
        [
            SimpleNamespace(job_id="100528_0", name="sweep", state="COMPLETED"),
            SimpleNamespace(job_id="100528_1", name="sweep", state="TIMEOUT"),
        ],
    )

    hub._sync_job_status(rec)

    assert hub.store.get_job("sweep")["state"] == "FAILED"


def test_in_creation_job_is_runtime_only(tmp_path):
    hub = Hub(Settings(data_dir=tmp_path / "data"))
    job = SimpleNamespace(
        namespace="fresh",
        job_name="fresh",
        ssh_config="hpc",
        task=SimpleNamespace(name="t", jobs_ids=[]),
        status=SimpleNamespace(job_id=""),
        status_file=SimpleNamespace(job_dir_exists=lambda: True),
    )
    rec = JobRecord(job, run_id=7, pipeline_id=None, discovered=False)
    hub.registry["fresh"] = rec

    # shown in listings, but only from the runtime registry
    shown = hub.list_jobs()
    assert [j["namespace"] for j in shown] == ["fresh"]
    assert shown[0]["in_creation"] == 1
    assert hub.list_jobs(run_id=7) != []
    assert hub.list_jobs(run_id=8) == []
    assert hub.store.list_jobs() == []

    # once a server-side status exists the job is persisted and no longer
    # flagged as in-creation
    hub._persist(rec)
    assert hub.store.get_job("fresh") is not None
    assert "in_creation" not in hub.list_jobs()[0]


def test_store_is_runtime_only(tmp_path):
    data = tmp_path / "data"
    hub = Hub(Settings(data_dir=data))
    pipeline = hub.store.add_pipeline("mock-demo", "sequence: {}", "mock", "", True)
    run = hub.store.add_run(pipeline["id"], "manual")
    hub.store.upsert_job("mock-job", pipeline_id=pipeline["id"], run_id=run["id"], ssh="mock")

    # a new hub (e.g. after a restart) starts empty: nothing is persisted on disk
    fresh = Hub(Settings(data_dir=data))
    assert fresh.store.list_pipelines() == []
    assert fresh.store.list_runs() == []
    assert fresh.store.list_jobs() == []
    assert not (data / "hub.sqlite3").exists()


def test_sync_catalog_imports_workflow_and_resolves_cluster(tmp_path, monkeypatch):
    settings = Settings(
        data_dir=tmp_path / "data",
        catalog_repo="git@example.com:team/catalog.git",
    )
    catalog = settings.catalog_dir
    workflow = catalog / "workflows" / "demo"
    workflow.mkdir(parents=True)
    (catalog / ".weshub.yaml").write_text(
        "\n".join(
            [
                "clusters:",
                "  hpc:",
                "    ssh: hpc-login",
                "workflows:",
                "  - name: demo",
                "    path: workflows/demo",
            ]
        )
    )
    (workflow / "pipeline.wes").write_text(
        """sequence:
    demo:
        git_url: ssh://git@example.com/team/project.git
        branch: feature/experiment
        ssh: hpc
        job: scripts/job.sh
"""
    )
    script = workflow / "scripts" / "job.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/bash\ntrue\n")
    hub = Hub(settings)
    monkeypatch.setattr(hub, "_sync_catalog_repo", lambda: None)

    imported = hub.sync_catalog()

    assert [pipeline["name"] for pipeline in imported] == ["demo"]
    assert hub.cluster_configs == {"hpc": "hpc-login"}
    tasks = hub._parse_tasks(imported[0]["id"])
    assert tasks[0].ssh_config == "hpc-login"
    assert tasks[0].branch == "feature/experiment"
    assert (hub.pipeline_dir(imported[0]["id"]) / "scripts" / "job.sh").is_file()
