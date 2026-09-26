"""Weighted least-squares adjustment for interconnected leveling networks.

This is a separate ControlSync workflow. It does not alter the validated Ron
three-wire workbook reduction or existing differential-level run solver.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def _finite(name: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite.")
    return number


def _positive(name: str, value: float) -> float:
    number = _finite(name, value)
    if number <= 0:
        raise ValueError(f"{name} must be positive.")
    return number


def _huber_weights(standardized: np.ndarray, k: float) -> np.ndarray:
    absolute = np.abs(standardized)
    weights = np.ones_like(absolute)
    mask = absolute > k
    weights[mask] = k / absolute[mask]
    return weights


def adjust_level_network(
    *,
    points: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    robust: bool = False,
    huber_k: float = 1.5,
    review_threshold: float = 3.0,
    max_iterations: int = 20,
) -> dict[str, Any]:
    """Adjust benchmark elevations from observed elevation differences.

    Observation convention: delta_elevation = elevation(to_id) - elevation(from_id).
    Observation sigma is in project vertical units.
    """

    if not points:
        raise ValueError("At least one level-network point is required.")
    if not observations:
        raise ValueError("At least one level observation is required.")
    huber_k = _positive("Huber k", huber_k)
    review_threshold = _positive("Review threshold", review_threshold)
    max_iterations = int(max_iterations)
    if not 1 <= max_iterations <= 100:
        raise ValueError("max_iterations must be between 1 and 100.")

    point_map: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for index, raw in enumerate(points, start=1):
        point_id = str(raw.get("point_id") or "").strip()
        if not point_id:
            raise ValueError(f"Point {index} is missing point_id.")
        if point_id in point_map:
            raise ValueError(f"Duplicate level-network point_id: {point_id}")
        point_map[point_id] = {
            "point_id": point_id,
            "elevation": _finite(f"{point_id} elevation", raw.get("elevation")),
            "fixed": bool(raw.get("fixed", False)),
        }
        order.append(point_id)

    if not any(bool(point_map[p]["fixed"]) for p in order):
        raise ValueError("At least one fixed benchmark is required.")

    unknown = [p for p in order if not bool(point_map[p]["fixed"])]
    if not unknown:
        raise ValueError("Level network contains no adjustable benchmarks.")
    parameter_index = {point_id: i for i, point_id in enumerate(unknown)}

    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(observations, start=1):
        from_id = str(raw.get("from_id") or "").strip()
        to_id = str(raw.get("to_id") or "").strip()
        if from_id not in point_map or to_id not in point_map:
            raise ValueError(f"Observation {index} references an unknown benchmark.")
        if from_id == to_id:
            raise ValueError(f"Observation {index} cannot begin and end on the same benchmark.")
        normalized.append(
            {
                "index": index,
                "from_id": from_id,
                "to_id": to_id,
                "delta_elevation": _finite(
                    f"Observation {index} delta elevation", raw.get("delta_elevation")
                ),
                "sigma": _positive(f"Observation {index} sigma", raw.get("sigma")),
            }
        )

    a = np.zeros((len(normalized), len(unknown)), dtype=float)
    l = np.zeros(len(normalized), dtype=float)
    base_weights = np.zeros(len(normalized), dtype=float)

    for row_index, obs in enumerate(normalized):
        constant = 0.0
        if obs["from_id"] in parameter_index:
            a[row_index, parameter_index[obs["from_id"]]] -= 1.0
        else:
            constant -= float(point_map[obs["from_id"]]["elevation"])
        if obs["to_id"] in parameter_index:
            a[row_index, parameter_index[obs["to_id"]]] += 1.0
        else:
            constant += float(point_map[obs["to_id"]]["elevation"])
        l[row_index] = float(obs["delta_elevation"]) - constant
        base_weights[row_index] = 1.0 / float(obs["sigma"]) ** 2

    if int(np.linalg.matrix_rank(a)) < len(unknown):
        raise ValueError(
            "Level network is rank deficient. Connect every adjustable benchmark "
            "to the fixed datum with independent observations."
        )

    robust_weights = np.ones(len(normalized), dtype=float)
    solution = np.zeros(len(unknown), dtype=float)
    iterations = 0
    for iterations in range(1, max_iterations + 1):
        weights = base_weights * robust_weights
        sqrt_w = np.sqrt(weights)
        aw = a * sqrt_w[:, None]
        lw = l * sqrt_w
        solution, *_ = np.linalg.lstsq(aw, lw, rcond=None)
        residuals = a @ solution - l

        if not robust:
            break
        normalized_residuals = residuals / np.asarray(
            [float(row["sigma"]) for row in normalized], dtype=float
        )
        next_weights = _huber_weights(normalized_residuals, huber_k)
        if float(np.max(np.abs(next_weights - robust_weights))) <= 1e-8:
            robust_weights = next_weights
            break
        robust_weights = next_weights

    weights = base_weights * robust_weights
    normal = a.T @ (weights[:, None] * a)
    if int(np.linalg.matrix_rank(normal)) < len(unknown):
        raise ValueError("Final level-network normal matrix is singular.")
    qxx = np.linalg.inv(normal)
    residuals = a @ solution - l
    rank = int(np.linalg.matrix_rank(a))
    dof = len(normalized) - rank
    weighted_ss = float(np.sum(weights * residuals * residuals))
    variance_factor = weighted_ss / dof if dof > 0 else 1.0
    covariance = qxx * variance_factor

    h = a @ qxx @ (a.T * weights)
    redundancy = np.clip(1.0 - np.diag(h), 0.0, 1.0)

    adjusted_points: list[dict[str, Any]] = []
    for point_id in order:
        initial = float(point_map[point_id]["elevation"])
        if point_id in parameter_index:
            idx = parameter_index[point_id]
            elevation = float(solution[idx])
            sigma = math.sqrt(max(float(covariance[idx, idx]), 0.0))
        else:
            elevation = initial
            sigma = 0.0
        adjusted_points.append(
            {
                "point_id": point_id,
                "fixed": bool(point_map[point_id]["fixed"]),
                "initial_elevation": initial,
                "elevation": elevation,
                "shift": elevation - initial,
                "sigma_elevation": sigma,
            }
        )

    result_observations: list[dict[str, Any]] = []
    review_count = 0
    for i, (obs, residual, red) in enumerate(
        zip(normalized, residuals, redundancy, strict=True)
    ):
        sigma_v = (
            math.sqrt(max(float(red), 0.0) / float(base_weights[i]))
            * math.sqrt(max(variance_factor, 0.0))
        )
        standardized = float(residual / sigma_v) if sigma_v > 1e-15 else 0.0
        needs_review = abs(standardized) >= review_threshold
        review_count += int(needs_review)
        result_observations.append(
            {
                **obs,
                "adjusted_residual": float(residual),
                "redundancy": float(red),
                "standardized_residual": standardized,
                "robust_weight": float(robust_weights[i]),
                "status": "REVIEW" if needs_review else "OK",
            }
        )

    return {
        "method": "weighted_level_network",
        "iterations": iterations,
        "robust": bool(robust),
        "huber_k": huber_k,
        "point_count": len(order),
        "adjusted_point_count": len(unknown),
        "observation_count": len(normalized),
        "parameter_count": len(unknown),
        "degrees_of_freedom": dof,
        "variance_factor": variance_factor,
        "reference_standard_deviation": math.sqrt(max(variance_factor, 0.0)),
        "weighted_sum_squares": weighted_ss,
        "redundancy_sum": float(np.sum(redundancy)),
        "review_threshold": review_threshold,
        "review_count": review_count,
        "points": adjusted_points,
        "observations": result_observations,
        "quality_note": (
            "This is a separate weighted benchmark-network adjustment. "
            "Ronald's validated three-wire workbook profile is unchanged. "
            "REVIEW flags require survey judgment and are never auto-deleted."
        ),
    }
