from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from wes.cache import JobCache
from wes.states import State

log = logging.getLogger("wes.web")

STATIC_DIR = Path(__file__).parent / "static"
RESULTS_DIR = Path("results")

_poller_task: asyncio.Task | None = None


async def _poll_running_jobs() -> None:
    while True:
        try:
            cache = JobCache(persistent=True)
            try:
                entries = cache.get_all()
                for run_id, data in list(entries.items()):
                    if not isinstance(data, dict):
                        continue
                    state = State(data.get("state", ""))
                    if state != State.RUNNING:
                        continue

                    task = JobCache.cached_task(run_id, data)
                    if not task.jobs_ids or not task.ssh_config:
                        continue

                    from wes.jobs.controller import JobController
                    from wes.remote.runner import RemoteRunner

                    runner = RemoteRunner(task.ssh_config)
                    query_ok = runner.run_command(
                        f"squeue -j {','.join(task.jobs_ids)} -h -o '%T'"
                    )
                    alive_states = {"RUNNING", "PENDING", "SUSPENDED", "COMPLETING"}
                    is_alive = False
                    if query_ok[0] and query_ok[1]:
                        states = {s.strip() for s in query_ok[1] if s.strip()}
                        is_alive = bool(states & alive_states)

                    if is_alive:
                        if task.artifacts:
                            try:
                                controller = JobController(runner)
                                controller.sync_artifacts(task, task._artifact_dir, task.artifacts)
                                log.info("Task '%s': artifacts synced", task.name)
                            except Exception as e:
                                log.error("Artifact sync error for '%s': %s", task.name, e)
                        cache.set(run_id, JobCache.task_to_cache_data(task))
                    else:
                        cache.set(
                            run_id,
                            {
                                **JobCache.task_to_cache_data(task),
                                "state": State.COMPLETED.value,
                            },
                        )
                        log.info("Task '%s': completed", task.name)
            finally:
                cache.close()
        except Exception as e:
            log.error("Poller error: %s", e)
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    global _poller_task
    _poller_task = asyncio.create_task(_poll_running_jobs())
    log.info("wes web started")
    yield
    if _poller_task:
        _poller_task.cancel()


def create_app() -> FastAPI:
    from web.api import router as api_router
    from web.routes import router as pages_router

    app = FastAPI(title="wes", lifespan=lifespan)
    app.include_router(api_router)
    app.include_router(pages_router)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return app


def main() -> None:
    import uvicorn

    uvicorn.run("web.app:create_app", factory=True, host="127.0.0.1", port=8000)
