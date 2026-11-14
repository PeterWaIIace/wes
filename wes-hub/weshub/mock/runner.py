"""Mock SshRunner: executes "remote" commands and file copies inside a local
sandbox directory instead of over ssh.

Implements the exact subset of the wes SshRunner interface that wes-hub
touches: run_command (with stdin scripts), scp_to, scp_from, get_user,
create_dir, cleanup_dir. SLURM commands (sbatch, squeue, sinfo, ...) are
provided by weshub/mock/bin and resolved through PATH.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class MockRunner:
    def __init__(self, ssh_config: str, path_prefix: str = "") -> None:
        self.ssh_config = ssh_config
        self.path_prefix = path_prefix
        from weshub.mock import mock_config

        cfg = mock_config()
        self.cluster_dir = cfg["cluster_dir"]  # type: ignore[assignment]

    # -- helpers -----------------------------------------------------------

    def _env(self) -> dict:
        from weshub.mock import mock_config

        cfg = mock_config()
        env = os.environ.copy()
        env["PATH"] = f"{cfg['bin_dir']}:{env['PATH']}"
        env["WESHUB_MOCK_STATE"] = str(Path(cfg["state_dir"]) / "jobs.tsv")
        env["WESHUB_MOCK_CLUSTER"] = str(cfg["cluster_dir"])
        return env

    def log(self, msg: str, kind: str = "•") -> None:
        pass

    # -- remote shell ------------------------------------------------------

    def get_user(self) -> str:
        return "mockuser"

    def run_command(
        self,
        cmd: str,
        script: str | None = None,
        retries: int = 0,
        retry_delay: float = 2.0,
        quiet: bool = False,
    ) -> tuple[bool, list[str]]:
        result = subprocess.run(
            ["bash", "-c", cmd],
            input=script,
            capture_output=True,
            text=True,
            check=False,
            cwd=self.cluster_dir,
            env=self._env(),
        )
        if result.returncode != 0:
            err = result.stderr.strip() or f"exit code {result.returncode}"
            print(f"[mock] command failed: {cmd}\n{err}")
            return False, []
        return True, [
            line
            for line in result.stdout.splitlines()
            if line.strip() and not line.startswith("JOBID")
        ]

    # -- file transfer -----------------------------------------------------

    def scp_to(self, dir: str, file: str | None, r: bool = False) -> bool:
        """Emulate ``scp <file> <config>:<dir>/`` (file lands inside dir)."""
        if not file:
            return False
        dest = Path(self.cluster_dir) / dir
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / Path(file).name
        if r and Path(file).is_dir():
            shutil.copytree(file, target, dirs_exist_ok=True)
        elif r:
            shutil.copy2(file, target)
        else:
            shutil.copy2(file, target)
        # wes stages scripts into a temp dir (mode 644) before uploading;
        # on a real cluster admins typically assume shell scripts execute.
        if target.suffix == ".sh":
            target.chmod(0o755)
        return True

    def scp_from(
        self,
        remote_path: str,
        tfile: str = "",
        cfile: str = "",
        r: bool = False,
    ) -> bool:
        """Emulate ``rsync [-r] <config>:<remote_path>/<tfile> <cfile>``."""
        src = Path(self.cluster_dir) / remote_path
        if tfile:
            src = src / tfile
        if not src.exists():
            print(f"[mock] scp_from: missing source {src}")
            return False
        name = tfile or Path(remote_path).name
        target = Path(cfile.rstrip("/")) / name if r else Path(cfile)
        target.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, target, dirs_exist_ok=True)
        else:
            shutil.copy2(src, target)
        return True

    # -- convenience (same semantics as SshRunner) --------------------------

    def create_dir(self, dir: str) -> bool:
        ok, _ = self.run_command(f"mkdir -p {dir}")
        return ok

    def cleanup_dir(self, dir: str) -> None:
        self.run_command(f"rm -rf {dir}")
