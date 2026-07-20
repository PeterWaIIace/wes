from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class NodeInfo:
    name: str
    partition: str
    state: str
    cpus: str
    gpus: str
    memory: str
    reason: str = ""


def get_nodes(ssh_config: str) -> list[NodeInfo]:
    """Query SLURM node availability via SSH.

    Uses sinfo with explicit format to get clean, parseable output:
      name | partition | state | cpus(alloc/idle/total) | gres | memory | reason

    Args:
        ssh_config: SSH host/config name (e.g. "hpc" or "~/.ssh/config entry")

    Returns:
        List of NodeInfo with name, partition, state, cpus, gpus, memory, reason.
    """
    fmt = "%N|%P|%T|%C|%G|%m|%R"
    result = subprocess.run(
        ["ssh", ssh_config, f"sinfo -N -o '{fmt}'"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []

    nodes: list[NodeInfo] = []
    for line in result.stdout.strip().splitlines():
        if not line.strip() or line.startswith("NODELIST"):
            continue
        parts = line.split("|")
        if len(parts) < 6:
            continue
        name = parts[0].strip()
        partition = parts[1].strip().rstrip("*")
        state = parts[2].strip()
        cpus = parts[3].strip()
        gres = parts[4].strip()
        memory = parts[5].strip()
        reason = parts[6].strip() if len(parts) > 6 else ""

        gpu_count = _parse_gpu_count(gres)

        nodes.append(
            NodeInfo(
                name=name,
                partition=partition,
                state=state,
                cpus=cpus,
                gpus=gpu_count,
                memory=f"{memory}M",
                reason=reason,
            )
        )
    return nodes


def _parse_gpu_count(gres: str) -> str:
    """Parse GPU count from GRES string like 'gpu:rtx_2070_super:1' or '(null)'."""
    if not gres or gres == "(null)":
        return "-"
    if "gpu" not in gres.lower():
        return "-"
    parts = gres.split(":")
    # last numeric part is the count
    for p in reversed(parts):
        try:
            return str(int(p))
        except ValueError:
            continue
    return gres
