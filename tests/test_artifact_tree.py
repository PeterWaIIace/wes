import subprocess
import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock


from wes.jobs.job import ArtifactItem, resolve_artifact_pattern
from wes.jobs.status import JobStatus, inject_job_status
from wes.jobs.status_sh_scripts import STATUS_HELPER_SCRIPT
from wes.remote.tree import inspect_remote_patterns, list_remote_directory, remote_tree


class LocalListingRunner:
    def run_command(self, command, quiet=False):
        result = subprocess.run(["bash", "-c", command], text=True, capture_output=True)
        return result.returncode == 0, result.stdout.splitlines()


def test_directory_listing_is_one_level_and_paginated(tmp_path):
    (tmp_path / "folder").mkdir()
    (tmp_path / "folder" / "nested.png").write_bytes(b"image")
    (tmp_path / "first file.txt").write_text("hello")
    (tmp_path / "second.txt").write_text("world")
    first = list_remote_directory(LocalListingRunner(), str(tmp_path), limit=2)
    second = list_remote_directory(LocalListingRunner(), str(tmp_path), offset=2, limit=2)

    assert first["next_offset"] == 2
    assert second["next_offset"] is None
    assert {entry["name"] for entry in first["entries"] + second["entries"]} == {
        "folder", "first file.txt", "second.txt"
    }
    assert not any(entry["name"] == "nested.png" for entry in first["entries"])


def test_tree_uses_depth_limit(tmp_path):
    (tmp_path / "folder").mkdir()
    (tmp_path / "folder" / "nested.png").write_text("chart")
    shallow = remote_tree(LocalListingRunner(), str(tmp_path), depth=1)
    deep = remote_tree(LocalListingRunner(), str(tmp_path), depth=2)
    assert not any("nested.png" in line for line in shallow)
    assert any("nested.png" in line for line in deep)


def test_inspect_patterns_accepts_spaces_and_symlink_directories(tmp_path):
    actual = tmp_path / "actual results"
    actual.mkdir()
    (actual / "status_2.png").write_bytes(b"png")
    (tmp_path / "results").symlink_to(actual, target_is_directory=True)
    entries = inspect_remote_patterns(LocalListingRunner(), [str(tmp_path / "results/status_*.png")])
    assert len(entries) == 1
    assert entries[0]["size"] == 3
    assert entries[0]["name"] == "status_2.png"


def test_artifact_variables_resolve_per_task(tmp_path, monkeypatch):
    status = JobStatus("task", "ns_array_2", "job", "hpc", job_id="42", array_index="2")
    owner = SimpleNamespace(status=status)
    runner = MagicMock()
    runner.ssh_config = "hpc"
    runner.run_command.return_value = (True, ["present"])
    runner.scp_from.return_value = True
    monkeypatch.setattr("wes.jobs.job.SshRunner", MagicMock(return_value=runner))
    artifact = ArtifactItem(str(tmp_path / "status_{array_index}_{job_id}.png"),
                            "results/status_{array_index}_{job_id}.png", "hpc", owner)

    outcome = artifact.sync()

    assert outcome.state == "downloaded"
    assert runner.scp_from.call_args.args[1] == "status_2_42.png"
    assert "{" not in str(runner.scp_from.call_args)


def test_unavailable_array_variable_defers_download():
    status = JobStatus("task", "ns", "job", "hpc")
    assert resolve_artifact_pattern("results/status_{array_index}.png", status) is None
    assert resolve_artifact_pattern("results/**/*.png", status) == "results/**/*.png"


def test_tree_cli_does_not_download(tmp_path, monkeypatch, capsys):
    from wes import cli

    factory = MagicMock()
    factory.return_value.tree.return_value = ["results", "|-- chart.png"]
    monkeypatch.setattr(cli, "WES", factory)
    monkeypatch.setattr("sys.argv", ["wes", "tree", "--ssh", "hpc", "--path", "results", "--depth", "1"])
    cli.main()
    factory.return_value.tree.assert_called_once_with("results", 1)
    factory.return_value.pull.assert_not_called()
    assert "chart.png" in capsys.readouterr().out


def test_array_injection_preserves_working_dir_and_records_artifact_dir(tmp_path):
    source = tmp_path / "swarm-gym"
    source.mkdir()
    helper = tmp_path / "wes_status.sh"
    helper.write_text(STATUS_HELPER_SCRIPT)
    helper.chmod(0o755)
    config = {"job": {"namespace": "ns", "job_name": "job", "ssh_config": "hpc"},
              "task": {"name": "sweep"}}
    (tmp_path / "sweep_config.json").write_text(json.dumps(config, indent=4))
    script = tmp_path / "job.sh"
    script.write_text(inject_job_status('#!/bin/bash\npwd > "$SLURM_SUBMIT_DIR/body.cwd"\n'))
    env = {**os.environ, "SLURM_SUBMIT_DIR": str(tmp_path), "SLURM_ARRAY_TASK_ID": "2",
           "SLURM_JOB_ID": "42", "WES_ARTIFACT_DIR": str(source)}

    subprocess.run(["bash", str(script)], cwd=source, env=env, check=True)

    assert (tmp_path / "body.cwd").read_text().strip() == str(source)
    status = JobStatus.from_text((tmp_path / "tasks/2/wes.status").read_text())
    assert status.artifact_dir == str(source)
    assert status.array_index == "2"
