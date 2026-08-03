from __future__ import annotations

from fastapi import APIRouter

from web.cache import JobCache
from web.engine import get_cluster_data, get_nodes
from web.models import ClusterData, NodeInfo
from web.services.mock import mock_cluster_data, mock_enabled, mock_nodes

router = APIRouter()


def _default_ssh() -> str:
    cache = JobCache()
    for data in (cache.get_all() or {}).values():
        if data.get("ssh"):
            return data["ssh"]
    return ""


@router.get("/nodes", response_model=ClusterData)
def api_get_nodes(ssh: str = "") -> ClusterData:
    if mock_enabled():
        return ClusterData(ssh="mock", nodes=[NodeInfo(**n) for n in mock_nodes()])
    if not ssh:
        ssh = _default_ssh()
    if not ssh:
        return ClusterData(ssh="", error="No SSH host specified")
    try:
        nodes = get_nodes(ssh)
    except Exception as e:
        return ClusterData(ssh=ssh, error=str(e))
    return ClusterData(
        ssh=ssh,
        nodes=[
            NodeInfo(
                name=n["name"],
                partition=n["partition"],
                state=n["state"],
                cpus=n["cpus"],
                gpus=n["gpus"],
                memory=n["memory"],
                reason=n["reason"],
            )
            for n in nodes
        ],
    )


@router.get("/cluster")
def api_get_cluster(ssh: str = "") -> dict:
    if mock_enabled():
        return mock_cluster_data()
    if not ssh:
        ssh = _default_ssh()
    if not ssh:
        return {"ssh": "", "error": "No SSH host specified"}
    try:
        return get_cluster_data(ssh)
    except Exception as e:
        return {"ssh": ssh, "error": str(e)}
