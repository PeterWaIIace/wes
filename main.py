#!/usr/bin/env python3
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.cache import JobCache
from src.parser import WESParser
from src.states import State


def main():
    load_dotenv()

    cache = JobCache()

    cached_tasks = {}
    for name, data in cache.get_all().items():
        state = State(data["state"])
        if state in (State.RUNNING, State.PENDING):
            cached_tasks[name] = JobCache.cached_task(name, data)
        else:
            cache.remove(name)

    config_file = sys.argv[1] if len(sys.argv) > 1 else "tasks.wes"
    wes = WESParser()
    new_tasks = wes.parse(config_file)

    seen = set(cached_tasks)
    tasks = list(cached_tasks.values())
    tasks.extend(t for t in new_tasks if t.name not in seen)

    for task in tasks:
        print(f"\n▸ {task.name}")
        task.execute()

        if task.status == State.RUNNING:
            cache.set(task.name, JobCache.task_to_cache_data(task))

        while task.status == State.RUNNING:
            time.sleep(10)
            task.execute()

        if task.status in (State.COMPLETED, State.FAILED):
            cache.remove(task.name)


if __name__ == "__main__":
    main()
