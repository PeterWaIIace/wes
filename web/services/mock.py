from __future__ import annotations

import base64
import hashlib
import os
import random
import time

from web.models import JobSummary, LogData, TaskInfo

JOB_NAMES = {
    "gpu": [
        "train_bert_base",
        "finetune_gpt_jb",
        "infer_llama_70b",
        "train_vit_large",
        "hyperparam_sweep_gpu",
        "multi_gpu_tune",
        "distil_whisper",
        "train_clip",
    ],
    "cpu": [
        "data_prep_imagenet",
        "tokenize_corpus",
        "compute_stats",
        "matrix_factorization",
        "vector_index_build",
        "crawl_dataset",
        "augment_dataset",
        "benchmark_io",
    ],
    "himem": [
        "assemble_genome",
        "graph_embedding",
        "large_sort",
        "feature_engineering",
    ],
    "short": [
        "lint_and_smoke",
        "unit_test_runner",
        "render_frames",
        "sync_artifacts",
    ],
}

USERS = [
    "alice",
    "bob",
    "carol",
    "dave",
    "erin",
    "frank",
    "grace",
    "henry",
    "irene",
    "james",
]

PENDING_REASONS = [
    "(Resources)",
    "(Priority)",
    "(QOSMaxCpuPerUserLimit)",
    "(Dependency)",
    "(License)",
    "(AssocGrpMemLimit)",
]

MOCK_TASKS: list[dict] = [
    {
        "name": "train_bert_base",
        "git_url": "ssh://git@git.mock/nlp/bert_base.git",
        "branch": "main",
        "ssh": "mock",
        "job": "scripts/train.sh",
        "path": ".",
        "pre": "scripts/prepare_data.sh",
        "artifacts": ["results", "checkpoints", "logs"],
        "partition": "gpu",
        "cpus": "16",
        "gpus": "8",
        "memory": "64G",
        "time": "04:00:00",
    },
    {
        "name": "finetune_gpt_jb",
        "git_url": "ssh://git@git.mock/nlp/gpt_jb.git",
        "branch": "release/v2",
        "ssh": "mock",
        "job": "scripts/finetune.sh",
        "path": ".",
        "artifacts": ["results", "logs"],
        "partition": "gpu",
        "cpus": "8",
        "gpus": "4",
        "memory": "32G",
        "time": "08:00:00",
    },
    {
        "name": "train_vit_large",
        "git_url": "ssh://git@git.mock/vision/vit_large.git",
        "branch": "main",
        "ssh": "mock",
        "job": "scripts/train.sh",
        "path": ".",
        "artifacts": ["results", "checkpoints"],
        "partition": "gpu",
        "cpus": "16",
        "gpus": "8",
        "memory": "64G",
        "time": "12:00:00",
    },
    {
        "name": "data_prep_imagenet",
        "git_url": "ssh://git@git.mock/data/imagenet_pipeline.git",
        "branch": "main",
        "ssh": "mock",
        "job": "scripts/prepare.sh",
        "path": ".",
        "artifacts": ["shards", "logs"],
        "partition": "cpu",
        "cpus": "32",
        "gpus": "0",
        "memory": "64G",
        "time": "24:00:00",
    },
    {
        "name": "tokenize_corpus",
        "git_url": "ssh://git@git.mock/data/tokenizer.git",
        "branch": "main",
        "ssh": "mock",
        "job": "scripts/tokenize.sh",
        "path": ".",
        "artifacts": ["tokens", "logs"],
        "partition": "cpu",
        "cpus": "16",
        "gpus": "0",
        "memory": "32G",
        "time": "12:00:00",
    },
    {
        "name": "compute_stats",
        "git_url": "ssh://git@git.mock/analysis/stats.git",
        "branch": "main",
        "ssh": "mock",
        "job": "scripts/stats.sh",
        "path": ".",
        "artifacts": ["results"],
        "partition": "cpu",
        "cpus": "8",
        "gpus": "0",
        "memory": "16G",
        "time": "06:00:00",
    },
    {
        "name": "assemble_genome",
        "git_url": "ssh://git@git.mock/genomics/assembler.git",
        "branch": "main",
        "ssh": "mock",
        "job": "scripts/assemble.sh",
        "path": ".",
        "artifacts": ["contigs", "logs"],
        "partition": "himem",
        "cpus": "32",
        "gpus": "0",
        "memory": "768G",
        "time": "48:00:00",
    },
    {
        "name": "unit_test_runner",
        "git_url": "ssh://git@git.mock/qa/tests.git",
        "branch": "main",
        "ssh": "mock",
        "job": "scripts/test.sh",
        "path": ".",
        "artifacts": ["reports"],
        "partition": "short",
        "cpus": "4",
        "gpus": "0",
        "memory": "8G",
        "time": "00:30:00",
    },
]

