from __future__ import annotations

from fastapi import APIRouter

from web.routers import cluster, jobs, settings, tasks

router = APIRouter(prefix="/api")
router.include_router(tasks.router)
router.include_router(jobs.router)
router.include_router(cluster.router)
router.include_router(settings.router)
