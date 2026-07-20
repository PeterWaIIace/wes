from __future__ import annotations

import pytest

from src.parser import ConfigError, WESParser


class TestWESParserValid:
    def test_parse_minimal(self, wes_file) -> None:
        content = """
        sequence:
            my-job:
                git_url: ssh://git@example.com/repo.git
                ssh: hpc
                job: scripts/job.sh
        """
        p = wes_file(content)
        parser = WESParser()
        tasks = parser.parse(p)

        assert len(tasks) == 1
        task = tasks[0]
        assert task.name == "my-job"
        assert task.git_url == "ssh://git@example.com/repo.git"
        assert task.ssh_config == "hpc"
        assert task.job == "scripts/job.sh"
        assert task.branch == ""
        assert task.path == "."
        assert task.artifacts == []
        assert task.run == []
        assert task.cleanup_git is False

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
        parser = WESParser()
        tasks = parser.parse(p)

        assert len(tasks) == 1
        task = tasks[0]
        assert task.name == "train-model"
        assert task.branch == "main"
        assert task.path == "/scratch/user"
        assert task.ssh_config == "gpu-cluster"
        assert task.run == ["scripts/setup.sh", "scripts/data.sh"]
        assert task.job == "scripts/train.sh"
        assert task.post == "scripts/cleanup.sh"
        assert task.artifacts == ["ml/results", "ml/checkpoints"]
        assert task.cleanup_git is True

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
        parser = WESParser()
        tasks = parser.parse(p)

        assert len(tasks) == 2
        assert tasks[0].name == "job-a"
        assert tasks[1].name == "job-b"

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
        parser = WESParser()
        tasks = parser.parse(p)

        assert len(tasks) == 2
        assert tasks[0].name == "job-a"
        assert tasks[1].name == "job-b"

    def test_parse_single_task_list(self, wes_file) -> None:
        content = """
        sequence:
            - fly-to-point:
                git_url: ssh://git@example.com/swarm.git
                branch: experiment-fly-to-point
                ssh: hpc
                run:
                    - bach_example/run.sh
                job: bach_example/job.sh
                artifacts:
                    - swarm-gym/results
                post: bach_example/post.sh
                cleanup: true
        """
        p = wes_file(content)
        parser = WESParser()
        tasks = parser.parse(p)

        assert len(tasks) == 1
        assert tasks[0].name == "fly-to-point"
        assert tasks[0].cleanup_git is True


class TestWESParserValidation:
    def test_missing_file(self, tmp_path) -> None:
        parser = WESParser()
        with pytest.raises(ConfigError, match="not found"):
            parser.parse(tmp_path / "nonexistent.wes")

    def test_wrong_extension(self, tmp_path) -> None:
        p = tmp_path / "test.yaml"
        p.write_text("sequence: {}", encoding="utf-8")
        parser = WESParser()
        with pytest.raises(ConfigError, match="must have .wes extension"):
            parser.parse(p)

    def test_empty_file(self, wes_file) -> None:
        p = wes_file("")
        p.write_text("", encoding="utf-8")
        parser = WESParser()
        with pytest.raises(ConfigError, match="must contain a 'sequence' key"):
            parser.parse(p)

    def test_no_sequence_key(self, wes_file) -> None:
        content = """
        jobs:
            my-job:
                git_url: ssh://git@example.com/repo.git
        """
        p = wes_file(content)
        parser = WESParser()
        with pytest.raises(ConfigError, match="must contain a 'sequence' key"):
            parser.parse(p)

    def test_missing_required_field(self, wes_file) -> None:
        content = """
        sequence:
            my-job:
                git_url: ssh://git@example.com/repo.git
        """
        p = wes_file(content)
        parser = WESParser()
        with pytest.raises(ConfigError, match="missing required fields"):
            parser.parse(p)

    def test_missing_git_url(self, wes_file) -> None:
        content = """
        sequence:
            my-job:
                ssh: hpc
                job: job.sh
        """
        p = wes_file(content)
        parser = WESParser()
        with pytest.raises(ConfigError, match="missing required fields.*git_url"):
            parser.parse(p)

    def test_empty_git_url(self, wes_file) -> None:
        content = """
        sequence:
            my-job:
                git_url: ""
                ssh: hpc
                job: job.sh
        """
        p = wes_file(content)
        parser = WESParser()
        with pytest.raises(ConfigError, match="non-empty string"):
            parser.parse(p)

    def test_empty_ssh(self, wes_file) -> None:
        content = """
        sequence:
            my-job:
                git_url: ssh://git@example.com/repo.git
                ssh: ""
                job: job.sh
        """
        p = wes_file(content)
        parser = WESParser()
        with pytest.raises(ConfigError, match="non-empty string"):
            parser.parse(p)

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
        parser = WESParser()
        with pytest.raises(ConfigError, match="unknown fields"):
            parser.parse(p)

    def test_run_not_list(self, wes_file) -> None:
        content = """
        sequence:
            my-job:
                git_url: ssh://git@example.com/repo.git
                ssh: hpc
                job: job.sh
                run: "not-a-list"
        """
        p = wes_file(content)
        parser = WESParser()
        with pytest.raises(ConfigError, match="'run' must be a list"):
            parser.parse(p)

    def test_artifacts_not_list(self, wes_file) -> None:
        content = """
        sequence:
            my-job:
                git_url: ssh://git@example.com/repo.git
                ssh: hpc
                job: job.sh
                artifacts: "not-a-list"
        """
        p = wes_file(content)
        parser = WESParser()
        with pytest.raises(ConfigError, match="'artifacts' must be a list"):
            parser.parse(p)

    def test_non_yaml_mapping(self, wes_file) -> None:
        p = wes_file("just a string")
        parser = WESParser()
        with pytest.raises(ConfigError, match="must be a YAML mapping"):
            parser.parse(p)

    def test_sequence_not_list_or_dict(self, wes_file) -> None:
        content = """
        sequence: "just a string"
        """
        p = wes_file(content)
        parser = WESParser()
        with pytest.raises(ConfigError, match="must be a list or mapping"):
            parser.parse(p)

    def test_list_item_not_single_key(self, wes_file) -> None:
        content = """
        sequence:
            - key1: val1
              key2: val2
        """
        p = wes_file(content)
        parser = WESParser()
        with pytest.raises(ConfigError, match="single-key mapping"):
            parser.parse(p)
