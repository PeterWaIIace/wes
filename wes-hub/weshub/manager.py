"""Orchestration layer: drives the wes library from a server process.

Nothing here patches or subclasses wes internals - only its public classes
(``WESParser``, ``Job``, ``JobScanner``, ``JobsQuery``, ``Cluster``) are used,
exactly like the ``wes`` CLI uses them.

One deliberate deviation: ``wes.engine.Engine.start_jobs`` re-runs every job it
has ever registered on each dispatch (fine for a one-shot CLI, wrong for a
long-lived server), so dispatch is orchestrated here over ``WESParser`` +
``Job`` directly.
"""

from __future__ import annotations

import dataclasses
import shlex
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import yaml
from wes.cluster import Cluster
from wes.jobs.job import Job, SshItem
from wes.jobs.scanner import JobScanner
from wes.jobs.status import STATUS_FILENAME, JobStatus, StatusFile
from wes.parser import ConfigError, WESParser
from wes.states import FINISHED_STATES, State
from wes.tasks.tasks import Task

from weshub.config import Settings
from weshub.cron import Cron, CronError
from weshub.discovery import find_status_dirs
from weshub.store import Store


class HubError(Exception):
    """Raised on user-facing hub errors (bad pipeline spec, unknown job...)."""


def _iso(ts: float | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else ""


def run_status(job_states: list[str]) -> str:
    if not job_states:
        return "queued"
    if all(s == State.COMPLETED.value for s in job_states):
        return "success"
    if any(s == State.FAILED.value for s in job_states):
        return "failure"
    if any(s == State.CANCELLED.value for s in job_states):
        return "cancelled"
    if any(s == State.RUNNING.value for s in job_states):
        return "running"
    return "queued"


class DiscoveredJob:
    """A job found via discovery (config on the cluster).

    Mirrors the parts of wes.jobs.job.Job the monitor needs (pull_status,
    artifacts/status files, identity fields) without constructing one:
    wes's Job ignores its ``namespace`` constructor argument and always
    generates a fresh identity, which would sever the link between the
    found config and the real job directory (see TODO.md, wes-upstream).
    """

    def __init__(
        self,
        task: Task,
        ssh_config: str,
        namespace: str,
        job_name: str,
        job_dir: str | None = None,
    ):
        self.task = task
        self.ssh_config = ssh_config
        self.namespace = namespace
        self.job_name = job_name
        # path-based discovery finds job dirs anywhere on the cluster, not
        # just at the default <task>/<namespace> layout
        self.job_dir = job_dir or f"{task.name}/{namespace}"
        git_name = task.git_url.split("/")[-1].replace(".git", "")
        self.repo_dir = f"{self.job_dir}/{git_name}"
        self.status_file = StatusFile(self.job_dir, ssh_config)
        self.status = JobStatus(
            task=task.name, namespace=namespace, job_name=job_name, ssh=ssh_config
        )
        self.artifacts = [
            SshItem(f"results/{self.repo_dir}/{path}", f"{self.repo_dir}/{path}", ssh_config)
            for path in task.artifacts
        ]
        self.status_files = [
            SshItem(f"results/{self.job_dir}/{name}", f"{self.job_dir}/{name}", ssh_config)
            for name in ("job_output.txt", "job_error.txt", STATUS_FILENAME)
        ]

    def pull_status(self) -> bool:
        remote = self.status_file.read()
        if remote is None:
            return False
        self.status = remote
        return True


class JobRecord:
    def __init__(self, job: Job, run_id: int | None, pipeline_id: int | None, discovered: bool):
        self.job = job
        self.run_id = run_id
        self.pipeline_id = pipeline_id
        self.discovered = discovered
        self.pulled = False
        self.last_state = State.PENDING.value


class Hub:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.ensure_dirs()
        self.store = Store(settings.data_dir / "hub.sqlite3")
        self.lock = threading.Lock()
        self.registry: dict[str, JobRecord] = {}
        self.clusters: dict[str, dict] = {}
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._last_discover = 0.0
        self._last_cluster: dict[str, float] = {}

    # ------------------------------------------------------------------ #
    # pipelines                                                          #
    # ------------------------------------------------------------------ #

    def pipeline_dir(self, pid: int) -> Path:
        return self.settings.pipelines_dir / str(pid)

    def _validate(self, wes_yaml: str) -> None:
        try:
            tasks = yaml.safe_load(wes_yaml)
        except yaml.YAMLError as e:
            raise HubError(f"invalid YAML: {e}") from e
        if not isinstance(tasks, dict):
            raise HubError("wes file must be a YAML mapping with a 'sequence' key")
        if "sequence" not in tasks:
            raise HubError("wes file must contain a 'sequence' key")

    def _parse_tasks(self, pid: int) -> list[Task]:
        wes_file = self.pipeline_dir(pid) / "pipeline.wes"
        try:
            tasks = WESParser().parse(wes_file)
        except ConfigError as e:
            raise HubError(str(e)) from e
        base = self.pipeline_dir(pid)
        for t in tasks:
            t.wes_file = str(wes_file)
            # wes resolves script paths against the process CWD; the server
            # runs from the data dir, so make them absolute now.
            for attr in ("job_script", "pre_script"):
                p = getattr(t, attr)
                if p:
                    setattr(t, attr, str((base / p).resolve()))
        return tasks

    def _missing_assets(self, tasks: list[Task]) -> list[str]:
        missing = []
        for t in tasks:
            if t.job_script and not Path(t.job_script).is_file():
                missing.append(f"{t.name}: job script '{t.job_script}'")
            if t.pre_script and not Path(t.pre_script).is_file():
                missing.append(f"{t.name}: pre script '{t.pre_script}'")
        return missing

    def create_pipeline(
        self,
        name: str,
        wes_yaml: str,
        ssh: str = "",
        cron: str = "",
        enabled: bool = True,
        assets: dict[str, str] | None = None,
    ) -> dict:
        self._validate(wes_yaml)
        cron_obj = None
        if cron:
            try:
                cron_obj = Cron(cron)
            except CronError as e:
                raise HubError(str(e)) from e
        pipeline = self.store.add_pipeline(name, wes_yaml, ssh, cron, enabled)
        pid = pipeline["id"]
        pdir = self.pipeline_dir(pid)
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "pipeline.wes").write_text(wes_yaml, encoding="utf-8")
        try:
            self.write_assets(pid, assets or {})
            tasks = self._parse_tasks(pid)
            missing = self._missing_assets(tasks)
        except Exception:
            self.delete_pipeline(pid)
            raise
        if missing:
            self.delete_pipeline(pid)
            raise HubError("missing script assets: " + "; ".join(missing))
        if cron_obj:
            nxt = cron_obj.next_run(datetime.now()).timestamp()
            self.store.update_pipeline(pid, next_run_at=nxt)
        return self.get_pipeline(pid)

    def update_pipeline(self, pid: int, **fields) -> dict:
        pipeline = self.get_pipeline(pid)
        if not pipeline:
            raise HubError(f"pipeline {pid} not found")
        if "wes_yaml" in fields and fields["wes_yaml"]:
            self._validate(fields["wes_yaml"])
        if "cron" in fields and fields["cron"]:
            try:
                Cron(fields["cron"])
            except CronError as e:
                raise HubError(str(e)) from e
        self.store.update_pipeline(pid, **fields)
        if "wes_yaml" in fields and fields["wes_yaml"]:
            wes_path = self.pipeline_dir(pid) / "pipeline.wes"
            wes_path.write_text(fields["wes_yaml"], encoding="utf-8")
        if "cron" in fields:
            self.reschedule(pid)
        return self.get_pipeline(pid)

    def reschedule(self, pid: int) -> dict:
        pipeline = self.get_pipeline(pid)
        if not pipeline:
            raise HubError(f"pipeline {pid} not found")
        if pipeline["cron"] and pipeline["enabled"]:
            nxt = Cron(pipeline["cron"]).next_run(datetime.now()).timestamp()
        else:
            nxt = None
        self.store.update_pipeline(pid, next_run_at=nxt)
        return self.get_pipeline(pid)

    def delete_pipeline(self, pid: int) -> None:
        self.store.delete_pipeline(pid)
        pdir = self.pipeline_dir(pid)
        if pdir.exists():
            for f in pdir.rglob("*"):
                if f.is_file():
                    f.unlink()
            pdir.rmdir()

    def get_pipeline(self, pid: int) -> dict:
        pipeline = self.store.get_pipeline(pid)
        if not pipeline:
            raise HubError(f"pipeline {pid} not found")
        runs = self.store.list_runs(pid, limit=1)
        pipeline["next_run_at_iso"] = _iso(pipeline.get("next_run_at"))
        pipeline["last_run"] = runs[0] if runs else None
        return pipeline

    def list_pipelines(self) -> list[dict]:
        return [self.get_pipeline(p["id"]) for p in self.store.list_pipelines()]

    def write_assets(self, pid: int, assets: dict[str, str]) -> None:
        base = self.pipeline_dir(pid)
        for rel, content in (assets or {}).items():
            target = (base / rel).resolve()
            if not str(target).startswith(str(base.resolve())):
                raise HubError(f"asset escapes pipeline dir: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            # scripts must be executable on the cluster (scp preserves mode)
            if target.suffix in (".sh", "") or target.name.startswith("pre"):
                target.chmod(0o755)

    def list_assets(self, pid: int) -> list[str]:
        base = self.pipeline_dir(pid)
        if not base.exists():
            return []
        return sorted(str(p.relative_to(base)) for p in base.rglob("*") if p.is_file())

    # ------------------------------------------------------------------ #
    # dispatch                                                           #
    # ------------------------------------------------------------------ #

    def trigger_run(self, pid: int, trigger: str = "manual") -> dict:
        pipeline = self.get_pipeline(pid)
        tasks = self._parse_tasks(pid)
        run = self.store.add_run(pid, trigger)
        threading.Thread(
            target=self._dispatch, args=(pipeline, tasks, run["id"]), daemon=True
        ).start()
        return run

    def _dispatch(self, pipeline: dict, tasks: list[Task], run_id: int) -> None:
        for task in tasks:
            try:
                job = Job(task, task.ssh_config)
            except Exception as e:  # noqa: BLE001
                print(f"[hub] job construction failed for {task.name}: {e}")
                continue
            with self.lock:
                self.registry[job.namespace] = JobRecord(job, run_id, pipeline["id"], False)
            self.store.upsert_job(
                job.namespace,
                run_id=run_id,
                pipeline_id=pipeline["id"],
                task=task.name,
                job_name=job.job_name,
                ssh=task.ssh_config,
                state=State.PENDING.value,
            )
            threading.Thread(target=self._dispatch_one, args=(job.namespace,), daemon=True).start()

    def _dispatch_one(self, namespace: str) -> None:
        with self.lock:
            rec = self.registry.get(namespace)
        if not rec:
            return
        job = rec.job
        print(f"[hub] dispatching {job.job_name}")
        job.upload_scripts()
        state = job.execute_job()
        job_id = job.task.jobs_ids[-1] if job.task.jobs_ids else ""
        self.store.set_job_state(
            namespace,
            str(getattr(state, "value", state)),
            job_id=job_id,
        )

    # ------------------------------------------------------------------ #
    # monitoring / discovery / results                                   #
    # ------------------------------------------------------------------ #

    def _ssh_configs(self) -> set[str]:
        configs = {j["ssh"] for j in self.store.list_jobs() if j["ssh"]}
        for p in self.store.list_pipelines():
            if p["ssh"]:
                configs.add(p["ssh"])
        return configs

    def _register(self, job: Job, rec: JobRecord) -> None:
        with self.lock:
            self.registry[job.namespace] = rec
        self.store.upsert_job(
            job.namespace,
            run_id=rec.run_id,
            pipeline_id=rec.pipeline_id,
            task=job.task.name,
            job_name=job.job_name,
            ssh=job.ssh_config,
            discovered=int(rec.discovered),
        )

    def discover(self, ssh: str, path: str | None = None) -> list[str]:
        """Job discovery: adopt jobs found on the cluster.

        With ``path``, recursively search that remote dir for ``wes.status``
        files - only non-hidden entries are entered, and a dir containing a
        status file is adopted and not descended into. Without ``path``,
        fall back to the ``*_config.json`` scan under the remote workdir.
        """
        if path:
            return self._bounded(self._discover_path, ssh, path) or []
        return self._bounded(self._discover, ssh) or []

    def _discover_path(self, ssh: str, path: str) -> list[str]:
        """Status-file discovery: adopt jobs whose dir under `path` holds wes.status."""
        scanner = JobScanner(ssh)
        try:
            job_dirs = find_status_dirs(scanner.runner, path)
        except Exception as e:  # noqa: BLE001
            print(f"[hub] status discovery on {ssh}:{path} failed: {e}")
            return []
        known = set(self.registry)
        adopted = []
        for job_dir in job_dirs:
            try:
                status = StatusFile(job_dir, ssh).read()
                if not status or not status.namespace or status.namespace in known:
                    continue
                task = self._task_for_dir(scanner, job_dir, status, ssh)
                job = DiscoveredJob(
                    task,
                    status.ssh or ssh,
                    status.namespace,
                    status.job_name or status.namespace,
                    job_dir=job_dir,
                )
                job.status = status
            except Exception as e:  # noqa: BLE001
                print(f"[hub] skipping broken status dir {job_dir}: {e}")
                continue
            known.add(status.namespace)
            existing = self.store.get_job(status.namespace)
            rec = JobRecord(
                job,
                existing["run_id"] if existing else None,
                existing["pipeline_id"] if existing else None,
                discovered=True,
            )
            self._register(job, rec)
            # the status was just read over ssh - store it without re-reading
            self._store_status(rec, status)
            adopted.append(status.namespace)
        return adopted

    def _task_for_dir(self, scanner: JobScanner, job_dir: str, status: JobStatus, ssh: str) -> Task:
        """Full task spec if the job dir carries a *_config.json, else a minimal one."""
        ok, lines = scanner.runner.run_command(
            f"find {shlex.quote(job_dir)} -maxdepth 1 -name '*_config.json'"
        )
        if ok and lines:
            config = scanner._read_config(lines[0])
            if config:
                task = scanner._config_to_task(config)
                if not task.ssh_config:
                    task.ssh_config = ssh
                return task
        name = status.task or job_dir.rstrip("/").split("/")[-1]
        return Task(name=name, git_url="", ssh_config=ssh)

    def _discover(self, ssh: str) -> list[str]:
        """Job discovery: adopt jobs from *_config.json on the cluster."""
        scanner = JobScanner(ssh)
        known = set(self.registry)
        adopted = []
        try:
            config_paths = scanner._find_config()
        except Exception as e:  # noqa: BLE001
            print(f"[hub] discovery on {ssh} failed: {e}")
            return []
        for path in config_paths:
            try:
                config = scanner._read_config(path)
                if not config:
                    continue
                job_info = config.get("job", {})
                ns = job_info.get("namespace", "")
                if not ns or ns in known:
                    continue
                task = scanner._config_to_task(config)
                job = DiscoveredJob(
                    task,
                    job_info.get("ssh_config", ssh),
                    ns,
                    job_info.get("job_name", ""),
                )
            except Exception as e:  # noqa: BLE001
                print(f"[hub] skipping broken config {path}: {e}")
                continue
            known.add(ns)
            existing = self.store.get_job(ns)
            rec = JobRecord(
                job,
                existing["run_id"] if existing else None,
                existing["pipeline_id"] if existing else None,
                discovered=True,
            )
            self._register(job, rec)
            adopted.append(ns)
        return adopted

    def _bounded(self, fn, *args, timeout: float | None = None):
        """Run an ssh-backed call in a worker; give up after `timeout`.

        The wes SshRunner has no internal timeout, so an unreachable or
        hung cluster could otherwise stall the monitor loop.
        """
        timeout = timeout or self.settings.ssh_timeout
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(fn, *args)
            try:
                return future.result(timeout=timeout)
            except TimeoutError:
                print(f"[hub] timeout after {timeout}s: {getattr(fn, '__name__', fn)}")
                return None

    def _pull_results(self, rec: JobRecord) -> None:
        job = rec.job
        print(f"[hub] pulling results for {job.job_name}")
        try:
            for item in job.artifacts + job.status_files:
                item.sync()
        except Exception as e:  # noqa: BLE001
            print(f"[hub] pull failed for {job.job_name}: {e}")
            return
        rec.pulled = True
        self.store.set_job_state(job.namespace, rec.last_state, artifacts_pulled=1)

    def pull_job(self, namespace: str) -> dict:
        rec = self.registry.get(namespace)
        if not rec:
            raise HubError(f"job {namespace} not found")
        self._bounded(self._pull_results, rec)
        if not rec.pulled:
            raise HubError(f"pull timed out for {namespace}")
        return self.store.get_job(namespace)

    def _store_status(self, rec: JobRecord, st) -> None:
        value = st.state.value if hasattr(st.state, "value") else str(st.state)
        rec.last_state = value
        self.store.set_job_state(
            rec.job.namespace,
            value,
            job_id=st.job_id,
            node=st.node,
            partition=st.partition,
            message=st.message,
            updated=st.updated or "",
        )

    def _sync_job_status(self, rec: JobRecord) -> None:
        job = rec.job
        try:
            job.pull_status()
        except Exception as e:  # noqa: BLE001
            print(f"[hub] status pull failed for {job.job_name}: {e}")
            return
        st = job.status
        if not st or not st.state:
            return
        self._store_status(rec, st)

    def _refresh_cluster(self, ssh: str, max_age: float = 30.0) -> None:
        import time as _time

        if _time.time() - self._last_cluster.get(ssh, 0) < max_age:
            return
        self._last_cluster[ssh] = _time.time()
        self._bounded(self._cluster_snapshot, ssh)

    def _cluster_snapshot(self, ssh: str) -> None:
        import time as _time

        try:
            cluster = Cluster(ssh)
            nodes = [
                {**dataclasses.asdict(n.info), **asdict_flat(n.capacity)}
                for n in cluster.get_nodes()
            ]
            jobs = [dataclasses.asdict(j) for j in cluster.get_jobs()]
            self.clusters[ssh] = {
                "ssh": ssh,
                "updated": _iso(_time.time()),
                "nodes": nodes,
                "jobs": jobs,
            }
        except Exception as e:  # noqa: BLE001
            print(f"[hub] cluster refresh on {ssh} failed: {e}")

    def _recompute_runs(self) -> None:
        import time as _time

        for run_id in self.store.active_run_states():
            jobs = self.store.list_jobs(run_id)
            status = run_status([j["state"] for j in jobs])
            if status != "running" and status != "queued":
                self.store.update_run(run_id, status, finished_at=_time.time())
            elif status != "queued":
                self.store.update_run(run_id, status)

    def monitor_tick(self) -> None:
        import time as _time

        with self.lock:
            records = list(self.registry.values())
        with ThreadPoolExecutor(max_workers=self.settings.max_status_workers) as pool:
            try:
                list(pool.map(self._sync_job_status, records, timeout=self.settings.ssh_timeout))
            except TimeoutError:
                print("[hub] timeout polling job statuses (slow cluster?)")
        # pull artifacts for newly finished jobs
        for rec in records:
            if rec.last_state in {s.value for s in FINISHED_STATES} and not rec.pulled:
                self._bounded(self._pull_results, rec)
        if _time.time() - self._last_discover > self.settings.discover_interval:
            self._last_discover = _time.time()
            for ssh in self._ssh_configs():
                self.discover(ssh)
                # also refresh status of discovered jobs registered before
                self._refresh_cluster(ssh, max_age=self.settings.discover_interval)
        self._recompute_runs()

    def scheduler_tick(self) -> None:
        import time as _time

        now = _time.time()
        for pipeline in self.store.list_pipelines():
            if not pipeline["enabled"] or not pipeline["cron"]:
                continue
            nxt = pipeline["next_run_at"]
            if nxt is None:
                self.reschedule(pipeline["id"])
                continue
            if now >= nxt:
                print(f"[hub] cron dispatching pipeline {pipeline['name']}")
                self.trigger_run(pipeline["id"], trigger="cron")
                self.reschedule(pipeline["id"])

    # ------------------------------------------------------------------ #
    # lifecycle                                                          #
    # ------------------------------------------------------------------ #

    def _loop(self, fn, interval: float) -> None:
        fn()
        while not self._stop.wait(interval):
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                print(f"[hub] loop error in {fn.__name__}: {e}")

    def start(self) -> None:
        self._stop.clear()
        t1 = threading.Thread(
            target=self._loop, args=(self.monitor_tick, self.settings.poll_interval), daemon=True
        )
        t2 = threading.Thread(
            target=self._loop,
            args=(self.scheduler_tick, self.settings.scheduler_interval),
            daemon=True,
        )
        t1.start()
        t2.start()
        self._threads = [t1, t2]

    def stop(self) -> None:
        self._stop.set()
        self.store.close()

    # ------------------------------------------------------------------ #
    # snapshots                                                          #
    # ------------------------------------------------------------------ #

    def state(self) -> dict:
        pipelines = []
        for p in self.list_pipelines():
            pipelines.append(p)
        runs = self.store.list_runs(limit=50)
        for r in runs:
            r["jobs"] = self.store.list_jobs(r["id"])
            r["created_at_iso"] = _iso(r["created_at"])
            r["finished_at_iso"] = _iso(r["finished_at"])
        jobs = self.store.list_jobs()
        return {
            "pipelines": pipelines,
            "runs": runs,
            "jobs": jobs,
            "clusters": list(self.clusters.values()),
            "poll_interval_ms": int(max(self.settings.poll_interval, 2) * 1000),
        }


def asdict_flat(cap) -> dict:
    d = dataclasses.asdict(cap)
    return {f"cap_{k}": v for k, v in d.items()}
