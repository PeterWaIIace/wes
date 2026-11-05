from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from weshub import api
from weshub.config import Settings
from weshub.manager import Hub

WEB_DIR = Path(__file__).resolve().parent / "web"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.ensure_dirs()
    hub = Hub(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not getattr(app.state, "disable_lifecycle", False):
            hub.start()
        yield
        hub.stop()

    app = FastAPI(title="wes-hub", version="0.1.0", lifespan=lifespan)
    api.set_hub(hub)
    app.include_router(api.router)

    app.mount("/results", StaticFiles(directory=str(settings.results_dir)), name="results")
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(WEB_DIR / "favicon.svg")

    return app
