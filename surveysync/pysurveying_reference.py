"""Independent pySurveying-style validation engine for SurveySync control networks.

The production SurveySync solver remains authoritative. This module provides a
second calculation path for numerical cross-checking and review. It follows the
MIT-licensed pySurveying project's public adjustment/QC behavior and concepts,
but uses SurveySync's northing/easting API and analytic observation derivatives
instead of the production solver's numerical Jacobian.

Upstream: https://github.com/hujinghaoabcd/pySurveying
Copyright (c) 2026 Jinghao Hu
License: MIT
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

_ELLIPSE_95_SCALE = 2.447746830680816
_RAD_TO_DEG = 180.0 / math.pi


def _finite(name: str, value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite.")
    return number


def _normalize_deg(value: float) -> float:
    return float(value) % 360.0


def _angle_difference(calculated: float, observed: float) -> float:
    return (float(calculated) - float(observed) + 180.0) % 360.0 - 180.0


def _huber_weights(residuals: np.ndarray, k: float) -> np.ndarray:
    absolute = np.abs(residuals)
    weights = np.ones_like(absolute)
    mask = absolute > k
    weights[mask] = k / absolute[mask]
    return weights


def _ellipse95(covariance: np.ndarray) -> dict[str, float]:
    block = np.asarray(covariance, dtype=float)
    block = (block + block.T) / 2.0
    eigenvalues, eigenvectors = np.linalg.eigh(block)
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = np.maximum(eigenvalues[order], 0.0)
    major_vector = eigenvectors[:, order[0]]
    return {
        "semi_major": _ELLIPSE_95_SCALE * math.sqrt(float(eigenvalues[0])),
        "semi_minor": _ELLIPSE_95_SCALE * math.sqrt(float(eigenvalues[1])),
        "azimuth_deg": (
            math.degrees(
                math.atan2(float(major_vector[1]), float(major_vector[0]))
            )
            % 180.0
        ),
    }


def reference_adjust_control_network(
    *,
    points: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    max_iterations: int = 20,
    tolerance: float = 1e-7,
    robust: bool = False,
    huber_k: float = 1.5,
    review_threshold: float = 3.0,
) -> dict[str, Any]:
    """Run an independent constrained 2D weighted least-squares adjustment."""

    if not points:
        raise ValueError("At least one network point is required.")
    if not observations:
        raise ValueError("At least one network observation is required.")
    if int(max_iterations) < 1 or int(max_iterations) > 100:
        raise ValueError("max_iterations must be between 1 and 100.")
    tolerance_value = _finite("Tolerance", tolerance)
    huber_value = _finite("Huber k", huber_k)
    review_value = _finite("Review threshold", review_threshold)
    if tolerance_value <= 0 or huber_value <= 0 or review_value <= 0:
        raise ValueError("Tolerance, Huber k, and review threshold must be positive.")

    point_map: dict[str, dict[str, Any]] = {}
    point_order: list[str] = []
    for index, row in enumerate(points, start=1):
        point_id = str(row.get("point_id") or "").strip()
        if not point_id:
            raise ValueError(f"Point {index} is missing point_id.")
        if point_id in point_map:
            raise ValueError(f"Duplicate network point_id: {point_id}")
        point_map[point_id] = {
            "northing": _finite(f"{point_id} northing", row["northing"]),
            "easting": _finite(f"{point_id} easting", row["easting"]),
            "fixed": bool(row.get("fixed", False)),
        }
        point_order.append(point_id)

    if not any(point_map[name]["fixed"] for name in point_order):
        raise ValueError("At least one fixed control point is required.")

    normalized: list[dict[str, Any]] = []
    supported = {"distance", "azimuth", "direction", "angle"}
    for index, row in enumerate(observations, start=1):
        kind = str(row.get("kind") or "").strip().lower()
        if kind not in supported:
            raise ValueError(f"Observation {index} has unsupported kind: {kind or '(blank)'}")
        from_id = str(row.get("from_id") or "").strip()
        to_id = str(row.get("to_id") or "").strip()
        target2_id = str(row.get("target2_id") or "").strip() or None
        if from_id not in point_map or to_id not in point_map:
            raise ValueError(f"Observation {index} references an unknown point.")
        if kind == "angle":
            if not target2_id:
                raise ValueError(f"Angle observation {index} requires target2_id.")
            if target2_id not in point_map:
                raise ValueError(
                    f"Observation {index} references unknown target2 point {target2_id!r}."
                )
        sigma = _finite(f"Observation {index} sigma", row["sigma"])
        if sigma <= 0:
            raise ValueError(f"Observation {index} sigma must be positive.")
        normalized.append(
            {
                "kind": kind,
                "from_id": from_id,
                "to_id": to_id,
                "target2_id": target2_id,
                "value": _finite(f"Observation {index} value", row["value"]),
                "sigma": sigma,
            }
        )

    unknown_points = [name for name in point_order if not point_map[name]["fixed"]]
    if not unknown_points:
        raise ValueError("Network contains no adjustable points.")

    coordinate_index: dict[str, tuple[int, int]] = {}
    packed: list[float] = []
    for name in unknown_points:
        coordinate_index[name] = (len(packed), len(packed) + 1)
        packed.extend(
            [float(point_map[name]["northing"]), float(point_map[name]["easting"])]
        )

    coordinate_parameter_count = len(packed)
    direction_stations = sorted(
        {str(row["from_id"]) for row in normalized if row["kind"] == "direction"}
    )
    orientation_index: dict[str, int] = {}

    def initial_xy(point_id: str) -> tuple[float, float]:
        point = point_map[point_id]
        return float(point["northing"]), float(point["easting"])

    def raw_azimuth(start: tuple[float, float], end: tuple[float, float]) -> float:
        dn = end[0] - start[0]
        de = end[1] - start[1]
        if dn * dn + de * de <= 1e-30:
            raise ValueError("Angular observation contains coincident points.")
        return math.degrees(math.atan2(de, dn)) % 360.0

    orientations: list[float] = []
    for station in direction_stations:
        first = next(
            row
            for row in normalized
            if row["kind"] == "direction" and row["from_id"] == station
        )
        predicted = raw_azimuth(
            initial_xy(station), initial_xy(str(first["to_id"]))
        )
        orientation_index[station] = coordinate_parameter_count + len(orientations)
        orientations.append(_normalize_deg(predicted - float(first["value"])))

    current = np.asarray(packed + orientations, dtype=float)

    def coordinates(state: np.ndarray, point_id: str) -> tuple[float, float]:
        point = point_map[point_id]
        if point["fixed"]:
            return float(point["northing"]), float(point["easting"])
        ni, ei = coordinate_index[point_id]
        return float(state[ni]), float(state[ei])

    def azimuth_with_derivatives(
        state: np.ndarray, from_id: str, to_id: str
    ) -> tuple[float, dict[int, float]]:
        n1, e1 = coordinates(state, from_id)
        n2, e2 = coordinates(state, to_id)
        dn = n2 - n1
        de = e2 - e1
        d2 = dn * dn + de * de
        if d2 <= 1e-30:
            raise ValueError("Angular observation contains coincident points.")
        derivatives: dict[int, float] = {}
        dnt = (-de / d2) * _RAD_TO_DEG
        det = (dn / d2) * _RAD_TO_DEG
        if not point_map[to_id]["fixed"]:
            ni, ei = coordinate_index[to_id]
            derivatives[ni] = derivatives.get(ni, 0.0) + dnt
            derivatives[ei] = derivatives.get(ei, 0.0) + det
        if not point_map[from_id]["fixed"]:
            ni, ei = coordinate_index[from_id]
            derivatives[ni] = derivatives.get(ni, 0.0) - dnt
            derivatives[ei] = derivatives.get(ei, 0.0) - det
        return math.degrees(math.atan2(de, dn)) % 360.0, derivatives

    def distance_with_derivatives(
        state: np.ndarray, from_id: str, to_id: str
    ) -> tuple[float, dict[int, float]]:
        n1, e1 = coordinates(state, from_id)
        n2, e2 = coordinates(state, to_id)
        dn = n2 - n1
        de = e2 - e1
        distance = math.hypot(dn, de)
        if distance <= 1e-15:
            raise ValueError("Distance observation contains coincident points.")
        derivatives: dict[int, float] = {}
        dnt = dn / distance
        det = de / distance
        if not point_map[to_id]["fixed"]:
            ni, ei = coordinate_index[to_id]
            derivatives[ni] = derivatives.get(ni, 0.0) + dnt
            derivatives[ei] = derivatives.get(ei, 0.0) + det
        if not point_map[from_id]["fixed"]:
            ni, ei = coordinate_index[from_id]
            derivatives[ni] = derivatives.get(ni, 0.0) - dnt
            derivatives[ei] = derivatives.get(ei, 0.0) - det
        return distance, derivatives

    def residual_and_design(
        state: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, list[float]]:
        residuals: list[float] = []
        calculated_values: list[float] = []
        design = np.zeros((len(normalized), state.size), dtype=float)
        for row_index, row in enumerate(normalized):
            kind = row["kind"]
            sigma = float(row["sigma"])
            observed = float(row["value"])
            if kind == "distance":
                calculated, derivatives = distance_with_derivatives(
                    state, row["from_id"], row["to_id"]
                )
                raw_residual = calculated - observed
            elif kind == "azimuth":
                calculated, derivatives = azimuth_with_derivatives(
                    state, row["from_id"], row["to_id"]
                )
                raw_residual = _angle_difference(calculated, observed)
            elif kind == "direction":
                azimuth, derivatives = azimuth_with_derivatives(
                    state, row["from_id"], row["to_id"]
                )
                orientation_position = orientation_index[row["from_id"]]
                calculated = _normalize_deg(
                    azimuth - float(state[orientation_position])
                )
                derivatives[orientation_position] = (
                    derivatives.get(orientation_position, 0.0) - 1.0
                )
                raw_residual = _angle_difference(calculated, observed)
            else:
                back_azimuth, back_derivatives = azimuth_with_derivatives(
                    state, row["from_id"], row["to_id"]
                )
                fore_azimuth, fore_derivatives = azimuth_with_derivatives(
                    state, row["from_id"], row["target2_id"]
                )
                calculated = _normalize_deg(fore_azimuth - back_azimuth)
                derivatives: dict[int, float] = {}
                for column, value in fore_derivatives.items():
                    derivatives[column] = derivatives.get(column, 0.0) + value
                for column, value in back_derivatives.items():
                    derivatives[column] = derivatives.get(column, 0.0) - value
                raw_residual = _angle_difference(calculated, observed)

            calculated_values.append(float(calculated))
            residuals.append(raw_residual / sigma)
            for column, derivative in derivatives.items():
                design[row_index, column] = derivative / sigma
        return np.asarray(residuals, dtype=float), design, calculated_values

    converged = False
    iteration = 0
    for iteration in range(1, int(max_iterations) + 1):
        residuals, design, _ = residual_and_design(current)
        weights = (
            _huber_weights(residuals, huber_value)
            if robust
            else np.ones_like(residuals)
        )
        sqrt_weights = np.sqrt(weights)
        correction, *_ = np.linalg.lstsq(
            design * sqrt_weights[:, None],
            -(residuals * sqrt_weights),
            rcond=None,
        )
        current = current + correction
        for station in direction_stations:
            current[orientation_index[station]] = _normalize_deg(
                current[orientation_index[station]]
            )
        if float(np.max(np.abs(correction))) < tolerance_value:
            converged = True
            break

    residuals, design, calculated = residual_and_design(current)
    weights = (
        _huber_weights(residuals, huber_value)
        if robust
        else np.ones_like(residuals)
    )
    weighted_design = design * np.sqrt(weights)[:, None]
    rank = int(np.linalg.matrix_rank(weighted_design))
    parameter_count = int(current.size)
    if rank < parameter_count:
        raise ValueError(
            "Reference network is rank deficient. Add independent control or observations."
        )

    dof = int(len(normalized) - rank)
    weighted_ss = float(np.sum(weights * residuals**2))
    sigma0 = math.sqrt(weighted_ss / dof) if dof > 0 else None
    weight_matrix = np.diag(weights)
    qxx = np.linalg.pinv(design.T @ weight_matrix @ design)
    covariance = qxx if sigma0 is None else qxx * sigma0**2
    qll = np.diag(1.0 / weights)
    qvv = qll - design @ qxx @ design.T
    qvv = (qvv + qvv.T) / 2.0
    redundancy = np.clip(np.diag(qvv @ weight_matrix), 0.0, 1.0)

    observation_rows: list[dict[str, Any]] = []
    for index, (row, calc, normalized_residual, red, robust_weight) in enumerate(
        zip(normalized, calculated, residuals, redundancy, weights, strict=True),
        start=1,
    ):
        sigma = float(row["sigma"])
        standardized = None
        if red > 1e-12:
            scale = sigma0 if sigma0 is not None and sigma0 > 1e-12 else 1.0
            standardized = float(normalized_residual) / (
                scale * math.sqrt(float(red))
            )
        observation_rows.append(
            {
                "index": index,
                "kind": row["kind"],
                "from_id": row["from_id"],
                "to_id": row["to_id"],
                "target2_id": row["target2_id"],
                "observed": row["value"],
                "calculated": calc,
                "residual": float(normalized_residual) * sigma,
                "normalized_residual": float(normalized_residual),
                "sigma": sigma,
                "redundancy": float(red),
                "standardized_residual": standardized,
                "robust_weight": float(robust_weight),
                "status": (
                    "REVIEW"
                    if standardized is not None
                    and abs(standardized) >= review_value
                    else "OK"
                ),
            }
        )

    adjusted_points: list[dict[str, Any]] = []
    for name in point_order:
        initial_n = float(point_map[name]["northing"])
        initial_e = float(point_map[name]["easting"])
        fixed = bool(point_map[name]["fixed"])
        adjusted_n, adjusted_e = coordinates(current, name)
        if fixed:
            sigma_n = sigma_e = correlation = 0.0
            ellipse = {
                "semi_major": 0.0,
                "semi_minor": 0.0,
                "azimuth_deg": 0.0,
            }
        else:
            ni, ei = coordinate_index[name]
            block = covariance[np.ix_([ni, ei], [ni, ei])]
            sigma_n = math.sqrt(max(0.0, float(block[0, 0])))
            sigma_e = math.sqrt(max(0.0, float(block[1, 1])))
            denominator = sigma_n * sigma_e
            correlation = (
                float(block[0, 1]) / denominator if denominator > 0 else 0.0
            )
            ellipse = _ellipse95(block)
        adjusted_points.append(
            {
                "point_id": name,
                "fixed": fixed,
                "northing": adjusted_n,
                "easting": adjusted_e,
                "horizontal_shift": math.hypot(
                    adjusted_n - initial_n, adjusted_e - initial_e
                ),
                "sigma_northing": sigma_n,
                "sigma_easting": sigma_e,
                "correlation_ne": correlation,
                "ellipse95_semi_major": ellipse["semi_major"],
                "ellipse95_semi_minor": ellipse["semi_minor"],
                "ellipse95_azimuth_deg": ellipse["azimuth_deg"],
            }
        )

    return {
        "engine": "pysurveying_reference",
        "upstream": "hujinghaoabcd/pySurveying",
        "upstream_version": "0.3.0",
        "license": "MIT",
        "converged": converged,
        "iterations": iteration,
        "parameter_count": parameter_count,
        "rank": rank,
        "degrees_of_freedom": dof,
        "sigma0": sigma0,
        "robust": bool(robust),
        "huber_k": huber_value,
        "review_threshold": review_value,
        "redundancy_sum": float(np.sum(redundancy)),
        "points": adjusted_points,
        "observations": observation_rows,
        "orientations_deg": {
            station: float(current[index])
            for station, index in orientation_index.items()
        },
        "quality_note": (
            "Independent reference calculation uses analytic observation derivatives "
            "and NumPy least-squares. It does not replace the production solver."
        ),
    }


def validate_native_network(
    *,
    points: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    native_result: dict[str, Any],
    max_iterations: int = 20,
    tolerance: float = 1e-7,
    robust: bool = False,
    huber_k: float = 1.5,
    review_threshold: float = 3.0,
    coordinate_tolerance: float = 1e-4,
    normalized_residual_tolerance: float = 1e-4,
    redundancy_tolerance: float = 1e-4,
    ellipse_tolerance: float = 1e-4,
    sigma0_tolerance: float = 1e-4,
) -> dict[str, Any]:
    """Compare native SurveySync output with the independent reference result."""

    reference = reference_adjust_control_network(
        points=points,
        observations=observations,
        max_iterations=max_iterations,
        tolerance=tolerance,
        robust=robust,
        huber_k=huber_k,
        review_threshold=review_threshold,
    )
    native_points = {
        str(row["point_id"]): row for row in native_result.get("points", [])
    }
    reference_points = {str(row["point_id"]): row for row in reference["points"]}

    point_deltas: list[dict[str, Any]] = []
    max_coordinate_delta = 0.0
    max_ellipse_delta = 0.0
    for point_id in sorted(reference_points):
        if point_id not in native_points:
            raise ValueError(f"Native result is missing point {point_id!r}.")
        native = native_points[point_id]
        ref = reference_points[point_id]
        dn = float(native["northing"]) - float(ref["northing"])
        de = float(native["easting"]) - float(ref["easting"])
        horizontal_delta = math.hypot(dn, de)
        major_delta = abs(
            float(native.get("ellipse95_semi_major") or 0.0)
            - float(ref.get("ellipse95_semi_major") or 0.0)
        )
        minor_delta = abs(
            float(native.get("ellipse95_semi_minor") or 0.0)
            - float(ref.get("ellipse95_semi_minor") or 0.0)
        )
        max_coordinate_delta = max(max_coordinate_delta, horizontal_delta)
        max_ellipse_delta = max(max_ellipse_delta, major_delta, minor_delta)
        point_deltas.append(
            {
                "point_id": point_id,
                "delta_northing": dn,
                "delta_easting": de,
                "horizontal_delta": horizontal_delta,
                "ellipse95_major_delta": major_delta,
                "ellipse95_minor_delta": minor_delta,
            }
        )

    native_observations = list(native_result.get("observations") or [])
    if len(native_observations) != len(reference["observations"]):
        raise ValueError("Native/reference observation counts do not match.")

    observation_deltas: list[dict[str, Any]] = []
    max_normalized_residual_delta = 0.0
    max_redundancy_delta = 0.0
    for native, ref in zip(
        native_observations, reference["observations"], strict=True
    ):
        native_normalized = float(native["residual"]) / float(ref["sigma"])
        residual_delta = abs(
            native_normalized - float(ref["normalized_residual"])
        )
        redundancy_delta = abs(
            float(native["redundancy"]) - float(ref["redundancy"])
        )
        max_normalized_residual_delta = max(
            max_normalized_residual_delta, residual_delta
        )
        max_redundancy_delta = max(max_redundancy_delta, redundancy_delta)
        observation_deltas.append(
            {
                "index": int(ref["index"]),
                "normalized_residual_delta": residual_delta,
                "redundancy_delta": redundancy_delta,
            }
        )

    native_sigma0 = native_result.get("sigma0")
    reference_sigma0 = reference.get("sigma0")
    if native_sigma0 is None and reference_sigma0 is None:
        sigma0_delta = 0.0
    elif native_sigma0 is None or reference_sigma0 is None:
        sigma0_delta = float("inf")
    else:
        sigma0_delta = abs(float(native_sigma0) - float(reference_sigma0))

    checks = {
        "convergence_match": bool(native_result.get("converged"))
        == bool(reference.get("converged")),
        "coordinate_match": max_coordinate_delta <= coordinate_tolerance,
        "normalized_residual_match": (
            max_normalized_residual_delta <= normalized_residual_tolerance
        ),
        "redundancy_match": max_redundancy_delta <= redundancy_tolerance,
        "ellipse_match": max_ellipse_delta <= ellipse_tolerance,
        "sigma0_match": sigma0_delta <= sigma0_tolerance,
    }
    status = "PASS" if all(checks.values()) else "REVIEW"
    return {
        "status": status,
        "engine": reference["engine"],
        "upstream": reference["upstream"],
        "upstream_version": reference["upstream_version"],
        "license": reference["license"],
        "checks": checks,
        "tolerances": {
            "coordinate": coordinate_tolerance,
            "normalized_residual": normalized_residual_tolerance,
            "redundancy": redundancy_tolerance,
            "ellipse_axis": ellipse_tolerance,
            "sigma0": sigma0_tolerance,
        },
        "max_coordinate_delta": max_coordinate_delta,
        "max_normalized_residual_delta": max_normalized_residual_delta,
        "max_redundancy_delta": max_redundancy_delta,
        "max_ellipse_axis_delta": max_ellipse_delta,
        "sigma0_delta": sigma0_delta,
        "point_deltas": point_deltas,
        "observation_deltas": observation_deltas,
        "reference_summary": {
            "converged": reference["converged"],
            "iterations": reference["iterations"],
            "degrees_of_freedom": reference["degrees_of_freedom"],
            "sigma0": reference["sigma0"],
            "redundancy_sum": reference["redundancy_sum"],
        },
        "note": (
            "PASS means the native and independent calculations agree within the "
            "listed tolerances. REVIEW never alters original observations or results."
        ),
    }


def reference_data_snooping(
    *,
    points: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    threshold: float = 3.0,
    max_removals: int = 3,
    max_iterations: int = 20,
    tolerance: float = 1e-7,
) -> dict[str, Any]:
    """Identify gross-error review candidates without changing survey evidence."""

    threshold_value = _finite("Threshold", threshold)
    if threshold_value <= 0:
        raise ValueError("Threshold must be positive.")
    if int(max_removals) < 0:
        raise ValueError("max_removals cannot be negative.")

    original = list(observations)
    active = list(range(len(original)))
    removed: list[int] = []
    history: list[dict[str, Any]] = []
    stopped_reason = "threshold_satisfied"
    final_result: dict[str, Any] | None = None

    while active:
        try:
            result = reference_adjust_control_network(
                points=points,
                observations=[original[index] for index in active],
                max_iterations=max_iterations,
                tolerance=tolerance,
                robust=False,
                review_threshold=threshold_value,
            )
        except (ValueError, np.linalg.LinAlgError):
            stopped_reason = "insufficient_geometry"
            break

        final_result = result
        if int(result["degrees_of_freedom"]) <= 0:
            stopped_reason = "insufficient_redundancy"
            break

        candidates = [
            (local_index, row)
            for local_index, row in enumerate(result["observations"])
            if row.get("standardized_residual") is not None
        ]
        if not candidates:
            stopped_reason = "insufficient_redundancy"
            break

        local_index, worst = max(
            candidates,
            key=lambda item: abs(float(item[1]["standardized_residual"])),
        )
        global_index = active[local_index]
        flagged = (
            abs(float(worst["standardized_residual"])) >= threshold_value
        )
        history.append(
            {
                "iteration": len(history) + 1,
                "observation_number": global_index + 1,
                "kind": worst["kind"],
                "from_id": worst["from_id"],
                "to_id": worst["to_id"],
                "target2_id": worst["target2_id"],
                "standardized_residual": worst["standardized_residual"],
                "redundancy": worst["redundancy"],
                "flagged": flagged,
                "recommended_for_removal": False,
            }
        )
        if not flagged:
            stopped_reason = "threshold_satisfied"
            break
        if len(removed) >= int(max_removals):
            stopped_reason = "max_removals"
            break

        candidate_active = active.copy()
        candidate_active.pop(local_index)
        try:
            candidate_result = reference_adjust_control_network(
                points=points,
                observations=[original[index] for index in candidate_active],
                max_iterations=max_iterations,
                tolerance=tolerance,
                robust=False,
                review_threshold=threshold_value,
            )
        except (ValueError, np.linalg.LinAlgError):
            stopped_reason = "insufficient_geometry"
            break
        if int(candidate_result["degrees_of_freedom"]) <= 0:
            stopped_reason = "insufficient_redundancy"
            break

        history[-1]["recommended_for_removal"] = True
        active = candidate_active
        removed.append(global_index)

    return {
        "engine": "pysurveying_reference",
        "threshold": threshold_value,
        "max_removals": int(max_removals),
        "removed_indices": removed,
        "removed_observation_numbers": [index + 1 for index in removed],
        "active_indices": active,
        "history": history,
        "stopped_reason": stopped_reason,
        "converged": stopped_reason == "threshold_satisfied",
        "final_result": final_result,
        "note": (
            "Data snooping identifies review candidates only. SurveySync does not "
            "delete or modify original observations automatically."
        ),
    }
