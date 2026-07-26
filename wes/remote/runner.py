from __future__ import annotations

import subprocess


class SshRunner:
    def __init__(self, ssh_config: str, path_prefix : str = "") -> None:
        self.ssh_config = ssh_config
        self.path_prefix = path_prefix

    def log(self, msg: str, kind: str = "•") -> None:
        print(f"  {kind} {msg}")

    def get_user(self) -> str:
        result = self._ssh_run(self.ssh_config, "whoami")
        print(result)
        return result[1][0].strip()

    def _ssh_run(
        self, ssh_config: str, cmd: str, script: str | None = None
    ) -> tuple[bool, list[str]]:
        result = subprocess.run(
            ["ssh", ssh_config, cmd],
            input=script,
            capture_output=True,
            text=True,
            check=False,
        )
        print("result:", result)
        if result.returncode != 0:
            print(f"ssh command failed: {result.stderr}")
            return False, []
        print("--------------")
        return True, [
            line
            for line in result.stdout.strip().splitlines()
            if line.strip() and not line.startswith("JOBID")
        ]

    def run_command(self, cmd: str, script: str | None = None) -> tuple[bool, list[str]]:
        try:
            return self._ssh_run(self.ssh_config, cmd, script)
        except Exception as e:
            print(f"Error running command '{cmd}': {e}")
            return False, []

    def create_dir(self, dir: str) -> bool:
        self.log(f"creating run dir {dir}", "▶")
        ok, _ = self.run_command(f"mkdir -p {dir}")
        return ok

    def cleanup_dir(self, dir: str) -> None:
        self.log(f"cleaning up dir {dir}", "▶")
        self.run_command(f"rm -rf {dir}")

    def clone_repository(self, dir: str, git_url: str, branch: str = "") -> bool:
        git_name = git_url.split("/")[-1].replace(".git", "")
        if branch:
            clone_cmd = f"git clone -b {branch} {git_url} {dir}/{git_name}"
        else:
            clone_cmd = f"git clone {git_url} {dir}/{git_name}"
        status, result = self.run_command(clone_cmd)
        if not status:
            self.log(f"clone failed for {git_url}", "✗")
            return False
        return True

    def scp_to(self, dir: str, file: str | None, r: bool = False) -> bool:
        if not file:
            self.log("no file specified for SCP", "⚠")
            return False
        dest = f"{self.ssh_config}:{dir}/"
        print("Copying file to remote:", file, "to", dest)
        cmd = ["scp", file, dest]
        if r:
            cmd = ["scp", "-r", file, dest]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if stderr:
                self.log(f"scp error: {stderr}", "✗")
            return False
        return True

    def scp_from(self, remote_path: str, tfile: str = "", cfile: str = "", r: bool = False) -> bool:
        src = f"{self.ssh_config}:{remote_path}/{tfile}"
        cmd = ["rsync", "-e", "ssh", src, cfile]
        if r:
            cmd = ["rsync", "-r", "--no-inc-recursive", "-e", "ssh", src, cfile]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if stderr:
                self.log(f"rsync error: {stderr}", "✗")
            return False
        return True


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
