"""ControlSync network-adjustment API kept separate from the frozen main router."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .api_models import ControlNetworkAdjustmentIn
from .network_adjustment import adjust_control_network

router = APIRouter()


def _project():
    from . import router as main_router

    return main_router.require_project()


@router.post("/api/v9/control/network-adjust")
def control_network_adjust(payload: ControlNetworkAdjustmentIn):
    project = _project()
    try:
        result = adjust_control_network(
            points=[point.model_dump() for point in payload.points],
            observations=[observation.model_dump() for observation in payload.observations],
            max_iterations=payload.max_iterations,
            tolerance=payload.tolerance,
            robust=payload.robust,
            huber_k=payload.huber_k,
            review_threshold=payload.review_threshold,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc

    project.db.audit(
        "ControlSync",
        "NETWORK_ADJUSTMENT",
        details={
            "points": [point.model_dump() for point in payload.points],
            "observations": [observation.model_dump() for observation in payload.observations],
            "settings": {
                "max_iterations": payload.max_iterations,
                "tolerance": payload.tolerance,
                "robust": payload.robust,
                "huber_k": payload.huber_k,
                "review_threshold": payload.review_threshold,
            },
            "result_summary": {
                "converged": result["converged"],
                "iterations": result["iterations"],
                "degrees_of_freedom": result["degrees_of_freedom"],
                "sigma0": result["sigma0"],
                "review_count": result["review_count"],
            },
        },
    )
    return result
