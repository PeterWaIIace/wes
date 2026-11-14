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
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import yaml
from wes.cluster import Cluster
from wes.jobs.job import Job, SshItem
from wes.jobs.query import JobsQuery
from wes.jobs.scanner import JobScanner
from wes.jobs.status import STATUS_FILENAME, JobStatus, StatusFile, slurm_state
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
        return ""
    if all(s == State.COMPLETED.value for s in job_states):
        return State.COMPLETED.value
    if any(s == State.FAILED.value for s in job_states):
        return State.FAILED.value
    if any(s == State.CANCELLED.value for s in job_states):
        return State.CANCELLED.value
    if any(s == State.RUNNING.value for s in job_states):
        return State.RUNNING.value
    if any(s == State.PENDING.value for s in job_states):
        return State.PENDING.value
    return ""


def independent_task_status(status: JobStatus) -> JobStatus:
    """Give legacy array status files a stable identity per array index."""
    if not status.array_index:
        return status
    parent = status.parent_namespace or status.namespace
    namespace = f"{parent}_array_{status.array_index}"
    if status.namespace != namespace:
        status.job_name = f"{status.job_name}_array_{status.array_index}"
    status.parent_namespace = parent
    status.namespace = namespace
    return status


def parent_job_dir(status_dir: str) -> str:
    """Map an array-task status dir back to the job dir that owns it.

    ``<job>/tasks/<index>`` and the legacy ``<job>/array-status/<id>/<index>``
    both belong to ``<job>``. Any other path is returned unchanged.
    """
    parts = status_dir.rstrip("/").split("/")
    if len(parts) >= 3 and parts[-2] == "tasks" and parts[-1].isdigit():
        return "/".join(parts[:-2]) or "/"
    if (
        len(parts) >= 4
        and parts[-3] == "array-status"
        and parts[-2].isdigit()
        and parts[-1].isdigit()
    ):
        return "/".join(parts[:-3]) or "/"
    return status_dir


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
        if parent_job_dir(self.job_dir) != self.job_dir:
            self.repo_dir = self.job_dir
        self.status_file = StatusFile(self.job_dir, ssh_config)
        self.status = JobStatus(
            task=task.name, namespace=namespace, job_name=job_name, ssh=ssh_config
        )
        self.artifacts = [
            SshItem(f"results/{self.repo_dir}/{path}", f"{self.repo_dir}/{path}", ssh_config)
            for path in task.artifacts
        ]
        self.progress_artifacts = [
            SshItem(f"results/{self.repo_dir}/{path}", f"{self.repo_dir}/{path}", ssh_config)
            for path in task.progress_artifacts
        ]
        self.status_files = [
            SshItem(f"results/{self.job_dir}/{name}", f"{self.job_dir}/{name}", ssh_config)
            for name in (STATUS_FILENAME,)
        ]

    def pull_status(self) -> bool:
        remote = self.status_file.read()
        if remote is None:
            return False
        self.status = independent_task_status(remote)
        return True

    def sync_progress(self) -> None:
        for item in self.progress_artifacts:
            item.sync()


class JobRecord:
    def __init__(self, job: Job, run_id: int | None, pipeline_id: int | None, discovered: bool):
        self.job = job
        self.run_id = run_id
        self.pipeline_id = pipeline_id
        self.discovered = discovered
        self.pulled = False
        self.last_state = ""
        self.last_progress_pull = 0.0
        self.status_seen = False
        # jobs in the process of creation live only in the runtime registry;
        # the store row is written once a server-side wes.status exists
        self.persisted = discovered


