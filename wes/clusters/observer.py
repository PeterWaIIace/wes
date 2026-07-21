from __future__ import annotations

from wes.clusters.node import Node, NodeCapacity, NodeInfo
from wes.remote.runner import _ssh_run


class NodesObserver:
    def __init__(self, ssh_config: str):
        self.ssh_config = ssh_config

    def __get_server_nodes_info(self) -> list[NodeInfo]:
        fmt = "%N|%P|%T|%C|%G|%m|%R"
        lines = _ssh_run(self.ssh_config, f"sinfo -N -o '{fmt}'")
        infos: list[NodeInfo] = []
        for line in lines:
            infos.append(NodeInfo(line))
        return infos

    def __get_server_nodes_capacity(self) -> list[NodeCapacity]:
        lines = _ssh_run(self.ssh_config, "scontrol show nodes -o")
        capacities: list[NodeCapacity] = []
        for line in lines:
            capacities.append(NodeCapacity(line))
        return capacities

    def get_nodes(self) -> list[Node]:
        infos = sorted(self.__get_server_nodes_info(), key=lambda c: c.name)
        capacities = sorted(self.__get_server_nodes_capacity(), key=lambda c: c.name)
        nodes = []
        for info, capacity in zip(infos, capacities, strict=True):
            nodes.append(Node(info, capacity))
        return nodes
