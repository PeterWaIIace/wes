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
        self.cache = JobCache(persistent=True)

    def _runner_for(self, task: Task) -> RemoteRunner:
        return RemoteRunner(task.ssh_config or self.ssh_config)

    def _query_for(self, task: Task) -> JobsQuery:
        return JobsQuery(task.ssh_config or self.ssh_config)

    def create_task(self, task: Task) -> State:
        print("[CREATING TASK]")
        runner = self._runner_for(task)
        runner.create_dir(task._run_dir)
        if not runner.clone_repository(task._run_dir, task.git_url, task.branch):
            runner.log(f"failed to setup {task.name}", "✗")
            return State.FAILED
        controller = JobController(runner)
        controller.upload_scripts(task)
        return State.PENDING

    def pending_task(self, task: Task) -> State:
        print("[CHECKING PENDING TASK]")
        runner = self._runner_for(task)
        controller = JobController(runner)
        state = controller.execute_job(task)
        if state == State.RUNNING:
            self.cache.set(task.run_id, JobCache.task_to_cache_data(task))
        return state

    def running_task(self, task: Task) -> State:
        query = self._query_for(task)
        runner = self._runner_for(task)
        controller = JobController(runner)
        if task.artifacts:
            controller.sync_artifacts(task, task._artifact_dir, task.artifacts)
        if not query.has_alive_jobs(task.jobs_ids):
            if task.jobs_ids:
                return State.COMPLETED
            return State.RUNNING
        self.cache.set(task.run_id, JobCache.task_to_cache_data(task))
        return State.RUNNING

    def completed_task(self, task: Task) -> State:
        print(f"[COMPLETING TASK]: {task.name}")
        runner = self._runner_for(task)
        controller = JobController(runner)
        controller.execute_post_script(task)
        if task.artifacts:
            controller.sync_artifacts(task, task._artifact_dir, task.artifacts)
        if task.cleanup_git:
            runner.cleanup_dir(task._run_dir)
        task.jobs_ids = []
        self.cache.remove(task.run_id)
        return State.COMPLETED

    def failing_task(self, task: Task) -> State:
        print("[TASK FAILED]")
        runner = self._runner_for(task)
        if task.cleanup_git:
            runner.cleanup_dir(task._run_dir)
        task.jobs_ids = []
        self.cache.remove(task.run_id)
        return State.FAILED

    def run(self, args: argparse.Namespace) -> None:
        wes = WESParser()
        new_tasks = wes.parse(args.config)

        new_names = {t.name for t in new_tasks}

        for _run_id, task in self.cache.clean_for_task_names(new_names):
            if task.jobs_ids and task.ssh_config:
                for jid in task.jobs_ids:
                    try:
                        import subprocess
                        subprocess.run(
                            ["ssh", task.ssh_config, f"scancel {jid}"],
                            capture_output=True, text=True, check=False,
                        )
                    except Exception:
                        pass

        def _is_alive(task: Task) -> bool:
            if not task.jobs_ids:
                return False
            return self._query_for(task).has_alive_jobs(task.jobs_ids)

        self.cache.clean_dead(_is_alive)

        alive = {}
        for run_id, data in self.cache.get_all().items():
            if isinstance(data, dict):
                alive[run_id] = JobCache.cached_task(run_id, data)

        tasks: list[Task] = list(alive.values()) + new_tasks

        task_mgr = TaskManager(tasks)
        task_mgr.add_create_cb(self.create_task)
        task_mgr.add_pending_cb(self.pending_task)
        task_mgr.add_running_cb(self.running_task)
        task_mgr.add_completed_cb(self.completed_task)
        task_mgr.add_failing_cb(self.failing_task)

        try:
            while True:
                for task in tasks:
                    print(f"\n▸ {task.name}")
                    task_mgr.check(task.name)

                time.sleep(2)
        finally:
            self.cache.close()
