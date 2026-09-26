"""Weighted leveling-network API kept separate from the frozen main router."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .api_models import LevelNetworkAdjustmentIn
from .level_network import adjust_level_network

router = APIRouter()


def _project():
    from . import router as main_router

    return main_router.require_project()


@router.post("/api/v9/level/network-adjust")
def level_network_adjust(payload: LevelNetworkAdjustmentIn):
    project = _project()
    try:
        result = adjust_level_network(
            points=[point.model_dump() for point in payload.points],
            observations=[observation.model_dump() for observation in payload.observations],
            robust=payload.robust,
            huber_k=payload.huber_k,
            review_threshold=payload.review_threshold,
            max_iterations=payload.max_iterations,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc

    project.db.audit(
        "ControlSync",
        "LEVEL_NETWORK_ADJUSTMENT",
        details={
            "points": [point.model_dump() for point in payload.points],
            "observations": [observation.model_dump() for observation in payload.observations],
            "settings": {
                "robust": payload.robust,
                "huber_k": payload.huber_k,
                "review_threshold": payload.review_threshold,
                "max_iterations": payload.max_iterations,
            },
            "result_summary": {
                "degrees_of_freedom": result["degrees_of_freedom"],
                "variance_factor": result["variance_factor"],
                "review_count": result["review_count"],
            },
        },
    )
    return result
