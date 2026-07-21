from __future__ import annotations

import re
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

    def __init__(self, line: str):
        self.__parse(line)

    def __parse(self, line: str) -> None:
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
            self.name = ""
            self.cpu_total = 0
            self.cpu_alloc = 0
            self.cpu_free = 0
            self.mem_total_mb = 0
            self.mem_alloc_mb = 0
            self.mem_free_mb = 0
            self.gpu_total = 0
            self.gpu_alloc = 0
            self.gpu_free = 0
            return

        self.name = self._parse_scontrol_value(line, "NodeName")

        cpu_total = self._parse_int(self._parse_scontrol_value(line, "Cpus"), 0)
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

        self.cpu_total = cpu_total
        self.cpu_alloc = cpu_alloc
        self.cpu_free = cpu_free
        self.mem_total_mb = mem_total
        self.mem_alloc_mb = mem_alloc
        self.mem_free_mb = mem_free
        self.gpu_total = gpu_total
        self.gpu_alloc = gpu_alloc
        self.gpu_free = gpu_free

    def _parse_scontrol_value(self, line: str, key: str) -> str:
        m = re.search(rf"\b{key}=(\S+)", line)
        return m.group(1) if m else ""

    def _parse_gpu_count(self, gres: str) -> str:
        if not gres or gres == "(null)":
            return "-"
        if "gpu" not in gres.lower():
            return "-"
        parts = gres.split(":")
        for p in reversed(parts):
            cleaned = p.split("(")[0]
            try:
                return str(int(cleaned))
            except ValueError:
                continue
        return gres

    def _parse_gres_alloc(self, gres: str) -> int:
        if not gres or gres == "(null)":
            return 0
        m = re.search(r"gpu:\w+:(\d+)", gres)
        if not m:
            m = re.search(r"gpu:(\d+)", gres)
        if not m:
            return 0
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
        return 0

    def _parse_int(self, s: str, default: int) -> int:
        try:
            return int(s)
        except (ValueError, TypeError):
            return default


class Node:
    def __init__(self, info: NodeInfo, capacity: NodeCapacity):
        self.info = info
        self.capacity = capacity

    def get_info(self) -> NodeInfo:
        return self.info

    def get_capacity(self) -> NodeCapacity:
        return self.capacity
