
import re
import subprocess
from dataclasses import dataclass, field
from wes.remote.runner import _ssh_run
from wes.jobs.query import JobsQuery
from wes.clusters.node import JobInfo, NodeInfo, NodeCapacity

@dataclass
class NodeInfo:
    name: str
    partition: str
    state: str
    cpus: str
    gpus: str
    memory: str
    reason: str = ""

    def __init__(self, line):
        self.__parse(line)

    def __parse(self, line: str) -> None:
        """Parse a sinfo line into NodeInfo fields."""
        parts = line.split("|")
        if len(parts) < 6:
            raise ValueError(f"Invalid sinfo line: {line}")
        self.name = parts[0].strip()
        self.partition = parts[1].strip().rstrip("*")
        self.state = parts[2].strip()
        self.cpus = parts[3].strip()
        self.gpus = parts[4].strip()
        self.memory = parts[5].strip()
        self.reason = parts[6].strip() if len(parts) > 6 else ""


@dataclass
class NodeCapacity:
    name: str
    cpu_total: int
    cpu_alloc: int
    cpu_free: int
    mem_total_mb: int
    mem_alloc_mb: int
    mem_free_mb: int
    gpu_total: int
    gpu_alloc: int
    gpu_free: int

    def __init__(self, line: str):
        self.__parse(line)

    def __parse(self, line: str) -> None:
        line = line.strip()
        if not line or not line.startswith("NodeName="):
            return

        name = self._parse_scontrol_value(line, "NodeName")
        if not name:
            return

        cpu_total = self._parse_int(self._parse_scontrol_value(line, "Cpus"), 0)
        # try CPUSockets * CoresPerSocket as fallback
        if cpu_total == 0:
            sockets = self._parse_int(self._parse_scontrol_value(line, "Sockets"), 0)
            cores = self._parse_int(self._parse_scontrol_value(line, "CoresPerSocket"), 0)
            cpu_total = sockets * cores

        cpu_alloc = self._parse_int(self._parse_scontrol_value(line, "CPUAlloc"), 0)
        cpu_free = max(cpu_total - cpu_alloc, 0)

        mem_total = self._parse_int(self._parse_scontrol_value(line, "RealMemory"), 0)
        mem_alloc = self._parse_int(self._parse_scontrol_value(line, "AllocMem"), 0)
        mem_free_str = self._parse_scontrol_value(line, "FreeMem")
        mem_free = self._parse_int(mem_free_str, max(mem_total - mem_alloc, 0))

        gres = self._parse_scontrol_value(line, "Gres")
        gpu_total = self._parse_int(self._parse_gpu_count(gres), 0)
        gpu_alloc = self._parse_gres_alloc(gres) if gres else 0
        gpu_free = max(gpu_total - gpu_alloc, 0)

    def _parse_scontrol_value(self, line: str, key: str) -> str:
        """Extract a value from a scontrol one-line output like 'Key=Value'."""
        m = re.search(rf"\b{key}=(\S+)", line)
        return m.group(1) if m else ""

    def _parse_gpu_count(self, gres: str) -> str:
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

    def _parse_gres_alloc(self, gres: str) -> int:
        """Parse allocated GPUs from GRES like 'gpu:rtx_2070_super:2(IDX:0-1)'."""
        if not gres or gres == "(null)":
            return 0
        # match gpu:type:N or gpu:N where N is total
        m = re.search(r"gpu:\w+:(\d+)", gres)
        if not m:
            m = re.search(r"gpu:(\d+)", gres)
        if not m:
            return 0
        # allocated = total - count of free indices
        idx_match = re.search(r"IDX:([\d,-]+)", gres)
        if idx_match:
            allocated = 0
            for part in idx_match.group(1).split(","):
                if "-" in part:
                    lo, hi = part.split("-", 1)
                    allocated += int(hi) - int(lo) + 1
                else:
                    allocated += 1
            return allocated
        # no IDX info, use node state to estimate
        return 0

    def _parse_int(self, s: str, default: int) -> int:
        try:
            return int(s)
        except (ValueError, TypeError):
            return default

class Node:

    def __init__(self, info: NodeInfo, capacity: NodeCapacity):
        self.capacity : NodeCapacity = info
        self.info : NodeInfo = capacity


    def get_info(self) -> NodeInfo:
        return self.info

    def get_capacity(self, ssh_config: str) -> NodeCapacity:
        return self.capacity