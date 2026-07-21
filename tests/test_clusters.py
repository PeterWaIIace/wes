from __future__ import annotations

from unittest.mock import patch

from wes import WES
from wes.cluster import Cluster
from wes.clusters.node import Node, NodeCapacity, NodeInfo
from wes.clusters.observer import NodesObserver
from wes.jobs.job import JobInfo
from wes.jobs.query import JobsQuery

SCONTROL_GPU0 = (
    "NodeName=gpu0 Cpus=8 CPUAlloc=4 RealMemory=32000"
    " AllocMem=16000 FreeMem=15000 Gres=gpu:rtx_3090:2(IDX:0-1)"
)
SCONTROL_CPU0 = (
    "NodeName=cpu0 Cpus=4 CPUAlloc=0 RealMemory=8000 AllocMem=0 FreeMem=8000 Gres=(null)"
)
SCONTROL_BIG0 = (
    "NodeName=big0 Sockets=2 CoresPerSocket=16 CPUAlloc=10"
    " RealMemory=128000 AllocMem=64000 FreeMem=63000 Gres=(null)"
)
SCONTROL_GPU1 = (
    "NodeName=gpu1 Cpus=8 CPUAlloc=0 RealMemory=32000"
    " AllocMem=0 FreeMem=31000 Gres=gpu:a100:4(IDX:0-1)"
)
SCONTROL_V100 = (
    "NodeName=gpu0 Cpus=8 CPUAlloc=0 RealMemory=32000 AllocMem=0 FreeMem=32000 Gres=gpu:v100:1"
)


# --- NodeInfo ---


class TestNodeInfo:
    def test_parse_standard_line(self) -> None:
        info = NodeInfo("gpu0|gpu|idle|8|1|32000|none")
        assert info.name == "gpu0"
        assert info.partition == "gpu"
        assert info.state == "idle"
        assert info.cpus == "8"
        assert info.gpus == "1"
        assert info.memory == "32000"
        assert info.reason == "none"

    def test_parse_strips_star_from_partition(self) -> None:
        info = NodeInfo("node1|compute*|alloc|4|0|16000|")
        assert info.partition == "compute"

    def test_parse_no_reason(self) -> None:
        info = NodeInfo("node1|compute|idle|4|0|16000")
        assert info.reason == ""

    def test_parse_too_few_fields_raises(self) -> None:
        try:
            NodeInfo("node1|compute|idle")
        except ValueError as e:
            assert "Invalid sinfo line" in str(e)
        else:
            raise AssertionError("Should have raised ValueError")

    def test_parse_strips_whitespace(self) -> None:
        info = NodeInfo(
            "  gpu0  |  gpu  |  idle  |  8  |  1  |  32000  |  none  "
        )
        assert info.name == "gpu0"
        assert info.partition == "gpu"
        assert info.state == "idle"
        assert info.cpus == "8"
        assert info.gpus == "1"
        assert info.memory == "32000"
        assert info.reason == "none"


# --- NodeCapacity ---


class TestNodeCapacity:
    def test_parse_standard_scontrol_line(self) -> None:
        cap = NodeCapacity(SCONTROL_GPU0)
        assert cap.name == "gpu0"
        assert cap.cpu_total == 8
        assert cap.cpu_alloc == 4
        assert cap.cpu_free == 4
        assert cap.mem_total_mb == 32000
        assert cap.mem_alloc_mb == 16000
        assert cap.mem_free_mb == 15000
        assert cap.gpu_total == 2
        assert cap.gpu_alloc == 2

    def test_parse_empty_line(self) -> None:
        cap = NodeCapacity("")
        assert cap.name == ""
        assert cap.cpu_total == 0
        assert cap.gpu_total == 0

    def test_parse_non_scontrol_line(self) -> None:
        cap = NodeCapacity("random text")
        assert cap.name == ""

    def test_parse_no_gres(self) -> None:
        cap = NodeCapacity(SCONTROL_CPU0)
        assert cap.name == "cpu0"
        assert cap.gpu_total == 0
        assert cap.gpu_alloc == 0
        assert cap.gpu_free == 0

    def test_parse_sockets_cores_fallback(self) -> None:
        cap = NodeCapacity(SCONTROL_BIG0)
        assert cap.cpu_total == 32
        assert cap.cpu_alloc == 10
        assert cap.cpu_free == 22

    def test_parse_gres_with_range_allocation(self) -> None:
        cap = NodeCapacity(SCONTROL_GPU1)
        assert cap.gpu_total == 4
        assert cap.gpu_alloc == 2


# --- Node ---


class TestNode:
    def test_node_holds_info_and_capacity(self) -> None:
        info = NodeInfo("gpu0|gpu|idle|8|1|32000|ready")
        cap = NodeCapacity(SCONTROL_V100)
        node = Node(info, cap)
        assert node.get_info() is info
        assert node.get_capacity() is cap

    def test_node_fields_are_correct(self) -> None:
        info = NodeInfo("node1|compute|alloc|4|0|16000|")
        cap = NodeCapacity(
            "NodeName=node1 Cpus=4 CPUAlloc=4 RealMemory=16000 AllocMem=16000 FreeMem=0 Gres=(null)"
        )
        node = Node(info, cap)
        assert node.info.name == "node1"
        assert node.capacity.cpu_total == 4
        assert node.capacity.cpu_alloc == 4


