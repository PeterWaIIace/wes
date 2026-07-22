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
    cache = JobCache(persistent=True)
    while True:
        try:
            for name, data in (cache.get_all() or {}).items():
                state = State(data["state"])
                if state == State.RUNNING:
                    task = JobCache.cached_task(name, data)
                    try:
                        new_status = await asyncio.to_thread(task.execute)
                    except Exception as e:
                        log.error("Poller error on task '%s': %s", name, e)
                        new_status = State.FAILED

                    if new_status == State.RUNNING:
                        cache.set(name, JobCache.task_to_cache_data(task))
                        log.info("Task '%s': still running, artifacts synced", name)
                    else:
                        cache.set(
                            name,
                            {
                                **JobCache.task_to_cache_data(task),
                                "state": new_status.value,
                            },
                        )
                        log.info("Task '%s': %s", name, new_status.value)
        except Exception:
            pass
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