class Hub:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.ensure_dirs()
        self.store = Store()
        self.lock = threading.Lock()
        self.registry: dict[str, JobRecord] = {}
        self.clusters: dict[str, dict] = {}
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._last_discover = 0.0
        self._last_cluster: dict[str, float] = {}
        self.cluster_configs: dict[str, str] = {}

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
            if self.cluster_configs:
                ssh = self.cluster_configs.get(t.ssh_config)
                if not ssh:
                    raise HubError(f"task '{t.name}' uses unconfigured cluster '{t.ssh_config}'")
                t.ssh_config = ssh
        return tasks

    def _sync_catalog_repo(self) -> None:
        if not self.settings.catalog_repo:
            return
        catalog_dir = self.settings.catalog_dir
        if catalog_dir.exists():
            command = [
                "git",
                "-C",
                str(catalog_dir),
                "fetch",
                "origin",
                self.settings.catalog_branch,
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(catalog_dir),
                    "reset",
                    "--hard",
                    f"origin/{self.settings.catalog_branch}",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            return
        subprocess.run(
            [
                "git",
                "clone",
                "--branch",
                self.settings.catalog_branch,
                "--single-branch",
                self.settings.catalog_repo,
                str(catalog_dir),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def sync_catalog(self) -> list[dict]:
        """Pull the workflow catalog and import its manifest into hub pipelines."""
        if not self.settings.catalog_repo:
            return []
        try:
            self._sync_catalog_repo()
            manifest_path = self.settings.catalog_dir / ".weshub.yaml"
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        except (OSError, subprocess.CalledProcessError, yaml.YAMLError) as e:
            raise HubError(f"catalog sync failed: {e}") from e
        if not isinstance(manifest, dict):
            raise HubError("catalog manifest must be a YAML mapping")

        clusters = manifest.get("clusters", {})
        if not isinstance(clusters, dict):
            raise HubError("catalog 'clusters' must be a mapping")
        self.cluster_configs = {}
        for name, spec in clusters.items():
            ssh = spec.get("ssh", name) if isinstance(spec, dict) else str(spec)
            if not isinstance(name, str) or not ssh:
                raise HubError("each catalog cluster needs a name and ssh config")
            self.cluster_configs[name] = ssh

        workflows = manifest.get("workflows", [])
        if not isinstance(workflows, list):
            raise HubError("catalog 'workflows' must be a list")
        imported = []
        for workflow in workflows:
            if not isinstance(workflow, dict):
                raise HubError("each workflow must be a mapping")
            name = workflow.get("name")
            directory = workflow.get("path")
            cluster = workflow.get("cluster", "")
            if not isinstance(name, str) or not isinstance(directory, str):
                raise HubError("each workflow needs string 'name' and 'path'")
            if cluster and cluster not in self.cluster_configs:
                raise HubError(f"workflow '{name}' uses unknown cluster '{cluster}'")
            source_dir = (self.settings.catalog_dir / directory).resolve()
            if not str(source_dir).startswith(str(self.settings.catalog_dir.resolve())):
                raise HubError(f"workflow '{name}' path escapes catalog")
            wes_file = source_dir / workflow.get("file", "pipeline.wes")
            if not wes_file.is_file():
                relative_file = wes_file.relative_to(self.settings.catalog_dir)
                raise HubError(f"workflow '{name}' file not found: {relative_file}")
            wes_yaml = wes_file.read_text(encoding="utf-8")
            assets = {
                str(path.relative_to(source_dir)): path.read_text(encoding="utf-8")
                for path in source_dir.rglob("*")
                if path.is_file() and path != wes_file and ".git" not in path.parts
            }
            existing = self.store.get_pipeline_by_name(name)
            if existing:
                self.update_pipeline(existing["id"], wes_yaml=wes_yaml, ssh=cluster)
                self.write_assets(existing["id"], assets)
                pipeline = self.get_pipeline(existing["id"])
            else:
                pipeline = self.create_pipeline(name, wes_yaml, cluster, assets=assets)
            imported.append(pipeline)
        return imported

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
            shutil.rmtree(pdir)

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
                self.store.upsert_job(
                    namespace=f"dispatch-error-{run_id}-{task.name}",
                    run_id=run_id,
                    pipeline_id=pipeline["id"],
                    task=task.name,
                    job_name=task.name,
                    ssh=task.ssh_config,
                    state=State.FAILED.value,
                    message=f"job construction failed: {e}",
                )
                continue
            with self.lock:
                # in-creation job: runtime registry only until a server-side
                # wes.status exists (see _persist)
                self.registry[job.namespace] = JobRecord(job, run_id, pipeline["id"], False)
            threading.Thread(target=self._dispatch_one, args=(job.namespace,), daemon=True).start()

    def _dispatch_one(self, namespace: str) -> None:
        with self.lock:
            rec = self.registry.get(namespace)
        if not rec:
            return
        job = rec.job
        print(f"[hub] dispatching {job.job_name}")
        try:
            job.upload_scripts()
            state = job.execute_job()
            job_id = job.task.jobs_ids[-1] if job.task.jobs_ids else ""
            if job.pull_status():
                self._store_status(rec, job.status)
            elif state is State.PENDING and job_id:
                # sbatch accepted the job, but it has not started yet and no
                # server-side wes.status has been written by the job script.
                self._persist(rec)
                self.store.set_job_state(namespace, State.PENDING.value, job_id=job_id)
            else:
                self._persist(rec)
                self.store.set_job_state(
                    namespace,
                    State.FAILED.value,
                    job_id=job_id,
                    message="dispatch failed before wes.status was available",
                )
        except Exception as e:  # noqa: BLE001
            print(f"[hub] dispatch failed for {job.job_name}: {e}")
            self._persist(rec)
            self.store.set_job_state(
                namespace,
                State.FAILED.value,
                message=f"dispatch failed: {e}",
            )
        self._recompute_runs()

    # ------------------------------------------------------------------ #
    # monitoring / discovery / results                                   #
    # ------------------------------------------------------------------ #

    def _ssh_configs(self) -> set[str]:
        if self.cluster_configs:
            return set(self.cluster_configs.values())

        configs = set()
        configs.update(j["ssh"] for j in self.store.list_jobs() if j["ssh"])
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
        rec.persisted = True

    def _persist(self, rec: JobRecord) -> None:
        """Write the store row for a job once it is status-backed on the server
        (or reached a terminal dispatch outcome). Until then the job is only
        tracked in the runtime registry."""
        if rec.persisted:
            return
        rec.persisted = True
        self.store.upsert_job(
            rec.job.namespace,
            run_id=rec.run_id,
            pipeline_id=rec.pipeline_id,
            task=rec.job.task.name,
            job_name=rec.job.job_name,
            ssh=rec.job.ssh_config,
            discovered=int(rec.discovered),
        )

    def discover(self, ssh: str, path: str | None = None) -> list[str]:
        """Job discovery: adopt jobs that have a ``wes.status`` on the cluster.

        Only status-backed jobs are adopted; a dir containing a status file is
        not descended into. Jobs merely in the process of creation (config
        uploaded, no status yet) are tracked at dispatch time in the runtime
        registry only and are never persisted from a config-only scan.

        On a full scan (no ``path``), cached jobs with no ``wes.status`` on the
        server are pruned from the store and the UI, unless they are in
        creation in the runtime registry or still live in Slurm.
        """
        full = path in (None, ".")
        result = self._bounded(self._discover_path, ssh, path or ".")
        adopted, seen = result if result else ([], None)
        # prune only when discovery actually succeeded - a failed ssh scan
        # must never wipe cached jobs
        if full and seen is not None:
            self._bounded(self._prune_unseen, ssh, seen)
            self._bounded(self._prune_jobless_runs)
        return adopted

    def _prune_jobless_runs(self, grace: float = 300.0) -> None:
        """Delete runs that have no jobs left - neither on the server nor in
        creation in the runtime registry. Fresh unfinished runs get a grace
        period so a dispatch thread that has not registered its job yet is
        not wiped."""
        import time as _time

        now = _time.time()
        for run in self.store.list_runs(limit=100000):
            if self.list_jobs(run["id"]):
                continue
            if not run["finished_at"] and now - run["created_at"] < grace:
                continue
            print(f"[hub] pruned run #{run['id']}: no jobs left on the server")
            self.store.delete_run(run["id"])

    def _prune_unseen(self, ssh: str, seen: set[str]) -> None:
        """Drop cached jobs that no longer have a wes.status on the server."""
        with self.lock:
            records = dict(self.registry)
        try:
            live_jobs = Cluster(ssh).get_jobs()
        except Exception as e:  # noqa: BLE001
            print(f"[hub] cannot verify cached jobs against Slurm ({e}); skipping prune")
            return
        for row in self.store.list_jobs():
            ns = row["namespace"]
            if row["ssh"] != ssh or ns in seen or ns in records:
                continue
            if self._slurm_live(ssh, row["job_name"], {row.get("job_id") or ""}, live_jobs):
                continue
            print(f"[hub] pruned cached job {ns}: no wes.status on {ssh} anymore")
            self.store.delete_job(ns)
        # runtime entries whose status is gone from the server too. Same rule
        # as for discovered jobs: anything persisted (status-backed) must still
        # be discoverable on the server or live in Slurm; only unpersisted
        # in-creation jobs are exempt, and those are runtime-only anyway
        for ns, rec in records.items():
            if ns in seen or rec.job.ssh_config != ssh:
                continue
            if not rec.persisted:
                continue
            job = rec.job
            known = set(getattr(job.task, "jobs_ids", []))
            stored = self.store.get_job(ns) or {}
            if stored.get("job_id"):
                known.add(stored["job_id"])
            if self._slurm_live(ssh, job.job_name, known, live_jobs):
                continue
            self._forget_missing_status(rec)

    def _discover_path(self, ssh: str, path: str) -> tuple[list[str], set[str] | None]:
        """Status-file discovery: adopt jobs whose dir under `path` holds wes.status.

        Returns the adopted namespaces and every namespace seen on the server,
        or ``None`` for the seen-set when the scan itself failed.
        """
        scanner = JobScanner(ssh)
        try:
            job_dirs = find_status_dirs(scanner.runner, path)
        except Exception as e:  # noqa: BLE001
            print(f"[hub] status discovery on {ssh}:{path} failed: {e}")
            return [], None
        known = set(self.registry)
        adopted = []
        seen = set()
        for raw_dir in job_dirs:
            try:
                status = StatusFile(raw_dir, ssh).read()
                if not status or not status.namespace:
                    continue
                status = independent_task_status(status)
                job_dir = raw_dir
                seen.add(status.namespace)
                if status.namespace in known:
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
                print(f"[hub] skipping broken status dir {raw_dir}: {e}")
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
        return adopted, seen

    def _task_for_dir(self, scanner: JobScanner, job_dir: str, status: JobStatus, ssh: str) -> Task:
        """Full task spec if the job dir carries a *_config.json, else a minimal one."""
        config_dir = parent_job_dir(job_dir) if status.array_index else job_dir
        ok, lines = scanner.runner.run_command(
            f"find {shlex.quote(config_dir)} -maxdepth 1 -name '*_config.json'"
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

    def list_jobs(self, run_id: int | None = None) -> list[dict]:
        """Jobs to show: persisted (status-backed on the server) rows plus
        in-creation jobs still held only in the runtime registry."""
        jobs = [dict(j) for j in self.store.list_jobs(run_id)]
        seen = {j["namespace"] for j in jobs}
        with self.lock:
            records = list(self.registry.values())
        for rec in records:
            if rec.persisted:
                continue
            if rec.job.namespace in seen:
                continue
            if run_id is not None and rec.run_id != run_id:
                continue
            job = rec.job
            jobs.append(
                {
                    "namespace": job.namespace,
                    "task": job.task.name,
                    "job_name": job.job_name,
                    "ssh": job.ssh_config,
                    "state": rec.last_state,
                    "discovered": 0,
                    "run_id": rec.run_id,
                    "pipeline_id": rec.pipeline_id,
                    "job_id": getattr(job.status, "job_id", ""),
                    "in_creation": 1,
                }
            )
        return jobs

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

    def _pull_progress(self, rec: JobRecord) -> None:
        if not rec.job.progress_artifacts:
            return
        try:
            rec.job.sync_progress()
            rec.last_progress_pull = time.time()
        except Exception as e:  # noqa: BLE001
            print(f"[hub] progress pull failed for {rec.job.job_name}: {e}")

    def pull_job(self, namespace: str) -> dict:
        rec = self.registry.get(namespace)
        if not rec:
            raise HubError(f"job {namespace} not found")
        self._bounded(self._pull_results, rec)
        if not rec.pulled:
            raise HubError(f"pull timed out for {namespace}")
        return self.store.get_job(namespace)

    def result_tree(self, namespace: str) -> list[dict]:
        """List the locally pulled result files for one job."""
        job = self.store.get_job(namespace)
        if not job:
            raise HubError(f"job {namespace} not found")
        rec = self.registry.get(namespace)
        job_dir = rec.job.job_dir if rec else f"{job['task']}/{namespace}"
        results_root = self.settings.results_dir.resolve()
        root = (results_root / job_dir).resolve()
        try:
            root.relative_to(results_root)
        except ValueError as e:
            raise HubError(f"invalid results path for job {namespace}") from e
        if not root.is_dir():
            return []

        def entries(path: Path) -> list[dict]:
            children = sorted(
                path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())
            )
            return [
                {
                    "name": child.name,
                    "path": child.relative_to(results_root).as_posix(),
                    "directory": child.is_dir(),
                    "children": entries(child) if child.is_dir() else [],
                }
                for child in children
            ]

        return entries(root)

    def _task_for_job(self, job: dict) -> Task | None:
        with self.lock:
            rec = self.registry.get(job["namespace"])
            if rec:
                return rec.job.task
        if not job.get("pipeline_id"):
            return None
        try:
            return next(
                (
                    task
                    for task in self._parse_tasks(job["pipeline_id"])
                    if task.name == job["task"]
                ),
                None,
            )
        except (ConfigError, HubError):
            return None

    def job_execution(self, job: dict) -> dict:
        """Derive WES phases from task configuration and server-owned status."""
        task = self._task_for_job(job)
        steps = [{"name": "Clone repository", "state": "next"}]
        if task and task.pre_script:
            steps.append({"name": "Run pre-script", "state": "next"})
        steps.extend(
            [
                {"name": "Submit to Slurm", "state": "next"},
                {"name": "Run job script", "state": "next"},
            ]
        )
        state = job.get("state", "")
        message = job.get("message", "").lower()
        job_index = len(steps) - 1
        pre_index = 1 if len(steps) == 4 else None
        submit_index = job_index - 1

        def complete_before(index: int) -> None:
            for step in steps[:index]:
                step["state"] = "completed"

        if not state:
            steps[0]["state"] = "current"
        elif state in (State.FAILED.value, State.CANCELLED.value):
            failed_index = job_index
            if "clone" in message:
                failed_index = 0
            elif "pre-script" in message and pre_index is not None:
                failed_index = pre_index
            elif "sbatch" in message or "submission" in message:
                failed_index = submit_index
            complete_before(failed_index)
            steps[failed_index]["state"] = "failed"
        elif message == "pre-script" and pre_index is not None:
            complete_before(pre_index)
            steps[pre_index]["state"] = "current"
        elif state == State.PENDING.value:
            complete_before(job_index)
        elif state == State.RUNNING.value:
            complete_before(job_index)
            steps[job_index]["state"] = "current"
        elif state == State.COMPLETED.value:
            for step in steps:
                step["state"] = "completed"

        active = next((step["name"] for step in steps if step["state"] == "current"), "")
        if state == State.PENDING.value and job.get("job_id"):
            active = "Waiting for Slurm allocation"
        return {"active": active, "steps": steps}

    def enrich_job(self, job: dict) -> dict:
        task = self._task_for_job(job)
        with self.lock:
            rec = self.registry.get(job["namespace"])
        job_dir = getattr(rec.job, "repo_dir", "") if rec else ""
        if not job_dir and task:
            git_name = task.git_url.rsplit("/", 1)[-1].removesuffix(".git")
            job_dir = f"{job['task']}/{job['namespace']}/{git_name}"
        results_root = self.settings.results_dir.resolve()
        progress = []
        seen_paths = set()
        for path in task.progress_artifacts if task else []:
            for local_path in sorted((results_root / job_dir).glob(path)):
                try:
                    relative_path = local_path.resolve().relative_to(results_root).as_posix()
                except ValueError:
                    continue
                if not local_path.is_file() or relative_path in seen_paths:
                    continue
                seen_paths.add(relative_path)
                progress.append(
                    {
                        "path": relative_path,
                        "thumbnail": local_path.suffix.lower()
                        in {".gif", ".jpeg", ".jpg", ".png", ".webp"},
                    }
                )
        return {
            **job,
            "execution": self.job_execution(job),
            "progress_artifacts": progress,
        }

    def _store_status(self, rec: JobRecord, st) -> None:
        self._persist(rec)
        value = st.state.value if hasattr(st.state, "value") else str(st.state)
        rec.last_state = value
        rec.status_seen = True
        self.store.set_job_state(
            rec.job.namespace,
            value,
            job_id=st.job_id,
            node=st.node,
            partition=st.partition,
            message=st.message,
            updated=st.updated or "",
        )

    def _array_statuses(self, rec: JobRecord) -> list[JobStatus]:
        """Read WES statuses written by individual Slurm array tasks.

        Current jobs write ``tasks/<index>/wes.status``. ``array-status/`` is
        still scanned so jobs dispatched before the per-task-dir switch keep
        reporting until they finish.
        """
        job = rec.job
        roots = (f"{job.job_dir}/tasks", f"{job.job_dir}/array-status")
        parts = []
        for root in roots:
            quoted = shlex.quote(root)
            parts.append(
                f"if [ -d {quoted} ]; then "
                f"find {quoted} -type f -name {shlex.quote(STATUS_FILENAME)}; fi"
            )
        ok, paths = job.status_file.runner.run_command("; ".join(parts))
        if not ok:
            return []
        statuses = []
        for path in paths:
            status = StatusFile(str(Path(path).parent), job.ssh_config).read()
            if status and status.array_index:
                statuses.append(status)
        return statuses

    def _array_slurm_states(self, rec: JobRecord) -> list[str]:
        """Return live Slurm states for a WES array parent."""
        try:
            live_jobs = Cluster(rec.job.ssh_config).get_jobs()
        except Exception as e:  # noqa: BLE001
            print(f"[hub] could not read Slurm array state for {rec.job.job_name}: {e}")
            return []
        stored = self.store.get_job(rec.job.namespace) or {}
        known_ids = set(getattr(rec.job.task, "jobs_ids", []))
        if stored.get("job_id"):
            known_ids.add(stored["job_id"])

        def parent_id(job_id: str) -> str:
            return job_id.split("_", 1)[0]

        return [
            slurm_state(info.state).value
            for info in live_jobs
            if info.name == rec.job.job_name
            or any(parent_id(info.job_id) == parent_id(job_id) for job_id in known_ids)
        ]

    def _store_array_statuses(self, rec: JobRecord, statuses: list[JobStatus]) -> None:
        for status in statuses:
            self.store.upsert_array_child(
                rec.job.namespace,
                status.array_index,
                job_id=status.job_id,
                state=status.state.value,
                node=status.node,
                partition=status.partition,
                message=status.message,
                updated=status.updated,
            )
        states = [status.state.value for status in statuses]
        # Child status files only exist after an array element starts. Include
        # squeue's pending/running elements so completion cannot be premature.
        states.extend(self._array_slurm_states(rec))
        aggregate = run_status(states)
        if aggregate:
            rec.last_state = aggregate
            rec.status_seen = True
            self.store.set_job_state(rec.job.namespace, aggregate)

    def _forget_missing_status(self, rec: JobRecord) -> None:
        namespace = rec.job.namespace
        with self.lock:
            if self.registry.get(namespace) is rec:
                self.registry.pop(namespace)
        self.store.delete_job(namespace)
        print(f"[hub] removed {namespace}: server wes.status no longer exists")

    def _slurm_live(self, ssh: str, job_name: str, known_ids, live_jobs=None) -> bool:
        """Whether Slurm still knows this job, including an array task."""
        if live_jobs is None:
            try:
                live_jobs = Cluster(ssh).get_jobs()
            except Exception as e:  # noqa: BLE001
                print(f"[hub] could not check Slurm for {job_name}: {e}")
                return True

        def base_job_id(job_id: str) -> str:
            return job_id.split("_", 1)[0]

        for info in live_jobs:
            if info.name == job_name:
                return True
            if any(base_job_id(info.job_id) == base_job_id(k) for k in known_ids if k):
                return True
        return False

    def _slurm_has_job(self, rec: JobRecord) -> bool:
        stored = self.store.get_job(rec.job.namespace) or {}
        known_ids = set(getattr(rec.job.task, "jobs_ids", []))
        if stored.get("job_id"):
            known_ids.add(stored["job_id"])
        return self._slurm_live(rec.job.ssh_config, rec.job.job_name, known_ids)

    def _sync_job_status(self, rec: JobRecord) -> None:
        job = rec.job
        # prune jobs whose directory no longer exists on the server (removed
        # by cleanup, wes clean, or manually) instead of erroring on every
        # poll; None means the server was unreachable - keep the job then
        job_dir_exists = job.status_file.job_dir_exists()
        if job_dir_exists is False:
            self._forget_missing_status(rec)
            return
        if job_dir_exists is None:
            return
        try:
            found = job.pull_status()
        except Exception as e:  # noqa: BLE001
            print(f"[hub] status pull failed for {job.job_name}: {e}")
            return
        if not found:
            # same rule for dispatched and discovered jobs: a persisted
            # (status-backed) job whose status file vanished and that Slurm
            # no longer knows is forgotten
            if rec.persisted and not self._slurm_has_job(rec):
                self._forget_missing_status(rec)
            return
        st = job.status
        if not st or not st.state:
            return
        self._store_status(rec, st)
        # a wes.status stuck at PENDING/RUNNING (e.g. an array parent whose
        # tasks only write array-status children) still resolves once Slurm
        # has finished the job: fall back to sacct when squeue no longer
        # lists it
        if st.state in (State.PENDING, State.RUNNING) and not self._slurm_has_job(rec):
            finished = self._sacct_states(rec)
            if finished:
                state = run_status(finished) or finished[0]
                rec.last_state = state
                rec.status_seen = True
                self._persist(rec)
                self.store.set_job_state(rec.job.namespace, state)

    def _sacct_states(self, rec: JobRecord) -> list[str]:
        """Finished Slurm states from sacct for this job, array elements included."""
        try:
            infos = JobsQuery(rec.job.ssh_config).get_recent()
        except Exception as e:  # noqa: BLE001
            print(f"[hub] sacct lookup failed for {rec.job.job_name}: {e}")
            return []
        stored = self.store.get_job(rec.job.namespace) or {}
        known_ids = set(getattr(rec.job.task, "jobs_ids", []))
        if stored.get("job_id"):
            known_ids.add(stored["job_id"])

        def base(job_id: str) -> str:
            return job_id.split("_", 1)[0]

        return [
            slurm_state(info.state).value
            for info in infos
            if info.name == rec.job.job_name
            or any(base(info.job_id) == base(known) for known in known_ids)
        ]

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
            if status not in ("", "queued", "running", State.PENDING.value, State.RUNNING.value):
                self.store.update_run(run_id, status, finished_at=_time.time())
            else:
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
            elif (
                rec.last_state in (State.PENDING.value, State.RUNNING.value)
                and time.time() - rec.last_progress_pull >= self.settings.progress_interval
            ):
                self._bounded(self._pull_progress, rec)
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
        if self.settings.catalog_repo:
            self.sync_catalog()
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

    # ------------------------------------------------------------------ #
    # snapshots                                                          #
    # ------------------------------------------------------------------ #

    def state(self) -> dict:
        pipelines = []
        for p in self.list_pipelines():
            pipelines.append(p)
        runs = self.store.list_runs(limit=50)
        for r in runs:
            r["jobs"] = [self.enrich_job(job) for job in self.list_jobs(r["id"])]
            r["created_at_iso"] = _iso(r["created_at"])
            r["finished_at_iso"] = _iso(r["finished_at"])
        jobs = [self.enrich_job(job) for job in self.list_jobs()]
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
