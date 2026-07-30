from __future__ import annotations

import pytest

from web.parser import ConfigError, parse_wes_file, task_to_wes_yaml


class TestParseWesFile:
    def test_parse_minimal(self, wes_file) -> None:
        content = """
        sequence:
            my-job:
                git_url: ssh://git@example.com/repo.git
                ssh: hpc
                job: scripts/job.sh
        """
        p = wes_file(content)
        tasks = parse_wes_file(p)

        assert len(tasks) == 1
        task = tasks[0]
        assert task["name"] == "my-job"
        assert task["git_url"] == "ssh://git@example.com/repo.git"
        assert task["ssh"] == "hpc"
        assert task["job"] == "scripts/job.sh"
        assert task["branch"] == ""
        assert task["path"] == ""
        assert task["artifacts"] == []
        assert task["run"] == []
        assert task["cleanup"] is False

    def test_parse_full_config(self, wes_file) -> None:
        content = """
        sequence:
            train-model:
                git_url: ssh://git@example.com/ml.git
                branch: main
                path: /scratch/user
                ssh: gpu-cluster
                run:
                    - scripts/setup.sh
                    - scripts/data.sh
                job: scripts/train.sh
                post: scripts/cleanup.sh
                artifacts:
                    - ml/results
                    - ml/checkpoints
                cleanup: true
        """
        p = wes_file(content)
        tasks = parse_wes_file(p)

        assert len(tasks) == 1
        task = tasks[0]
        assert task["name"] == "train-model"
        assert task["branch"] == "main"
        assert task["path"] == "/scratch/user"
        assert task["ssh"] == "gpu-cluster"
        assert task["run"] == ["scripts/setup.sh", "scripts/data.sh"]
        assert task["job"] == "scripts/train.sh"
        assert task["post"] == "scripts/cleanup.sh"
        assert task["artifacts"] == ["ml/results", "ml/checkpoints"]
        assert task["cleanup"] is True

    def test_parse_dict_sequence(self, wes_file) -> None:
        content = """
        sequence:
            job-a:
                git_url: ssh://git@example.com/a.git
                ssh: hpc
                job: a.sh
            job-b:
                git_url: ssh://git@example.com/b.git
                ssh: hpc
                job: b.sh
        """
        p = wes_file(content)
        tasks = parse_wes_file(p)

        assert len(tasks) == 2
        assert tasks[0]["name"] == "job-a"
        assert tasks[1]["name"] == "job-b"

    def test_parse_list_sequence(self, wes_file) -> None:
        content = """
        sequence:
            - job-a:
                git_url: ssh://git@example.com/a.git
                ssh: hpc
                job: a.sh
            - job-b:
                git_url: ssh://git@example.com/b.git
                ssh: hpc
                job: b.sh
        """
        p = wes_file(content)
        tasks = parse_wes_file(p)

        assert len(tasks) == 2
        assert tasks[0]["name"] == "job-a"
        assert tasks[1]["name"] == "job-b"

    def test_parse_slurm_fields(self, wes_file) -> None:
        content = """
        sequence:
            gpu-job:
                git_url: ssh://git@example.com/repo.git
                ssh: hpc
                job: train.sh
                partition: gpu
                cpus: 8
                gpus: 2
                memory: 32G
                time: "4:00:00"
                nodelist: gpu0,gpu1
        """
        p = wes_file(content)
        tasks = parse_wes_file(p)
        task = tasks[0]
        assert task["partition"] == "gpu"
        assert task["cpus"] == "8"
        assert task["gpus"] == "2"
        assert task["memory"] == "32G"
        assert task["time"] == "4:00:00"
        assert task["nodelist"] == "gpu0,gpu1"


class TestParseWesValidation:
    def test_missing_file(self, tmp_path) -> None:
        with pytest.raises(ConfigError, match="not found"):
            parse_wes_file(tmp_path / "nonexistent.wes")

    def test_wrong_extension(self, tmp_path) -> None:
        p = tmp_path / "test.yaml"
        p.write_text("sequence: {}", encoding="utf-8")
        with pytest.raises(ConfigError, match="must have .wes extension"):
            parse_wes_file(p)

    def test_empty_file(self, wes_file) -> None:
        p = wes_file("")
        p.write_text("", encoding="utf-8")
        with pytest.raises(ConfigError, match="must contain a 'sequence' key"):
            parse_wes_file(p)

    def test_missing_required_field(self, wes_file) -> None:
        content = """
        sequence:
            my-job:
                git_url: ssh://git@example.com/repo.git
        """
        p = wes_file(content)
        with pytest.raises(ConfigError, match="missing required fields"):
            parse_wes_file(p)

    def test_unknown_field(self, wes_file) -> None:
        content = """
        sequence:
            my-job:
                git_url: ssh://git@example.com/repo.git
                ssh: hpc
                job: job.sh
                unknown_field: true
        """
        p = wes_file(content)
        with pytest.raises(ConfigError, match="unknown fields"):
            parse_wes_file(p)


class TestTaskToWesYaml:
    def test_roundtrip(self, wes_file) -> None:
        content = """
        sequence:
            my-job:
                git_url: ssh://git@example.com/repo.git
                ssh: hpc
                job: job.sh
                branch: main
        """
        p = wes_file(content)
        tasks = parse_wes_file(p)
        yaml_str = task_to_wes_yaml(tasks[0])
        assert "git_url:" in yaml_str
        assert "ssh: hpc" in yaml_str
        assert "job: job.sh" in yaml_str
        assert "branch: main" in yaml_str
        assert "my-job" in yaml_str

    def test_omits_empty_fields(self) -> None:
        task = {
            "name": "test",
            "git_url": "ssh://git@example.com/repo.git",
            "ssh": "hpc",
            "job": "job.sh",
            "branch": "",
            "path": "",
            "run": [],
            "post": "",
            "artifacts": [],
            "cleanup": False,
            "partition": "",
            "cpus": "",
            "gpus": "",
            "memory": "",
            "time": "",
            "nodelist": "",
        }
        yaml_str = task_to_wes_yaml(task)
        assert "branch:" not in yaml_str
        assert "path:" not in yaml_str
        assert "run:" not in yaml_str
        assert "partition:" not in yaml_str
