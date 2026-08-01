from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from web.api import router as api_router
from web.cache import JobCache
from web.engine import check_jobs_alive
from web.routes import router as pages_router

log = logging.getLogger("wes.web")

STATIC_DIR = Path(__file__).parent / "static"

_poller_task: asyncio.Task | None = None


async def _poll_running_jobs() -> None:
    while True:
        try:
            cache = JobCache()
            entries = cache.get_all()
            for run_id, data in list(entries.items()):
                if not isinstance(data, dict):
                    continue
                state = data.get("state", "")
                if state != "RUNNING":
                    continue

                job_ids = data.get("jobs_ids", [])
                ssh = data.get("ssh", "")
                if not job_ids or not ssh:
                    continue

                if check_jobs_alive(ssh, job_ids):
                    cache.set(run_id, data)
                else:
                    data["state"] = "COMPLETED"
                    cache.set(run_id, data)
                    log.info("Task '%s': completed", data.get("task_name", run_id))
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
    app = FastAPI(title="wes", lifespan=lifespan)
    app.include_router(api_router)
    app.include_router(pages_router)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return app


def main() -> None:
    uvicorn.run("web.app:create_app", factory=True, host="127.0.0.1", port=8000)
