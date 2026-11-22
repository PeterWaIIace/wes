"""Path-based job discovery over ssh.

Complements the ``*_config.json`` scan in ``wes.jobs.scanner.JobScanner``:
given a remote base dir, recursively look for directories that directly
contain a ``wes.status`` file. Hidden entries (anything starting with a
dot) are never entered, and once a directory holds a status file it is
reported and not descended into - that directory is a job dir, so its
subtree cannot contain another job.

The search is a single ``find`` per call, executed on the cluster through
a wes ``SshRunner``-like object (``run_command(cmd) -> (ok, lines)``).
"""

from __future__ import annotations

import shlex

from wes.jobs.status import STATUS_FILENAME, JobStatus


def read_status_batch(runner, directories: list[str], allow_missing: bool = False) -> dict:
    """Read a batch in one SSH command; fail rather than return a partial scan."""
    if not directories:
        return {}
    paths = " ".join(shlex.quote(path) for path in directories)
    command = (
        f"for directory in {paths}; do "
        "printf '\\n__WES_STATUS_BEGIN__%s\\n' \"$directory\"; "
        f'if [ -f "$directory/{STATUS_FILENAME}" ]; then '
        f'cat "$directory/{STATUS_FILENAME}" || exit 1; '
        'else echo __WES_STATUS_MISSING__; fi; done'
    )
    ok, lines = runner.run_command(command)
    if not ok:
        raise RuntimeError("Could not read all discovered statuses")
    statuses = {}
    directory = None
    content = []
    for line in lines:
        if line.startswith("__WES_STATUS_BEGIN__"):
            if directory is not None:
                statuses[directory] = parse_batch_status(content, allow_missing)
            directory = line.removeprefix("__WES_STATUS_BEGIN__")
            content = []
        else:
            content.append(line)
    if directory is not None:
        statuses[directory] = parse_batch_status(content, allow_missing)
    if len(statuses) != len(directories):
        raise RuntimeError("Incomplete discovery status batch")
    return statuses


def parse_batch_status(content: list[str], allow_missing: bool):
    if content == ["__WES_STATUS_MISSING__"]:
        if allow_missing:
            return None
        raise RuntimeError("A status file disappeared during discovery")
    return JobStatus.from_text("\n".join(content))


def _root_cmd(base_dir: str) -> str:
    # does the base dir itself hold a status file? (-maxdepth 0 tests only
    # the starting point, so a hidden-named base is still honoured)
    q = shlex.quote(base_dir)
    return f"find {q} -maxdepth 0 -exec test -f '{{}}/{STATUS_FILENAME}' \\; -print"


def _tree_cmd(base_dir: str) -> str:
    # every non-hidden dir that directly contains a status file; -prune
    # stops the descent there. -mindepth 1 keeps the base itself out of
    # the '.*' prune (find would otherwise match the '.' of a '.' base).
    q = shlex.quote(base_dir)
    return (
        f"find {q} -mindepth 1 -name '.*' -prune "
        f"-o -type d -exec test -f '{{}}/{STATUS_FILENAME}' \\; -print -prune"
    )


def find_status_dirs(runner, base_dir: str) -> list[str]:
    """Remote dirs at or under ``base_dir`` that directly contain a status file.

    Returns [] when the path does not exist or the command fails. If the
    base dir itself is a job dir, only it is returned (the search stops at
    the first status file found on any branch, the root included).
    """
    base_dir = base_dir.rstrip("/") or "/"
    ok, lines = runner.run_command(_root_cmd(base_dir))
    if not ok:
        raise RuntimeError(f"Could not inspect discovery root {base_dir}")
    if lines:
        return [base_dir]
    ok, lines = runner.run_command(_tree_cmd(base_dir))
    if not ok:
        raise RuntimeError(f"Discovery scan failed under {base_dir}")
    return lines
