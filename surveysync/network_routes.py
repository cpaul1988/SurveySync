"""ControlSync network-adjustment API kept separate from the frozen main router."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .api_models import ControlNetworkAdjustmentIn
from .network_adjustment import adjust_control_network
from .pysurveying_reference import validate_native_network

router = APIRouter()


def _project():
    from . import router as main_router

    return main_router.require_project()


@router.post("/api/v9/control/network-adjust")
def control_network_adjust(payload: ControlNetworkAdjustmentIn):
    project = _project()
    point_rows = [point.model_dump() for point in payload.points]
    observation_rows = [observation.model_dump() for observation in payload.observations]

    try:
        result = adjust_control_network(
            points=point_rows,
            observations=observation_rows,
            max_iterations=payload.max_iterations,
            tolerance=payload.tolerance,
            robust=payload.robust,
            huber_k=payload.huber_k,
            review_threshold=payload.review_threshold,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc

    # Independent validation must never replace or block the production solver.
    # A validator failure is surfaced for review while preserving the native result.
    try:
        validation = validate_native_network(
            points=point_rows,
            observations=observation_rows,
            native_result=result,
            max_iterations=payload.max_iterations,
            tolerance=payload.tolerance,
            robust=payload.robust,
            huber_k=payload.huber_k,
            review_threshold=payload.review_threshold,
        )
    except Exception as exc:
        validation = {
            "status": "UNAVAILABLE",
            "engine": "pysurveying_reference",
            "upstream": "hujinghaoabcd/pySurveying",
            "license": "MIT",
            "error": str(exc),
            "note": (
                "The native SurveySync adjustment completed, but the independent "
                "reference calculation could not be completed."
            ),
        }

    result["independent_validation"] = validation

    project.db.audit(
        "ControlSync",
        "NETWORK_ADJUSTMENT",
        details={
            "points": point_rows,
            "observations": observation_rows,
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
                "independent_validation": validation.get("status"),
                "max_reference_coordinate_delta": validation.get(
                    "max_coordinate_delta"
                ),
            },
        },
    )
    return result
