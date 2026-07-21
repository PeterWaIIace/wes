import subprocess


def _ssh_run(ssh_config: str, cmd: str) -> list[str]:
    """Run a command via SSH and return non-header lines."""
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