TERMINAL_STATES = ("COMPLETED", "FAILED", "CANCELLED")
STATE_ORDER = {"RUNNING": 0, "PENDING": 1, "COMPLETED": 2, "FAILED": 3, "CANCELLED": 4}

MAX_ACTIVE_JOBS = 18
TERMINAL_RETENTION_MIN = 35


def _fmt_mem(mb: int) -> str:
    if mb >= 1024:
        return f"{mb // 1024}G"
    return f"{mb}M"


def _fmt_time(minutes: float) -> str:
    total = max(0, int(minutes * 60))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def _build_nodes() -> list[dict]:
    nodes: list[dict] = []

    def add(
        prefix: str,
        start: int,
        count: int,
        width: int,
        partition: str,
        cpus: int,
        gpus: int,
        mem_mb: int,
        role: str | None = None,
    ) -> None:
        for i in range(count):
            nodes.append(
                {
                    "name": f"{prefix}-{start + i:0{width}d}",
                    "partition": partition,
                    "cpus": str(cpus),
                    "gpus": str(gpus),
                    "memory": _fmt_mem(mem_mb),
                    "total_cpu": cpus,
                    "total_gpu": gpus,
                    "total_mem_mb": mem_mb,
                    "role": role,
                    "reason": "",
                }
            )

    add("node", 1, 2, 3, "cpu", 64, 0, 262144)
    add("node", 9, 2, 3, "cpu", 32, 0, 131072)
    add("gpu", 1, 2, 2, "gpu", 16, 8, 262144)

    for n in nodes:
        if n["role"] == "drain":
            n["reason"] = "Warm swap, draining"
        elif n["role"] == "down":
            n["reason"] = "Node heartbeat timeout"

    return nodes


