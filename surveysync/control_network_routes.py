"""ControlSync conventional-network adjustment routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .api_models import ControlNetworkAdjustmentIn
from .network_adjustment import adjust_network_2d

router = APIRouter()


def _project():
    from . import router as main_router

    return main_router.require_project()


@router.post("/api/v9/control/network-adjustment")
def control_network_adjustment(payload: ControlNetworkAdjustmentIn):
    project = _project()
    try:
        result = adjust_network_2d(
            fixed_points=[point.model_dump() for point in payload.fixed_points],
            unknown_points=[point.model_dump() for point in payload.unknown_points],
            observations=[observation.model_dump() for observation in payload.observations],
            max_iterations=payload.max_iterations,
            convergence_tolerance=payload.convergence_tolerance,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    audit_result = {
        "method": result["method"],
        "converged": result["converged"],
        "iterations": result["iterations"],
        "observation_count": result["observation_count"],
        "unknown_point_count": result["unknown_point_count"],
        "degrees_of_freedom": result["degrees_of_freedom"],
        "variance_factor": result["variance_factor"],
        "flagged_residual_count": result["flagged_residual_count"],
        "adjusted_points": result["adjusted_points"],
    }
    project.db.audit(
        "ControlSync",
        "NETWORK_ADJUSTMENT_2D",
        details=payload.model_dump() | {"result": audit_result},
    )
    return result
