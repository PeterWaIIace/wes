from __future__ import annotations

import re
import subprocess


def _ssh_run(ssh_config: str, cmd: str) -> list[str]:
    result = subprocess.run(
        ["ssh", ssh_config, cmd],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [
        line
        for line in result.stdout.strip().splitlines()
        if line.strip() and not line.startswith("JOBID")
    ]


def get_cluster_data(ssh: str) -> dict:
    nodes = _get_nodes(ssh)
    raw_jobs = _ssh_run(
        ssh, "squeue -a -o '%i|%u|%j|%T|%M|%N|%P|%R|%C|%m'"
    )
    jobs = []
    for line in raw_jobs:
        parts = line.split("|")
        if len(parts) < 10:
            continue
        jobs.append(
            {
                "job_id": parts[0].strip(),
                "user": parts[1].strip(),
                "name": parts[2].strip(),
                "state": parts[3].strip(),
                "time": parts[4].strip(),
                "nodes": parts[5].strip(),
                "partition": parts[6].strip(),
                "reason": parts[7].strip(),
                "cpus": parts[8].strip(),
                "memory": parts[9].strip(),
            }
        )

    capacity = []
    for n in nodes:
        cap = n["capacity"]
        capacity.append(
            {
                "name": cap["name"],
                "cpu_total": cap["cpu_total"],
                "cpu_alloc": cap["cpu_alloc"],
                "cpu_free": cap["cpu_free"],
                "mem_total_mb": cap["mem_total_mb"],
                "mem_alloc_mb": cap["mem_alloc_mb"],
                "mem_free_mb": cap["mem_free_mb"],
                "gpu_total": cap["gpu_total"],
                "gpu_alloc": cap["gpu_alloc"],
                "gpu_free": cap["gpu_free"],
            }
        )

    return {
        "ssh": ssh,
        "nodes": [
            {
                "name": n["name"],
                "partition": n["partition"],
                "state": n["state"],
                "cpus": n["cpus"],
                "gpus": n["gpus"],
                "memory": n["memory"],
                "reason": n["reason"],
            }
            for n in nodes
        ],
        "capacity": capacity,
        "jobs": jobs,
    }


def get_nodes(ssh: str) -> list[dict]:
    return [
        {
            "name": n["name"],
            "partition": n["partition"],
            "state": n["state"],
            "cpus": n["cpus"],
            "gpus": n["gpus"],
            "memory": n["memory"],
            "reason": n["reason"],
        }
        for n in _get_nodes(ssh)
    ]


def _get_nodes(ssh: str) -> list[dict]:
    info_lines = _ssh_run(ssh, "sinfo -N -o '%N|%P|%T|%C|%G|%m|%R'")
    cap_lines = _ssh_run(ssh, "scontrol show nodes -o")

    infos: dict[str, dict] = {}
    for line in info_lines:
        parts = line.split("|")
        if len(parts) < 6:
            continue
        name = parts[0].strip()
        infos[name] = {
            "name": name,
            "partition": parts[1].strip().rstrip("*"),
            "state": parts[2].strip(),
            "cpus": parts[3].strip(),
            "gpus": parts[4].strip(),
            "memory": parts[5].strip(),
            "reason": parts[6].strip() if len(parts) > 6 else "",
        }

    caps: dict[str, dict] = {}
    for line in cap_lines:
        cap = _parse_node_capacity(line)
        if cap:
            caps[cap["name"]] = cap

    nodes = []
    for name in sorted(set(infos) | set(caps)):
        if name in infos and name in caps:
            node = dict(infos[name])
            node["capacity"] = caps[name]
            nodes.append(node)
    return nodes


def _parse_node_capacity(line: str) -> dict | None:
    line = line.strip()
    if not line or not line.startswith("NodeName="):
        return None

    name = _sc_val(line, "NodeName")

    cpu_total = _int(_sc_val(line, "Cpus"), 0)
    if cpu_total == 0:
        sockets = _int(_sc_val(line, "Sockets"), 0)
        cores = _int(_sc_val(line, "CoresPerSocket"), 0)
        cpu_total = sockets * cores

    cpu_alloc = _int(_sc_val(line, "CPUAlloc"), 0)
    cpu_free = max(cpu_total - cpu_alloc, 0)

    mem_total = _int(_sc_val(line, "RealMemory"), 0)
    mem_alloc = _int(_sc_val(line, "AllocMem"), 0)
    mem_free_str = _sc_val(line, "FreeMem")
    mem_free = _int(mem_free_str, max(mem_total - mem_alloc, 0))

    gres = _sc_val(line, "Gres")
    gpu_total = _int(_parse_gpu_count(gres), 0)
    gpu_alloc = _parse_gres_alloc(gres) if gres else 0
    gpu_free = max(gpu_total - gpu_alloc, 0)

    return {
        "name": name,
        "cpu_total": cpu_total,
        "cpu_alloc": cpu_alloc,
        "cpu_free": cpu_free,
        "mem_total_mb": mem_total,
        "mem_alloc_mb": mem_alloc,
        "mem_free_mb": mem_free,
        "gpu_total": gpu_total,
        "gpu_alloc": gpu_alloc,
        "gpu_free": gpu_free,
    }


def _sc_val(line: str, key: str) -> str:
    m = re.search(rf"\b{key}=(\S+)", line)
    return m.group(1) if m else ""


def _parse_gpu_count(gres: str) -> str:
    if not gres or gres == "(null)" or "gpu" not in gres.lower():
        return "-"
    parts = gres.split(":")
    for p in reversed(parts):
        cleaned = p.split("(")[0]
        try:
            return str(int(cleaned))
        except ValueError:
            continue
    return gres


def _parse_gres_alloc(gres: str) -> int:
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


def _int(s: str, default: int) -> int:
    try:
        return int(s)
    except (ValueError, TypeError):
        return default


def cancel_slurm_jobs(ssh: str, job_ids: list[str]) -> list[str]:
    messages: list[str] = []
    for jid in job_ids:
        try:
            result = subprocess.run(
                ["ssh", ssh, f"scancel {jid}"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                messages.append(f"cancelled slurm job {jid}")
        except Exception:
            pass
    return messages


def remove_remote_dir(ssh: str, path: str) -> bool:
    try:
        result = subprocess.run(
            ["ssh", ssh, f"rm -rf {path}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def check_jobs_alive(ssh: str, job_ids: list[str]) -> bool:
    if not job_ids:
        return False
    lines = _ssh_run(ssh, f"squeue -j {','.join(job_ids)} -h -o '%T'")
    alive_states = {"RUNNING", "PENDING", "SUSPENDED", "COMPLETING"}
    for line in lines:
        state = line.strip()
        if state in alive_states:
            return True
    return False


def read_remote_log(ssh: str, path: str) -> str:
    lines = _ssh_run(ssh, f"cat {path}")
    return "\n".join(lines)