# --- NodesObserver (mocked SSH) ---


class TestNodesObserver:
    @patch("wes.clusters.observer._ssh_run")
    def test_get_nodes_pairs_info_and_capacity(self, mock_ssh):
        mock_ssh.side_effect = [
            ["gpu0|gpu|idle|8|1|32000|none", "cpu0|compute|idle|4|0|8000|"],
            [SCONTROL_V100, SCONTROL_CPU0],
        ]
        observer = NodesObserver("testhost")
        nodes = observer.get_nodes()
        assert len(nodes) == 2
        assert nodes[0].info.name == "cpu0"
        assert nodes[0].capacity.name == "cpu0"
        assert nodes[1].info.name == "gpu0"
        assert nodes[1].capacity.name == "gpu0"

    @patch("wes.clusters.observer._ssh_run")
    def test_get_nodes_empty(self, mock_ssh):
        mock_ssh.side_effect = [[], []]
        observer = NodesObserver("testhost")
        nodes = observer.get_nodes()
        assert nodes == []


# --- JobsQuery (mocked SSH) ---


class TestJobsQuery:
    @patch("wes.jobs.query._ssh_run")
    def test_get_parses_jobs(self, mock_ssh):
        mock_ssh.return_value = [
            "12345|user1|train|RUNNING|00:30|gpu0|gpu||2|8000",
            "12346|user2|eval|PENDING|0:00||compute||4|16000",
        ]
        query = JobsQuery("testhost")
        jobs = query.get()
        assert len(jobs) == 2
        assert jobs[0].job_id == "12345"
        assert jobs[0].user == "user1"
        assert jobs[0].name == "train"
        assert jobs[0].state == "RUNNING"
        assert jobs[0].cpus == "2"
        assert jobs[1].job_id == "12346"
        assert jobs[1].partition == "compute"

    @patch("wes.jobs.query._ssh_run")
    def test_get_skips_short_lines(self, mock_ssh):
        mock_ssh.return_value = [
            "12345|user1|train|RUNNING|00:30|gpu0|gpu||2|8000",
            "bad|line",
        ]
        query = JobsQuery("testhost")
        jobs = query.get()
        assert len(jobs) == 1

    @patch("wes.jobs.query._ssh_run")
    def test_get_empty(self, mock_ssh):
        mock_ssh.return_value = []
        query = JobsQuery("testhost")
        jobs = query.get()
        assert jobs == []


# --- Cluster facade ---


class TestCluster:
    @patch("wes.cluster.NodesObserver")
    @patch("wes.cluster.JobsQuery")
    def test_get_jobs(self, mock_jobs_cls, mock_nodes_cls):
        mock_jobs_cls.return_value.get.return_value = [
            JobInfo("1", "u", "j", "RUNNING", "0:1", "n", "p", "", "1", "1G")
        ]
        cluster = Cluster("host")
        jobs = cluster.get_jobs()
        assert len(jobs) == 1
        assert jobs[0].job_id == "1"

    @patch("wes.cluster.NodesObserver")
    @patch("wes.cluster.JobsQuery")
    def test_get_nodes(self, mock_jobs_cls, mock_nodes_cls):
        info = NodeInfo("gpu0|gpu|idle|8|1|32000|")
        cap = NodeCapacity(SCONTROL_V100)
        mock_nodes_cls.return_value.get_nodes.return_value = [Node(info, cap)]
        cluster = Cluster("host")
        nodes = cluster.get_nodes()
        assert len(nodes) == 1
        assert nodes[0].info.name == "gpu0"

    @patch("wes.cluster.Cluster.get_nodes")
    def test_get_capacity(self, mock_get_nodes):
        info = NodeInfo("gpu0|gpu|idle|8|1|32000|")
        cap = NodeCapacity(SCONTROL_V100)
        mock_get_nodes.return_value = [Node(info, cap)]
        cluster = Cluster("host")
        caps = cluster.get_capacity()
        assert len(caps) == 1
        assert caps[0].name == "gpu0"
        assert caps[0].cpu_total == 8


# --- WES (public API) ---


class TestWES:
    @patch("wes.Cluster")
    def test_get_nodes(self, mock_cluster_cls):
        info = NodeInfo("gpu0|gpu|idle|8|1|32000|")
        cap = NodeCapacity(SCONTROL_V100)
        mock_cluster_cls.return_value.get_nodes.return_value = [
            Node(info, cap)
        ]
        wes = WES("host")
        nodes = wes.get_nodes()
        assert len(nodes) == 1
        assert nodes[0].name == "gpu0"
        mock_cluster_cls.assert_called_once_with("host")

    @patch("wes.Cluster")
    def test_get_jobs(self, mock_cluster_cls):
        mock_cluster_cls.return_value.get_jobs.return_value = [
            JobInfo("1", "u", "j", "RUNNING", "0:1", "n", "p", "", "1", "1G")
        ]
        wes = WES("host")
        jobs = wes.get_jobs()
        assert len(jobs) == 1
        assert jobs[0].job_id == "1"

    @patch("wes.Cluster")
    def test_get_capacity(self, mock_cluster_cls):
        cap = NodeCapacity(SCONTROL_V100)
        mock_cluster_cls.return_value.get_capacity.return_value = [cap]
        wes = WES("host")
        caps = wes.get_capacity()
        assert len(caps) == 1
        assert caps[0].name == "gpu0"