class MockCluster:
    def __init__(self, seed: int = 42) -> None:
        self.rng = random.Random(seed)
        self.nodes = _build_nodes()
        self.jobs: list[dict] = []
        self.next_id = 482900
        self.clock = 0.0
        self._last_submit = 0.0
        self._submit_interval = 2.0
        self._last_update = time.monotonic()
        for _ in range(140):
            self._advance(1.0)

    def snapshot(self) -> dict:
        dt = time.monotonic() - self._last_update
        self._last_update = time.monotonic()
        self._advance(dt)
        return {
            "ssh": "mock",
            "nodes": [self._node_dict(n) for n in self.nodes],
            "capacity": [self._capacity_dict(n) for n in self.nodes],
            "jobs": sorted(
                (self._job_dict(j) for j in self.jobs),
                key=lambda j: STATE_ORDER.get(j["state"], 99),
            ),
        }

    def _advance(self, minutes: float) -> None:
        self.clock += minutes

        while self.clock - self._last_submit >= self._submit_interval:
            self._last_submit += self._submit_interval
            self.jobs.append(self._new_job(submitted=self._last_submit))
            self._submit_interval = self.rng.uniform(2.0, 6.0)

        for j in self.jobs:
            if j["state"] == "PENDING" and self.clock - j["submitted"] >= j["wait"]:
                node = self._find_node(j)
                if node:
                    j["state"] = "RUNNING"
                    j["nodes"] = [node]
                    j["start"] = self.clock
                    j["duration"] = self.rng.uniform(20.0, 150.0)
                else:
                    j["wait"] += self.rng.uniform(1.0, 5.0)
            elif j["state"] == "RUNNING" and self.clock - j["start"] >= j["duration"]:
                r = self.rng.random()
                j["state"] = "COMPLETED" if r < 0.94 else "FAILED" if r < 0.97 else "CANCELLED"
                j["end"] = self.clock

        active = [j for j in self.jobs if j["state"] in ("RUNNING", "PENDING")]
        if len(active) > MAX_ACTIVE_JOBS:
            pending = sorted(
                (j for j in active if j["state"] == "PENDING"),
                key=lambda j: j["submitted"],
            )
            for j in pending[: len(active) - MAX_ACTIVE_JOBS]:
                j["state"] = "CANCELLED"
                j["end"] = self.clock

        self.jobs = [
            j
            for j in self.jobs
            if j["state"] not in TERMINAL_STATES
            or self.clock - j.get("end", self.clock) <= TERMINAL_RETENTION_MIN
        ]

    def _new_job(self, submitted: float | None = None) -> dict:
        partition = self.rng.choices(
            list(JOB_NAMES),
            weights=[40, 30, 10, 20],
        )[0]
        name = self.rng.choice(JOB_NAMES[partition])
        user = self.rng.choice(USERS)

        if partition == "gpu":
            cpus = self.rng.choice([8, 16])
            gpus = self.rng.choice([1, 2, 4, 8, 8])
            mem = self.rng.choice([32768, 65536])
        elif partition == "himem":
            cpus = self.rng.choice([16, 32, 64])
            gpus = 0
            mem = 786432
        elif partition == "short":
            cpus = self.rng.choice([1, 2, 4, 8])
            gpus = 0
            mem = self.rng.choice([4096, 8192, 16384])
        else:
            cpus = self.rng.choice([8, 16, 32, 48])
            gpus = 0
            mem = self.rng.choice([8192, 16384, 32768, 65536])

        self.next_id += 1
        return {
            "id": self.next_id,
            "name": name,
            "user": user,
            "partition": partition,
            "cpus": cpus,
            "gpus": gpus,
            "mem_mb": mem,
            "priority": str(4294967290 - self.rng.randint(0, 40)),
            "state": "PENDING",
            "submitted": self.clock if submitted is None else submitted,
            "wait": self.rng.uniform(1.0, 15.0),
            "nodes": [],
            "start": None,
            "duration": None,
        }

    def _node_alloc(self, name: str) -> dict:
        cpu = mem = gpu = 0
        for j in self.jobs:
            if j["state"] == "RUNNING" and name in j["nodes"]:
                cpu += j["cpus"]
                gpu += j["gpus"]
                mem += j["mem_mb"]
        return {"cpu": cpu, "gpu": gpu, "mem": mem}

    def _find_node(self, job: dict) -> str | None:
        pool = [n for n in self.nodes if n["role"] is None and n["partition"] == job["partition"]]
        self.rng.shuffle(pool)
        for n in pool:
            a = self._node_alloc(n["name"])
            if (
                n["total_cpu"] - a["cpu"] >= job["cpus"]
                and n["total_gpu"] - a["gpu"] >= job["gpus"]
                and n["total_mem_mb"] - a["mem"] >= job["mem_mb"]
            ):
                return n["name"]
        return None

    def _node_state(self, n: dict, alloc: dict) -> str:
        if n["role"] == "drain":
            return "drain"
        if n["role"] == "down":
            return "down"
        if alloc["cpu"] == 0 and alloc["gpu"] == 0 and alloc["mem"] == 0:
            return "idle"
        if (
            alloc["cpu"] >= n["total_cpu"]
            or (n["total_gpu"] and alloc["gpu"] >= n["total_gpu"])
            or alloc["mem"] >= n["total_mem_mb"]
        ):
            return "alloc"
        return "mix"

    def _node_dict(self, n: dict) -> dict:
        alloc = self._node_alloc(n["name"])
        return {
            "name": n["name"],
            "partition": n["partition"],
            "state": self._node_state(n, alloc),
            "cpus": n["cpus"],
            "gpus": n["gpus"],
            "memory": n["memory"],
            "reason": n["reason"],
        }

    def _capacity_dict(self, n: dict) -> dict:
        a = self._node_alloc(n["name"])
        return {
            "name": n["name"],
            "cpu_total": n["total_cpu"],
            "cpu_alloc": a["cpu"],
            "cpu_free": n["total_cpu"] - a["cpu"],
            "mem_total_mb": n["total_mem_mb"],
            "mem_alloc_mb": a["mem"],
            "mem_free_mb": n["total_mem_mb"] - a["mem"],
            "gpu_total": n["total_gpu"],
            "gpu_alloc": a["gpu"],
            "gpu_free": n["total_gpu"] - a["gpu"],
        }

    def _job_dict(self, j: dict) -> dict:
        if j["state"] == "RUNNING":
            time_str = _fmt_time(self.clock - j["start"])
            nodes = ",".join(j["nodes"])
            reason = ""
        elif j["state"] == "PENDING":
            time_str = ""
            nodes = ""
            reason = self.rng.choice(PENDING_REASONS)
        else:
            start = j.get("start")
            end = j.get("end", self.clock)
            time_str = _fmt_time((end - start) if start is not None else 0.0)
            nodes = ""
            reason = ""
        return {
            "job_id": str(j["id"]),
            "user": j["user"],
            "name": j["name"],
            "state": j["state"],
            "priority": j["priority"],
            "time": time_str,
            "nodes": nodes,
            "partition": j["partition"],
            "reason": reason,
            "cpus": str(j["cpus"]),
            "memory": _fmt_mem(j["mem_mb"]),
        }


