from unittest.mock import MagicMock

import pytest

from weshub.config import Settings
from weshub.manager import Hub, HubError


WORKFLOW = """sequence:
  demo:
    git_url: https://example.com/repo.git
    ssh: hpc
    job: scripts/job.sh
    artifacts: [results]
"""


def test_manifest_free_catalog_imports_runnable_workflows(tmp_path, monkeypatch, capsys):
    settings = Settings(data_dir=tmp_path, catalog_repo="git@example.com:workflows.git")
    scripts = settings.catalog_dir / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "job.sh").write_text("#!/bin/bash\necho hello\n")
    (settings.catalog_dir / "demo.wes").write_text(WORKFLOW)
    (settings.catalog_dir / "example.wes").write_text("sequence: {example: {git_url: []}}")
    (settings.catalog_dir / "missing.wes").write_text(WORKFLOW.replace("scripts/job.sh", "missing.sh"))
    (settings.catalog_dir / "binary.dat").write_bytes(b"\xff\xfe")
    (settings.catalog_dir / ".hidden").mkdir()
    (settings.catalog_dir / ".hidden" / "ignored.wes").write_text(WORKFLOW)
    hub = Hub(settings)
    monkeypatch.setattr(hub, "_sync_catalog_repo", MagicMock())

    imported = hub.sync_catalog()

    assert [pipeline["name"] for pipeline in imported] == ["demo"]
    assert hub.cluster_configs == {"hpc": "hpc"}
    assert (hub.pipeline_dir(imported[0]["id"]) / "scripts/job.sh").is_file()
    assert "example.wes" in capsys.readouterr().out
    assert len(hub.sync_catalog()) == 1
    assert len(hub.store.list_pipelines()) == 1
    hub.stop()


def test_empty_manifest_free_catalog_reports_actionable_error(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, catalog_repo="git@example.com:workflows.git")
    settings.catalog_dir.mkdir()
    hub = Hub(settings)
    monkeypatch.setattr(hub, "_sync_catalog_repo", MagicMock())
    with pytest.raises(HubError, match="No runnable .wes workflows"):
        hub.sync_catalog()
    hub.stop()


def test_explicit_manifest_remains_authoritative(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, catalog_repo="git@example.com:workflows.git")
    settings.catalog_dir.mkdir()
    (settings.catalog_dir / ".weshub.yaml").write_text("workflows: invalid\n")
    hub = Hub(settings)
    monkeypatch.setattr(hub, "_sync_catalog_repo", MagicMock())
    with pytest.raises(HubError, match="'workflows' must be a list"):
        hub.sync_catalog()
    hub.stop()
