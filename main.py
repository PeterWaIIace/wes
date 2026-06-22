#!/usr/bin/env python3
import argparse
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.cache import CACHE_FILE, JobCache
from src.parser import WESParser
from src.states import State


def main():
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", action="store_true", help="Remove cache file and exit")
    parser.add_argument("config", nargs="?", default="tasks.wes", help="Path to config file")
    args = parser.parse_args()

    if args.clean:
        if CACHE_FILE.exists():
            CACHE_FILE.unlink()
            print("Cache file removed.")

    cache = JobCache()

    cached_tasks = {}
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


if __name__ == "__main__":
    main()
