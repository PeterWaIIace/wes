from __future__ import annotations

from wes.clusters.node import Node, NodeCapacity, NodeInfo
from wes.remote.runner import SshRunner


class NodesObserver:
    def __init__(self, ssh_config: str):
        self.ssh_config = ssh_config

    def __get_server_nodes_info(self) -> list[NodeInfo]:
        fmt = "%N|%P|%T|%C|%G|%m|%R"
        ok, lines = SshRunner(self.ssh_config).run_command(f"sinfo -N -o '{fmt}'")
        if not ok:
            return []
        infos: list[NodeInfo] = []
        for line in lines:
            infos.append(NodeInfo(line))
        return infos

    def __get_server_nodes_capacity(self) -> list[NodeCapacity]:
        ok, lines = SshRunner(self.ssh_config).run_command("scontrol show nodes -o")
        if not ok:
            return []
        capacities: list[NodeCapacity] = []
        for line in lines:
            capacities.append(NodeCapacity(line))
        return capacities

    def get_nodes(self) -> list[Node]:
        infos = {info.name: info for info in self.__get_server_nodes_info()}
        capacities = {cap.name: cap for cap in self.__get_server_nodes_capacity()}
        nodes = []
        for name in sorted(set(infos) | set(capacities)):
            info = infos.get(name)
            cap = capacities.get(name)
            if info and cap:
                nodes.append(Node(info, cap))
        return nodes
