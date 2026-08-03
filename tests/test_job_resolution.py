from __future__ import annotations

from unittest.mock import Mock, patch

from wes.jobs.job import JobInfo


def _info(name: str, job_id: str = "123", state: str = "RUNNING") -> JobInfo:
    return JobInfo(
        job_id=job_id,
        user="u",
        name=name,
        state=state,
        time="00:01",
        nodes="n",
        partition="p",
        reason="",
        cpus="2",
        memory="8G",
    )


class TestFindSlurmJob:
    def _query(self) -> Mock:
        query = Mock()
        query.get.return_value = [_info("train_ns123")]
        return query

    def test_match_by_slurm_id(self) -> None:
        from web.routers.jobs import _find_slurm_job

        assert _find_slurm_job(self._query(), "123", None) is not None

    def test_match_by_namespace(self) -> None:
        from web.routers.jobs import _find_slurm_job

        assert _find_slurm_job(self._query(), "ns123", None) is not None

    def test_match_by_cached_jobs_ids(self) -> None:
        from web.routers.jobs import _find_slurm_job

        assert _find_slurm_job(self._query(), "ns123", {"jobs_ids": ["123"]}) is not None

    def test_no_match(self) -> None:
        from web.routers.jobs import _find_slurm_job

        assert _find_slurm_job(self._query(), "other", None) is None


class TestReachableHosts:
    @patch("web.routers.jobs.known_ssh_hosts", return_value=["hpc1", "hpc2"])
    @patch("web.routers.jobs.SshRunner")
    def test_all_reachable(self, mock_runner, _mock_hosts) -> None:
        mock_runner.return_value.run_command.return_value = (True, [])
        from web.routers.jobs import _reachable_hosts

        assert _reachable_hosts() == {"hpc1", "hpc2"}

    @patch("web.routers.jobs.known_ssh_hosts", return_value=["hpc1", "hpc2"])
    @patch("web.routers.jobs.SshRunner")
    def test_partial_outage(self, mock_runner, _mock_hosts) -> None:
        mock_runner.return_value.run_command.side_effect = [(True, []), (False, [])]
        from web.routers.jobs import _reachable_hosts

        assert _reachable_hosts() == {"hpc1"}

    @patch("web.routers.jobs.known_ssh_hosts", return_value=["hpc1", "hpc2"])
    @patch("web.routers.jobs.SshRunner")
    def test_full_outage(self, mock_runner, _mock_hosts) -> None:
        mock_runner.return_value.run_command.return_value = (False, [])
        from web.routers.jobs import _reachable_hosts

        assert _reachable_hosts() == set()


class TestCheckJobsAlive:
    def test_alive_when_id_present(self) -> None:
        from web.engine import check_jobs_alive

        with patch("web.engine.JobsQuery") as mq:
            q = mq.return_value
            q.get.return_value = [_info("train_ns123")]
            assert check_jobs_alive("hpc", ["123"]) is True

    def test_dead_when_id_missing(self) -> None:
        from web.engine import check_jobs_alive

        with patch("web.engine.JobsQuery") as mq:
            q = mq.return_value
            q.get.return_value = []
            assert check_jobs_alive("hpc", ["123"]) is False
