from __future__ import annotations

import json
from unittest.mock import MagicMock

from wes import WES
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


def test_check_discovers_directories_breadth_first(monkeypatch) -> None:
    calls = []
    tree = {
        ".": ["./alpha", "./beta"],
        "./alpha": ["./alpha/nested"],
        "./beta": [],
        "./alpha/nested": [],
    }

    def list_dir(self, path, recursive=False, depth=None, dirs_only=False):
        if not dirs_only:
            calls.append(path)
        return tree[path] if dirs_only else tree[path]

    monkeypatch.setattr(JobScanner, "list_dir", list_dir)

    assert WES("hpc").check(refresh=True) == []
    assert calls == [".", "./alpha", "./beta", "./alpha/nested"]


def test_check_does_not_descend_into_unstarted_wes_job(monkeypatch) -> None:
    calls = []
    entries = {
        ".": ["./run"],
        "./run": ["./run/task_config.json", "./run/repository"],
    }

    def list_dir(self, path, recursive=False, depth=None, dirs_only=False):
        if not dirs_only:
            calls.append(path)
        if dirs_only:
            if path == ".":
                return ["./run"]
            return ["./run/repository"]
        return entries[path]

    monkeypatch.setattr(JobScanner, "list_dir", list_dir)

    assert WES("hpc").check(refresh=True) == []
    assert calls == [".", "./run"]


def test_clean_removes_only_failed_job_directories(monkeypatch) -> None:
    entries = {
        ".": ["./failed", "./running"],
        "./failed": ["./failed/wes.status"],
        "./running": ["./running/wes.status"],
    }
    commands = []

    def list_dir(self, path, recursive=False, depth=None, dirs_only=False):
        if dirs_only:
            return entries["."] if path == "." else []
        return entries[path]

    def run_command(self, command, **kwargs):
        commands.append(command)
        if command == "cat ./failed/wes.status":
            return True, ["state: FAILED"]
        if command == "cat ./running/wes.status":
            return True, ["state: RUNNING"]
        return True, []

    monkeypatch.setattr(JobScanner, "list_dir", list_dir)
    monkeypatch.setattr("wes.SshRunner.run_command", run_command)

    assert WES("hpc").clean(refresh=True) == ["removed ./failed"]
    assert "rm -rf -- ./failed" in commands
    assert "rm -rf -- ./running" not in commands


def test_check_reuses_cached_status_paths(monkeypatch, tmp_path) -> None:
    commands = []
    wes = WES("hpc")
    monkeypatch.setattr(wes, "_status_cache_path", lambda rootdir: tmp_path / "paths.yaml")
    wes._write_status_cache(".", ["./run/wes.status"])

    def run_command(self, command, **kwargs):
        commands.append(command)
        return True, ["state: RUNNING"]

    monkeypatch.setattr("wes.SshRunner.run_command", run_command)
    monkeypatch.setattr(
        JobScanner,
        "list_dir",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected discovery")),
    )

    assert wes.check() == [{"state": "RUNNING"}]
    assert commands == ["cat ./run/wes.status"]


def test_check_prunes_stale_paths_from_cache(monkeypatch, tmp_path) -> None:
    import yaml

    wes = WES("hpc")
    cache_file = tmp_path / "paths.yaml"
    monkeypatch.setattr(wes, "_status_cache_path", lambda rootdir: cache_file)
    wes._write_status_cache(".", ["./live/wes.status", "./gone/wes.status"])

    def run_command(self, command, **kwargs):
        if command == "cat ./live/wes.status":
            return True, ["state: RUNNING"]
        return False, []  # ./gone no longer exists on the server

    monkeypatch.setattr("wes.SshRunner.run_command", run_command)
    monkeypatch.setattr(
        JobScanner,
        "list_dir",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected discovery")),
    )

    assert wes.check() == [{"state": "RUNNING"}]
    # the deleted job's path was pruned from the cache, not just from the result
    assert yaml.safe_load(cache_file.read_text()) == ["./live/wes.status"]
