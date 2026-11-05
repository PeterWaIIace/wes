"""Mock cluster for wes-hub: run the full dispatch -> sbatch -> wes.status ->
results-download flow without any real cluster.

`setup()` prepares a sandbox (fake cluster dir, a local git repo to clone,
executable SLURM tool stand-ins). `activate()` swaps the `SshRunner` class
bindings inside the wes package modules for `MockRunner` at runtime - the wes
source tree is never modified. `deactivate()` restores them.

Usage:

    wes-hub serve --mock            # server + demo pipeline
    uv run wes-hub serve --mock --port 8420
"""

from __future__ import annotations

import importlib
import os
import stat
import subprocess
from pathlib import Path

_BIN_DIR = Path(__file__).resolve().parent / "bin"

_PATCH_TARGETS = (
    "wes.remote.runner",
    "wes.jobs.job",
    "wes.jobs.status",
    "wes.jobs.scanner",
    "wes.jobs.query",
    "wes.clusters.observer",
)
_saved: dict[str, type] = {}

# module-level runtime config, filled by setup()
_CONFIG: dict[str, str] = {}


def mock_config() -> dict[str, str]:
    return _CONFIG


# NOTE: do not `cd` in the job script - wes's injected exit trap calls
# ./wes_status.sh relative to the job dir, so a cd would break status updates.
DEMO_JOB = "#!/bin/bash\nset -e\nbash example-repo/run.sh\n"
DEMO_PRE = "#!/bin/bash\necho 'pre-script ok'\n"
DEMO_REPO_RUN = """#!/bin/bash
set -e
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$here/results"
echo "results from mock job at $(date)" > "$here/results/summary.txt"
echo "work done"
sleep 3
"""


def setup(settings) -> None:
    """Create the mock cluster sandbox. Idempotent."""
    mock_dir = Path(settings.data_dir) / "mock"
    cluster_dir = mock_dir / "cluster"
    repos_dir = mock_dir / "repos"
    state_dir = cluster_dir / ".mock"
    for d in (cluster_dir, repos_dir, state_dir):
        d.mkdir(parents=True, exist_ok=True)
    (state_dir / "jobs.tsv").touch()
    _CONFIG.update(
        {
            "mock_dir": str(mock_dir),
            "cluster_dir": str(cluster_dir),
            "repos_dir": str(repos_dir),
            "state_dir": str(state_dir),
            "bin_dir": str(_BIN_DIR),
        }
    )
    # the SLURM tools are data files; make sure they stay executable
    for tool in _BIN_DIR.iterdir():
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    _ensure_demo_repo(repos_dir / "example-repo")


def _ensure_demo_repo(repo: Path) -> None:
    if (repo / ".git").exists():
        return
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "README.md").write_text("example repo for the wes-hub mock cluster\n")
    (repo / "run.sh").write_text(DEMO_REPO_RUN)
    env = os.environ.copy()
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=repo, env=env, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-c", "user.name=mock", "-c", "user.email=mock@mock", "add", "-A"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=mock",
            "-c",
            "user.email=mock@mock",
            "commit",
            "-m",
            "demo repo for mock cluster",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def demo_wes_yaml() -> str:
    """A pipeline spec that clones the local demo repo and runs its job."""
    git_url = str(Path(_CONFIG["repos_dir"]) / "example-repo")
    return (
        "sequence:\n"
        "  - example_run:\n"
        f"      git_url: {git_url}\n"
        "      branch: main\n"
        "      ssh: mock\n"
        "      pre: pre.sh\n"
        "      job: job.sh\n"
        "      artifacts:\n"
        "        - results\n"
    )


def seed_demo_pipeline(hub) -> dict | None:
    """Create the demo pipeline if the hub has none yet."""
    if hub.store.list_pipelines():
        return None
    return hub.create_pipeline(
        name="mock-demo",
        wes_yaml=demo_wes_yaml(),
        ssh="mock",
        cron="",
        enabled=True,
        assets={"job.sh": DEMO_JOB, "pre.sh": DEMO_PRE},
    )


def activate() -> None:
    """Swap SshRunner with MockRunner inside the wes modules."""
    global _saved
    if _saved:
        return
    from weshub.mock.runner import MockRunner

    for mod_name in _PATCH_TARGETS:
        mod = importlib.import_module(mod_name)
        _saved[mod_name] = mod.SshRunner
        mod.SshRunner = MockRunner
    print("[mock] activated: all wes ssh traffic targets the local sandbox")


def deactivate() -> None:
    """Restore the real SshRunner."""
    global _saved
    import importlib

    for mod_name, cls in _saved.items():
        importlib.import_module(mod_name).SshRunner = cls
    _saved = {}
    print("[mock] deactivated")
