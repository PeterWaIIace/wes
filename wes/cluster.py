from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from wes.nodes.node import Node
from wes.jobs.job import JobInfo
from wes.jobs.query import JobsQuery
from wes.clusters.observer import NodesObserver

class Cluster: 

    def __init__(self, ssh_config: str):
        self.ssh_config = ssh_config

    def get_jobs(self) -> list[JobInfo]:
        return JobsQuery(self.ssh_config).get()

    def get_nodes(self) -> list[Node]:
        return NodesObserver(self.ssh_config).get_nodes()