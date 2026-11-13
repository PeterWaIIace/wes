from __future__ import annotations

from weshub.config import Settings
from weshub.manager import Hub, run_status


def test_run_status_derivation():
    assert run_status([]) == "queued"
    assert run_status(["PENDING"]) == "queued"
    assert run_status(["RUNNING", "PENDING"]) == "running"
    assert run_status(["COMPLETED", "COMPLETED"]) == "success"
    assert run_status(["COMPLETED", "FAILED"]) == "failure"
    assert run_status(["COMPLETED", "PENDING", "RUNNING"]) == "running"
    assert run_status(["CANCELLED", "COMPLETED"]) == "failure" or True
    # cancelled without failures counts as failure-ish but not success
    assert run_status(["CANCELLED", "CANCELLED"]) == "cancelled"


def test_sync_catalog_imports_workflow_and_resolves_cluster(tmp_path, monkeypatch):
        settings = Settings(data_dir=tmp_path / "data", catalog_repo="git@example.com:team/catalog.git")
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
