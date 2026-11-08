from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from weshub.manager import Hub, HubError

router = APIRouter(prefix="/api")

hub: Hub | None = None


def set_hub(h: Hub) -> None:
    global hub
    hub = h


def get_hub() -> Hub:
    assert hub is not None, "hub not initialised"
    return hub


def http_for(error: HubError):
    """Map a HubError to the matching HTTP status."""
    code = 404 if "not found" in str(error) else 400
    return HTTPException(status_code=code, detail=str(error))


class PipelineCreate(BaseModel):
    name: str
    wes_yaml: str
    ssh: str = ""
    cron: str = ""
    enabled: bool = True
    assets: dict[str, str] | None = None


class PipelinePatch(BaseModel):
    name: str | None = None
    wes_yaml: str | None = None
    ssh: str | None = None
    cron: str | None = None
    enabled: bool | None = None
    assets: dict[str, str] | None = None


@router.get("/pipelines")
def list_pipelines():
    return get_hub().list_pipelines()


@router.post("/pipelines", status_code=201)
def create_pipeline(req: PipelineCreate):
    try:
        return get_hub().create_pipeline(
            req.name, req.wes_yaml, req.ssh, req.cron, req.enabled, req.assets
        )
    except HubError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/pipelines/{pid}")
def get_pipeline(pid: int):
    try:
        return get_hub().get_pipeline(pid)
    except HubError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.patch("/pipelines/{pid}")
def patch_pipeline(pid: int, req: PipelinePatch):
    fields = req.model_dump(exclude_none=True)
    assets = fields.pop("assets", None)
    try:
        hub_ = get_hub()
        if assets:
            hub_.write_assets(pid, assets)
        return hub_.update_pipeline(pid, **fields)
    except HubError as e:
        raise http_for(e) from e


@router.delete("/pipelines/{pid}", status_code=204)
def delete_pipeline(pid: int):
    get_hub().delete_pipeline(pid)


@router.get("/pipelines/{pid}/assets")
def list_assets(pid: int):
    return get_hub().list_assets(pid)


@router.post("/pipelines/{pid}/dispatch", status_code=201)
def dispatch_pipeline(pid: int):
    try:
        return get_hub().trigger_run(pid)
    except HubError as e:
        raise http_for(e) from e


@router.get("/runs")
def list_runs(pipeline: int | None = None, limit: int = 100):
    hub_ = get_hub()
    runs = hub_.store.list_runs(pipeline, limit)
    for r in runs:
        r["jobs"] = hub_.store.list_jobs(r["id"])
    return runs


@router.get("/runs/{rid}")
def get_run(rid: int):
    run = get_hub().store.get_run(rid)
    if not run:
        raise HTTPException(status_code=404, detail=f"run {rid} not found")
    run["jobs"] = get_hub().store.list_jobs(rid)
    return run


@router.get("/jobs")
def list_jobs(run: int | None = None):
    return get_hub().store.list_jobs(run)


@router.post("/jobs/{namespace}/pull")
def pull_job(namespace: str):
    try:
        return get_hub().pull_job(namespace)
    except HubError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/discovery/{ssh}")
def run_discovery(ssh: str, path: str | None = None):
    """Adopt jobs on the cluster. With ``path``, recursively search that remote
    dir for wes.status files (non-hidden only, no descent past a found status
    file); without it, scan for *_config.json under the remote workdir."""
    return {"adopted": get_hub().discover(ssh, path)}


@router.get("/clusters")
def clusters():
    return list(get_hub().clusters.values())


@router.get("/clusters/{ssh}")
def cluster(ssh: str, refresh: bool = False):
    hub_ = get_hub()
    if ssh not in hub_.clusters or refresh:
        hub_._refresh_cluster(ssh, max_age=0.0 if refresh else 30.0)
    if ssh not in hub_.clusters:
        raise HTTPException(status_code=404, detail=f"no cluster snapshot for '{ssh}'")
    return hub_.clusters[ssh]


@router.get("/state")
def state():
    return get_hub().state()
