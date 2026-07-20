#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time

from dotenv import load_dotenv

from .cache import JobCache
from .parser import WESParser
from .states import State


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("config", help="Path to .wes config file")
    args = parser.parse_args()

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
