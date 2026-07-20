#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time

from dotenv import load_dotenv

from .cache import JobCache
from .parser import WESParser
from .states import State


def _run(args: argparse.Namespace) -> None:
    cache = JobCache()

    cached_tasks: dict = {}
    for name, data in cache.get_all().items():
        state = State(data["state"])
        if state in (State.RUNNING, State.PENDING):
            task = JobCache.cached_task(name, data)
            if task.has_alive_jobs():
                cached_tasks[name] = task
            else:
                cache.remove(name)
        else:
            cache.remove(name)

    wes = WESParser()
    new_tasks = wes.parse(args.config)

    seen = set(cached_tasks)
    tasks = list(cached_tasks.values())
    tasks.extend(t for t in new_tasks if t.name not in seen)

    try:
        for task in tasks:
            print(f"\n▸ {task.name}")
            task.execute()

            if task.status == State.RUNNING:
                cache.set(task.name, JobCache.task_to_cache_data(task))

            while task.status == State.RUNNING:
                time.sleep(2)
                task.execute()

            if task.status in (State.COMPLETED, State.FAILED):
                cache.remove(task.name)
    finally:
        cache.close()


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run(
        "web.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(prog="wes")
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Run a .wes config file")
    run_p.add_argument("config", help="Path to .wes config file")

    serve_p = sub.add_parser("serve", help="Start the web interface")
    serve_p.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    serve_p.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    serve_p.add_argument("--reload", action="store_true", help="Enable auto-reload for development")

    args, remaining = parser.parse_known_args()

    if args.command == "serve":
        _serve(args)
    elif args.command == "run":
        _run(args)
    elif remaining and remaining[0].endswith(".wes"):
        args.config = remaining[0]
        _run(args)
    else:
        parser.print_help()
