
import re
import subprocess
from dataclasses import dataclass, field
from wes.remote.runner import _ssh_run
from wes.jobs.query import JobsQuery
from wes.clusters.node import Node, NodeInfo, NodeCapacity


class NodesObserver:

    def __init__(self, ssh_config: str):
        self.ssh_config = ssh_config
        self.nodes : list[Node] = None

    def __get_server_nodes_info(self) -> list[NodeInfo]:
        """Query SLURM node availability via SSH.

        Uses sinfo with explicit format to get clean, parseable output:
        name | partition | state | cpus(alloc/idle/total) | gres | memory | reason

        Args:
            ssh_config: SSH host/config name (e.g. "hpc" or "~/.ssh/config entry")

        Returns:
            List of NodeInfo with name, partition, state, cpus, gpus, memory, reason.
        """
        fmt = "%N|%P|%T|%C|%G|%m|%R"
        lines = _ssh_run(self.ssh_config, f"sinfo -N -o '{fmt}'")
        infos: list[NodeInfo] = []

        for line in lines:
            infos.append(NodeInfo(line))
        return infos

    def __get_server_nodes_capacity(self) -> list[NodeCapacity]:
        lines = _ssh_run(self.ssh_config, f"sinfo -N -o '{fmt}'")
        capacities: list[NodeCapacity] = []
        for line in lines:
            capacities.append(NodeCapacity(line))
        return capacities

    def get_nodes(self) -> list[NodeInfo]:
        """Query SLURM node availability via SSH.

        Uses sinfo with explicit format to get clean, parseable output:
        name | partition | state | cpus(alloc/idle/total) | gres | memory | reason

        Args:
            ssh_config: SSH host/config name (e.g. "hpc" or "~/.ssh/config entry")

        Returns:
            List of NodeInfo with name, partition, state, cpus, gpus, memory, reason.
        """
        infos = sorted(self.__get_server_nodes_info(), lambda c : c.name)
        capacities = sorted(self.__get_server_nodes_capacity(), lambda c : c.name)
        nodes = []

        for info, capacity in zip(infos, capacities):
            nodes.append(NodeInfo(info, capacity))
        return nodes
