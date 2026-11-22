"""Remote directory metadata and glob expansion without downloading file contents."""

from __future__ import annotations

import shlex
from pathlib import PurePosixPath


def list_remote_directory(runner, directory: str, offset: int = 0, limit: int = 200) -> dict:
    """Return one page of immediate children; GNU find follows directory symlinks."""
    if offset < 0 or not 1 <= limit <= 1000:
        raise ValueError("offset must be nonnegative and limit must be between 1 and 1000")
    command = (
        "set -o pipefail; "
        f"find -L {shlex.quote(directory)} -mindepth 1 -maxdepth 1 "
        "-printf '%y\\t%s\\t%f\\n' | LC_ALL=C sort | "
        f"awk 'NR > {offset} && NR <= {offset + limit + 1}'"
    )
    ok, lines = runner.run_command(command, quiet=True)
    if not ok:
        raise RuntimeError(f"Cannot list remote directory: {directory}")
    entries = []
    for line in lines[:limit]:
        kind, size, name = line.split("\t", 2)
        if kind not in ("d", "f"):
            continue
        entries.append({"name": name, "directory": kind == "d", "size": int(size),
                        "path": str(PurePosixPath(directory) / name)})
    return {"entries": entries, "next_offset": offset + limit if len(lines) > limit else None}


def inspect_remote_patterns(runner, patterns: list[str]) -> list[dict]:
    """Expand configured patterns and describe their existing file/directory roots."""
    if not patterns:
        return []
    commands = ["shopt -s nullglob globstar; IFS=;"]
    for pattern in patterns:
        commands.append(
            f"pattern={shlex.quote(pattern)}; "
            'for path in $pattern; do '
            'if [ -d "$path" ]; then kind=d; elif [ -f "$path" ]; then kind=f; else continue; fi; '
            'size=$(stat -Lc %s -- "$path") || exit 1; '
            'printf "%s\\t%s\\t%s\\n" "$kind" "$size" "$path"; done;'
        )
    ok, lines = runner.run_command(f"bash -c {shlex.quote(' '.join(commands))}", quiet=True)
    if not ok:
        raise RuntimeError("Cannot inspect configured artifact paths")
    entries = {}
    for line in lines:
        kind, size, path = line.split("\t", 2)
        path = str(PurePosixPath(path))
        entries[path] = {"path": path, "name": PurePosixPath(path).name,
                         "directory": kind == "d", "size": int(size)}
    return list(entries.values())


def remote_tree(runner, directory: str, depth: int = 2) -> list[str]:
    """Render up to 200 entries per directory, stopping at the requested depth."""
    if not 1 <= depth <= 20:
        raise ValueError("tree depth must be between 1 and 20")
    lines = [directory]
    stack = [(directory, "", 0, True, None)]
    while stack:
        current, prefix, level, is_directory, name = stack.pop()
        if name is not None:
            lines.append(f"{prefix}|-- {name}{'/' if is_directory else ''}")
        if not is_directory or level >= depth:
            continue
        page = list_remote_directory(runner, current)
        if page["next_offset"] is not None:
            stack.append(("", prefix, depth, False, "... more entries (listing capped at 200)"))
        child_prefix = prefix + "|   " if name is not None else prefix
        for entry in reversed(page["entries"]):
            stack.append((entry["path"], child_prefix, level + 1, entry["directory"], entry["name"]))
    return lines
