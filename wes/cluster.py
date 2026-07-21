from __future__ import annotations

from wes.clusters.node import Node, NodeCapacity
from wes.clusters.observer import NodesObserver
from wes.jobs.job import JobInfo
from wes.jobs.query import JobsQuery


class Cluster:

    def __init__(self, ssh_config: str):
        self.ssh_config = ssh_config

    def get_jobs(self) -> list[JobInfo]:
        return JobsQuery(self.ssh_config).get()

    def get_nodes(self) -> list[Node]:
        return NodesObserver(self.ssh_config).get_nodes()

    def get_capacity(self) -> list[NodeCapacity]:
        return [n.capacity for n in self.get_nodes()]
