from __future__ import annotations

import json
from unittest.mock import MagicMock

from wes.jobs.scanner import JobScanner


def _config() -> dict:
    return {
        "job": {
            "namespace": "ns_20260101_ab12",
            "job_name": "my_task_ns_20260101_ab12",
            "ssh_config": "hpc",
        },
        "task": {
            "name": "my_task",
            "wes_file": "task.wes",
            "git_url": "git@github.com:user/repo.git",
            "path": ".",
            "ssh_config": "hpc",
            "job_script": "job.sh",
            "pre_script": "pre.sh",
            "branch": "main",
            "cleanup": True,
            "artifacts": ["out.txt"],
            "partition": "gpu",
            "cpus": "4",
            "gpus": "1",
            "memory": "16G",
            "time": "02:00:00",
            "nodelist": "h86",
        },
    }


def test_config_to_task_restores_pre_script() -> None:
    task = JobScanner("hpc")._config_to_task(_config())
    assert task.pre_script == "pre.sh"
    assert task.job_script == "job.sh"
    assert task.branch == "main"
    assert task.cleanup_git is True


def test_scan_reuses_namespace_from_config(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    runner_cls = MagicMock()
    monkeypatch.setattr("wes.jobs.scanner.SshRunner", runner_cls)
    monkeypatch.setattr("wes.jobs.job.SshRunner", runner_cls)
    monkeypatch.setattr("wes.jobs.status.SshRunner", runner_cls)
    runner = runner_cls.return_value

    def _run(cmd, script=None, **kw):
        if "find" in cmd and "_config.json" in cmd:
            return True, ["my_task/ns_20260101_ab12/my_task_config.json"]
        if cmd.startswith("cat "):
            return True, [json.dumps(_config())]
        return True, [""]

    runner.run_command.side_effect = _run

    jobs = JobScanner("hpc").scan()

    assert len(jobs) == 1
    job = jobs[0]
    assert job.namespace == "ns_20260101_ab12"
    assert job.job_dir == "my_task/ns_20260101_ab12"
    assert job.pre_script is not None
    assert job.pre_script.r_name == "pre.sh"
    # discovery must be read-only towards the server
    assert runner.scp_to.call_args_list == []
    cmds = [c.args[0] if c.args else "" for c in runner.run_command.call_args_list]
    assert not any("mkdir" in c for c in cmds)


def test_list_dir_dirs_only_adds_type_filter(monkeypatch) -> None:
    runner_cls = MagicMock()
    monkeypatch.setattr("wes.jobs.scanner.SshRunner", runner_cls)
    runner = runner_cls.return_value
    runner.run_command.return_value = (True, [])

    scanner = JobScanner("hpc")
    scanner.list_dir(".", recursive=False, depth=1, dirs_only=True)
    assert "-type d" in runner.run_command.call_args.args[0]

    scanner.list_dir(".", recursive=False, depth=1)
    assert "-type d" not in runner.run_command.call_args.args[0]