_cluster = MockCluster()
_STATIC_JOBS: list[dict] | None = None


def _static_jobs() -> list[dict]:
    global _STATIC_JOBS
    if _STATIC_JOBS is None:
        _STATIC_JOBS = _cluster.snapshot()["jobs"]
    return _STATIC_JOBS


def mock_enabled() -> bool:
    return os.environ.get("WES_MOCK", "").strip().lower() in ("1", "true", "yes", "on")


def mock_cluster_data() -> dict:
    return _cluster.snapshot()


def mock_nodes() -> list[dict]:
    return mock_cluster_data()["nodes"]


def mock_tasks() -> list[TaskInfo]:
    active = {j["name"]: j for j in _static_jobs()}
    tasks: list[TaskInfo] = []
    for task in MOCK_TASKS:
        job = active.get(task["name"])
        tasks.append(
            TaskInfo(
                **task,
                status=job["state"] if job else "",
                run_id=f"run-{job['job_id']}" if job else "",
            )
        )
    return tasks


def mock_user_jobs() -> list[JobSummary]:
    task_by_name = {t["name"]: t for t in MOCK_TASKS}
    jobs: list[JobSummary] = []
    for j in _static_jobs():
        task = task_by_name.get(j["name"], {})
        jobs.append(
            JobSummary(
                job_id=j["job_id"],
                task_name=j["name"],
                state=j["state"],
                run_id=f"run-{j['job_id']}",
                jobs_ids=[j["job_id"]],
                git_url=task.get("git_url", ""),
                branch=task.get("branch", ""),
                ssh="mock",
                job=task.get("job", ""),
                partition=j["partition"],
                cpus=j["cpus"],
                gpus=task.get("gpus", "0"),
                memory=j["memory"],
                time=j["time"],
                nodelist=task.get("nodelist", ""),
                priority=j["priority"],
            )
        )
    return jobs


def _find_static_job(job_id: str) -> dict | None:
    for j in _static_jobs():
        if j["job_id"] == job_id:
            return j
    return None


def mock_has_job(job_id: str) -> bool:
    return _find_static_job(job_id) is not None


def _mock_task(name: str) -> dict:
    for t in MOCK_TASKS:
        if t["name"] == name:
            return t
    return {}


def _mock_timestamp(job_id: str) -> str:
    h = int(hashlib.md5(job_id.encode()).hexdigest()[:8], 16)
    return f"{h % 24:02d}:{h // 24 % 60:02d}:{h // 1440 % 60:02d}"


