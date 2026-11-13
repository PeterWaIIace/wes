from __future__ import annotations

import os
import signal
import time
from collections import deque
from hashlib import sha256
from pathlib import Path
from shlex import quote

import yaml

from wes.cluster import Cluster
from wes.clusters.node import NodeCapacity
from wes.engine import Engine
from wes.jobs.job import JobInfo, SshItem, STATUS_FILENAME
from wes.jobs.scanner import JobScanner
from wes.remote.runner import SshRunner

class WES:
    def __init__(self, ssh: str | None = None):
        self.ssh = ssh
        self.cluster = Cluster(ssh) if ssh else None

    def _status_cache_path(self, rootdir: str) -> Path:
        key = sha256(f"{self.ssh}\0{rootdir}".encode()).hexdigest()
        return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "wes" / f"{key}.yaml"

    def _read_status_cache(self, rootdir: str) -> list[str]:
        try:
            data = yaml.safe_load(self._status_cache_path(rootdir).read_text())
        except (OSError, yaml.YAMLError):
            return []
        return data if isinstance(data, list) and all(isinstance(path, str) for path in data) else []

    def _write_status_cache(self, rootdir: str, paths: list[str]) -> None:
        cache_path = self._status_cache_path(rootdir)
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(yaml.safe_dump(paths))
        except OSError:
            pass

    def set_ssh(self, ssh):
        self.ssh = ssh
        self.cluster = Cluster(ssh)

    def get_nodes(self) -> list:
        return [n.info for n in self.cluster.get_nodes()]

    def get_jobs(self) -> list[JobInfo]:
        return self.cluster.get_jobs()

    def get_capacity(self) -> list[NodeCapacity]:
        return self.cluster.get_capacity()

    def dispatch(self, config) -> None:
        engine = Engine()
        engine.start_jobs(task_file=config)

    def get_job_status(self):
        pass

    def pull(self, pull_dir) -> list:
        SshItem(pull_dir, pull_dir, self.ssh).sync()

    def sync(self) -> None:
        engine = Engine()
        engine.add_user(self.ssh)
        engine.background_scan()

        def _shutdown(signum, frame):
            engine.run = False

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        try:
            while engine.run:
                time.sleep(1)
        except KeyboardInterrupt:
            engine.run = False
        finally:
            print("\nShutting down...")
            engine.stop()

    def ls(self, lsdir=None, recursive=False, depth=None) -> list:
        return JobScanner(self.ssh).list_dir(lsdir, recursive=recursive, depth=depth)

    def _read_status(self, path: str) -> dict | None:
        ok, lines = SshRunner(self.ssh).run_command(f"cat {quote(path)}", quiet=True)
        if not ok or not lines:
            return None
        data = yaml.safe_load("\n".join(lines))
        return data if isinstance(data, dict) else None

    def _discover_statuses(self, rootdir="."):
        statuses = []
        dirs_to_discover = deque([rootdir])
        while dirs_to_discover:
            current_dir = dirs_to_discover.popleft()
            results = JobScanner(self.ssh, quiet=True).list_dir(current_dir, recursive=False, depth=1)

            status_paths = [p for p in results if os.path.basename(p) == STATUS_FILENAME]
            if status_paths:
                # current_dir directly holds wes.status: it is a job dir, read
                # the status and do not descend into it (find -prune semantics)
                for path in status_paths:
                    data = self._read_status(path)
                    if data:
                        statuses.append((current_dir, path, data))
                continue

            # upload_scripts() creates this config file before the pre-script
            # has a chance to create wes.status. It still identifies a WES job
            # directory, so never descend into its cloned repository.
            if any(os.path.basename(path).endswith("_config.json") for path in results):
                continue

            # descend into subdirectories only; plain files (other than
            # WES status/config markers, handled above) would just waste a find
            # per entry
            subdirs = JobScanner(self.ssh, quiet=True).list_dir(
                current_dir, recursive=False, depth=1, dirs_only=True
            )
            for path in subdirs:
                if any(part.startswith(".") and len(part) > 1 for part in path.split("/")):
                    continue
                dirs_to_discover.append(path)
        return statuses

    def _statuses(self, rootdir=".", refresh=False):
        if not refresh:
            cached = []
            for path in self._read_status_cache(rootdir):
                data = self._read_status(path)
                if data:
                    cached.append((str(Path(path).parent), path, data))
            if cached:
                return cached

        discovered = self._discover_statuses(rootdir)
        self._write_status_cache(rootdir, [path for _dir, path, _status in discovered])
        return discovered

    def check(self, rootdir=".", refresh=False):
        return [status for _dir, _path, status in self._statuses(rootdir, refresh)]

    def clean(self, rootdir=".", dry_run=False, refresh=False) -> list[str]:
        """Remove discovered WES job directories whose recorded state is FAILED."""
        failed_dirs = [
            path
            for path, _status_path, status in self._statuses(rootdir, refresh)
            if status.get("state") == "FAILED"
        ]
        if dry_run:
            return [f"would remove {path}" for path in failed_dirs]

        removed = []
        runner = SshRunner(self.ssh)
        for path in failed_dirs:
            ok, _ = runner.run_command(f"rm -rf -- {quote(path)}", quiet=True)
            if ok:
                removed.append(f"removed {path}")
        return removed