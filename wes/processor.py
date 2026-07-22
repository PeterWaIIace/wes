#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time

from .cache import JobCache
from .jobs.controller import JobController
from .jobs.query import JobsQuery
from .parser import WESParser
from .remote.runner import RemoteRunner
from .tasks.states import State
from .tasks.tasks import Task, TaskManager


class Processor:

    def __init__(self, ssh_config: str = "") -> None:
        self.ssh_config = ssh_config
        self.cache = JobCache()

    def _runner_for(self, task: Task) -> RemoteRunner:
        return RemoteRunner(task.ssh_config or self.ssh_config)

    def _query_for(self, task: Task) -> JobsQuery:
        return JobsQuery(task.ssh_config or self.ssh_config)

    def create_task(self, task: Task) -> State:
        runner = self._runner_for(task)
        runner.create_dir(task._run_dir)
        if not runner.clone_repository(task._run_dir, task.git_url, task.branch):
            runner.log(f"failed to setup {task.name}", "✗")
            return State.FAILED
        return State.PENDING

    def pending_task(self, task: Task) -> State:
        runner = self._runner_for(task)
        controller = JobController(runner)
        state = controller.execute_job(task)
        if state == State.RUNNING:
            self.cache.set(task.name, JobCache.task_to_cache_data(task))
        return state

    def running_task(self, task: Task) -> State:
        query = self._query_for(task)
        if not query.has_alive_jobs(task.jobs_ids):
            if task.jobs_ids:
                return State.COMPLETED
            return State.RUNNING
        self.cache.set(task.name, JobCache.task_to_cache_data(task))
        return State.RUNNING

    def completed_task(self, task: Task) -> State:
        runner = self._runner_for(task)
        controller = JobController(runner)
        controller.execute_post_script(task)
        if task.artifacts:
            git_name = task.git_url.split("/")[-1].replace(".git", "")
            target_dir = f"{task._run_dir}/{git_name}/{task.path}"
            controller.sync_artifacts(task, target_dir, task.artifacts)
        if task.cleanup_git:
            runner.cleanup_dir(task._run_dir)
        task.jobs_ids = []
        self.cache.remove(task.name)
        return State.COMPLETED

    def failing_task(self, task: Task) -> State:
        runner = self._runner_for(task)
        if task.cleanup_git:
            runner.cleanup_dir(task._run_dir)
        task.jobs_ids = []
        self.cache.remove(task.name)
        return State.FAILED

    def run(self, args: argparse.Namespace) -> None:
        wes = WESParser()
        new_tasks = wes.parse(args.config)

        cached_tasks = {}
        for name, data in self.cache.get_all().items():
            if isinstance(data, dict):
                state = State(data.get("state", "PENDING"))
                if state in (State.RUNNING, State.PENDING):
                    task = JobCache.cached_task(name, data)
                    query = self._query_for(task)
                    if query.has_alive_jobs(task.jobs_ids):
                        cached_tasks[name] = task
                    else:
                        self.cache.remove(name)
                else:
                    self.cache.remove(name)

        seen = set(cached_tasks)
        tasks: list[Task] = list(cached_tasks.values())
        tasks.extend(t for t in new_tasks if t.name not in seen)

        task_mgr = TaskManager(tasks)
        task_mgr.add_create_cb(self.create_task)
        task_mgr.add_pending_cb(self.pending_task)
        task_mgr.add_running_cb(self.running_task)
        task_mgr.add_completed_cb(self.completed_task)
        task_mgr.add_failing_cb(self.failing_task)

        terminal = {State.COMPLETED, State.FAILED, State.CANCELLED}
        try:
            for task in tasks:
                print(f"\n▸ {task.name}")
                task_mgr.check(task.name)

                while task.getStatus() not in terminal:
                    time.sleep(2)
                    task_mgr.check(task.name)
        finally:
            self.cache.close()
