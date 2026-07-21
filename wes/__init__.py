from __future__ import annotations

from wes.cluster import Cluster
from wes.clusters.node import NodeCapacity, NodeInfo
from wes.jobs.job import JobInfo, SlurmJob


class WES:

    def __init__(self, ssh_config: str):
        self.ssh_config = ssh_config

    def get_nodes(self) -> list[NodeInfo]:
        return [n.info for n in Cluster(self.ssh_config).get_nodes()]

    def get_jobs(self) -> list[JobInfo]:
        return Cluster(self.ssh_config).get_jobs()

    def get_capacity(self) -> list[NodeCapacity]:
        return Cluster(self.ssh_config).get_capacity()