def mock_remote_logs(job_id: str) -> dict[str, str] | None:
    job = _find_static_job(job_id)
    if job is None:
        return None
    name = job["name"]
    state = job["state"]
    ts = _mock_timestamp(job_id)
    log = [
        f"[{ts}] SLURM job {job_id} ({name}) state={state}",
        f"[{ts}] partition={job['partition']} cpus={job['cpus']} memory={job['memory']}",
        f"[{ts}] nodes allocated: {job['nodes'] or 'n/a'}",
        f"[{ts}] workspace ready, running job script",
        f"[{ts}] step 1/3: preparing environment ... done",
    ]
    if state == "COMPLETED":
        log += [
            f"[{ts}] step 2/3: training completed after {job['time']}",
            f"[{ts}] step 3/3: syncing artifacts ... done",
            f"[{ts}] job finished successfully",
        ]
    elif state == "FAILED":
        log += [
            f"[{ts}] step 2/3: training aborted",
            f"[{ts}] ERROR: CUDA out of memory on rank 0",
            f"[{ts}] job failed",
        ]
    elif state == "CANCELLED":
        log += [
            f"[{ts}] step 2/3: training aborted",
            f"[{ts}] job cancelled by user",
        ]
    else:
        log += [
            f"[{ts}] epoch 3/10, loss=1.234, lr=3e-5",
            f"[{ts}] epoch 4/10, loss=1.101, lr=2.4e-5",
            f"[{ts}] job still running",
        ]
    return {
        "stdout": "\n".join(log),
        "stderr": ""
        if state in ("RUNNING", "COMPLETED", "PENDING")
        else "Error: training aborted\n",
        "pre_run": f"export WES_TASK={name}\nexport WES_RUN_ID=run-{job_id}\n",
    }


def mock_log_data(job_id: str) -> LogData:
    logs = mock_remote_logs(job_id)
    return LogData(**logs) if logs else LogData()


def mock_artifact_paths(job_id: str) -> list[str]:
    job = _find_static_job(job_id)
    if job is None:
        return []
    rng = random.Random("artifact-" + job_id)
    dirs = _mock_task(job["name"]).get("artifacts") or ["results"]
    paths: list[str] = []
    for d in dirs:
        if d == "checkpoints":
            for ep in range(1, rng.randint(2, 4) + 1):
                paths.append(f"checkpoints/model_epoch_{ep * 5:02d}.zip")
        elif d == "results":
            paths.append("results/metrics.csv")
            paths.append("results/loss_curve.png")
            if rng.random() < 0.7:
                paths.append("results/summary.csv")
        elif d == "shards":
            for i in range(rng.randint(2, 4)):
                paths.append(f"shards/data_{i:05d}.csv")
        elif d == "reports":
            paths.append("reports/test_results.csv")
            if rng.random() < 0.5:
                paths.append("reports/coverage.png")
        elif d == "tokens":
            paths.append("tokens/vocab.csv")
        elif d == "contigs":
            paths.append("contigs/genome.fa")
        elif d == "logs":
            paths.append("logs/train.log")
        else:
            paths.append(f"{d}/output.csv")
    return paths


_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
_EMPTY_ZIP = bytes.fromhex("504b0506000000000000000000000000000000000000")


def mock_artifact_size(path: str, kind: str) -> int:
    rng = random.Random("size-" + path)
    if kind == "model":
        return rng.randint(250, 850) * 1024 * 1024
    if kind == "video":
        return rng.randint(5, 80) * 1024 * 1024
    return rng.randint(60, 600) * 1024


def mock_artifact_content(path: str) -> bytes | None:
    suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if suffix == "png":
        return _TINY_PNG
    if suffix == "zip":
        return _EMPTY_ZIP
    if suffix == "csv":
        return mock_csv_progress(path).encode()
    if suffix in ("log", "fa", "html", "json", "txt"):
        return f"mock artifact: {path}\n".encode()
    return None


def mock_csv_progress(seed: str = "progress") -> str:
    rng = random.Random("progress-" + seed)
    lines = ["time/total_timesteps,eval/reward,train/actor_loss,train/critic_loss"]
    ts = 0
    reward = 100.0
    for i in range(25):
        ts += rng.randint(200, 600)
        reward += rng.uniform(0.2, 1.5)
        actor = max(0.01, 0.8 * (0.92**i) + rng.uniform(0.0, 0.05))
        critic = max(0.05, 1.2 * (0.90**i) + rng.uniform(0.0, 0.1))
        lines.append(f"{ts},{reward:.2f},{actor:.4f},{critic:.4f}")
    return "\n".join(lines)
