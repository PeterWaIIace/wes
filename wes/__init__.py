from __future__ import annotations

from wes.cluster import Cluster
from wes.clusters.node import NodeCapacity
from wes.jobs.job import JobInfo


class WES:
    def __init__(self, ssh_config: str):
        self.cluster = Cluster(ssh_config)

    def get_nodes(self) -> list:
        return [n.info for n in self.cluster.get_nodes()]

    def get_jobs(self) -> list[JobInfo]:
        return self.cluster.get_jobs()

    def get_capacity(self) -> list[NodeCapacity]:
        return self.cluster.get_capacity()
