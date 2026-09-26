"""SurveySync-native weighted least-squares adjustment for small 2D control networks.

The implementation is intentionally separate from Ronald's validated three-shot
control workflow. Numerical behavior is regression-checked against independent
MIT-licensed pySurveying reference fixtures, but no pySurveying source is copied.
"""

from __future__ import annotations

import math

import numpy as np

_ELLIPSE_95_SCALE = 2.447746830680816


def _finite(name: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite.")
    return number


def _normalize_deg(value: float) -> float:
    return float(value) % 360.0


def _angle_difference(calculated: float, observed: float) -> float:
    return (float(calculated) - float(observed) + 180.0) % 360.0 - 180.0


def _azimuth_deg(start: tuple[float, float], end: tuple[float, float]) -> float:
    dn = end[0] - start[0]
    de = end[1] - start[1]
    if math.hypot(dn, de) <= 1e-15:
        raise ValueError("Angular observation contains coincident points.")
    return _normalize_deg(math.degrees(math.atan2(de, dn)))


def _distance(start: tuple[float, float], end: tuple[float, float]) -> float:
    return math.hypot(end[0] - start[0], end[1] - start[1])


def _huber_weights(residuals: np.ndarray, k: float) -> np.ndarray:
    absolute = np.abs(residuals)
    weights = np.ones_like(absolute)
    mask = absolute > k
    weights[mask] = k / absolute[mask]
    return weights


def adjust_control_network(
    *,
    points: list[dict[str, object]],
    observations: list[dict[str, object]],
    max_iterations: int = 20,
    tolerance: float = 1e-7,
    robust: bool = False,
    huber_k: float = 1.5,
    review_threshold: float = 3.0,
) -> dict[str, object]:
    """Adjust a constrained 2D network using weighted nonlinear least squares.

    Supported observation kinds are distance, azimuth, direction, and angle.
    Distance sigma uses project linear units. Angular sigma uses degrees.
    Direction observations solve one orientation unknown per occupied station.
    """

    if not points:
        raise ValueError("At least one network point is required.")
    if not observations:
        raise ValueError("At least one network observation is required.")
    if int(max_iterations) < 1 or int(max_iterations) > 100:
        raise ValueError("max_iterations must be between 1 and 100.")
    tolerance_value = _finite("Tolerance", tolerance)
    if tolerance_value <= 0:
        raise ValueError("Tolerance must be positive.")
    huber_value = _finite("Huber k", huber_k)
    if huber_value <= 0:
        raise ValueError("Huber k must be positive.")
    review_value = _finite("Review threshold", review_threshold)
    if review_value <= 0:
        raise ValueError("Review threshold must be positive.")

    point_map: dict[str, dict[str, object]] = {}
    point_order: list[str] = []
    for index, row in enumerate(points, start=1):
        point_id = str(row.get("point_id") or "").strip()
        if not point_id:
            raise ValueError(f"Point {index} is missing point_id.")
        if point_id in point_map:
            raise ValueError(f"Duplicate network point_id: {point_id}")
        point_map[point_id] = {
            "point_id": point_id,
            "northing": _finite(f"{point_id} northing", float(row["northing"])),
            "easting": _finite(f"{point_id} easting", float(row["easting"])),
            "fixed": bool(row.get("fixed", False)),
        }
        point_order.append(point_id)

    if not any(bool(point_map[name]["fixed"]) for name in point_order):
        raise ValueError("At least one fixed control point is required.")

    normalized_observations: list[dict[str, object]] = []
    supported = {"distance", "azimuth", "direction", "angle"}
    for index, row in enumerate(observations, start=1):
        kind = str(row.get("kind") or "").strip().lower()
        if kind not in supported:
            raise ValueError(f"Observation {index} has unsupported kind: {kind or '(blank)'}")
        from_id = str(row.get("from_id") or "").strip()
        to_id = str(row.get("to_id") or "").strip()
        target2_id = str(row.get("target2_id") or "").strip() or None
        for point_id in (from_id, to_id):
            if point_id not in point_map:
                raise ValueError(f"Observation {index} references unknown point {point_id!r}.")
        if kind == "angle":
            if not target2_id:
                raise ValueError(f"Angle observation {index} requires target2_id.")
            if target2_id not in point_map:
                raise ValueError(
                    f"Observation {index} references unknown target2 point {target2_id!r}."
                )
        sigma = _finite(f"Observation {index} sigma", float(row["sigma"]))
        if sigma <= 0:
            raise ValueError(f"Observation {index} sigma must be positive.")
        normalized_observations.append(
            {
                "kind": kind,
                "from_id": from_id,
                "to_id": to_id,
                "target2_id": target2_id,
                "value": _finite(f"Observation {index} value", float(row["value"])),
                "sigma": sigma,
            }
        )

    unknown_points = [name for name in point_order if not bool(point_map[name]["fixed"])]
    if not unknown_points:
        raise ValueError("Network contains no adjustable points.")

    coordinate_index: dict[str, tuple[int, int]] = {}
    values: list[float] = []
    for name in unknown_points:
        coordinate_index[name] = (len(values), len(values) + 1)
        values.extend(
            [
                float(point_map[name]["northing"]),
                float(point_map[name]["easting"]),
            ]
        )
    coordinate_parameter_count = len(values)

    direction_stations = sorted(
        {
            str(row["from_id"])
            for row in normalized_observations
            if row["kind"] == "direction"
        }
    )

    def coordinates(current: np.ndarray, point_id: str) -> tuple[float, float]:
        point = point_map[point_id]
        if bool(point["fixed"]):
            return float(point["northing"]), float(point["easting"])
        n_index, e_index = coordinate_index[point_id]
        return float(current[n_index]), float(current[e_index])

    base_values = np.asarray(values, dtype=float)
    orientation_index: dict[str, int] = {}
    orientation_values: list[float] = []
    for station in direction_stations:
        first = next(
            row
            for row in normalized_observations
            if row["kind"] == "direction" and row["from_id"] == station
        )
        predicted = _azimuth_deg(
            coordinates(base_values, station),
            coordinates(base_values, str(first["to_id"])),
        )
        orientation_index[station] = coordinate_parameter_count + len(orientation_values)
        orientation_values.append(_normalize_deg(predicted - float(first["value"])))

    current = np.concatenate((base_values, np.asarray(orientation_values, dtype=float)))

    def calculated_values(state: np.ndarray) -> list[float]:
        calculated: list[float] = []
        for row in normalized_observations:
            station = coordinates(state, str(row["from_id"]))
            target = coordinates(state, str(row["to_id"]))
            kind = str(row["kind"])
            if kind == "distance":
                calculated.append(_distance(station, target))
            elif kind == "azimuth":
                calculated.append(_azimuth_deg(station, target))
            elif kind == "direction":
                orientation = state[orientation_index[str(row["from_id"])]]
                calculated.append(_normalize_deg(_azimuth_deg(station, target) - orientation))
            else:
                foresight = coordinates(state, str(row["target2_id"]))
                backsight_azimuth = _azimuth_deg(station, target)
                foresight_azimuth = _azimuth_deg(station, foresight)
                calculated.append(_normalize_deg(foresight_azimuth - backsight_azimuth))
        return calculated

    def residual_vector(state: np.ndarray) -> np.ndarray:
        calculated = calculated_values(state)
        rows: list[float] = []
        for calc, row in zip(calculated, normalized_observations, strict=True):
            observed = float(row["value"])
            sigma = float(row["sigma"])
            if row["kind"] == "distance":
                residual = calc - observed
            else:
                residual = _angle_difference(calc, observed)
            rows.append(residual / sigma)
        return np.asarray(rows, dtype=float)

    def numerical_jacobian(state: np.ndarray) -> np.ndarray:
        base = residual_vector(state)
        matrix = np.empty((base.size, state.size), dtype=float)
        for column in range(state.size):
            step = 1e-5 if column < coordinate_parameter_count else 1e-6
            plus = state.copy()
            minus = state.copy()
            plus[column] += step
            minus[column] -= step
            matrix[:, column] = (
                residual_vector(plus) - residual_vector(minus)
            ) / (2.0 * step)
        return matrix

    converged = False
    final_weights = np.ones(len(normalized_observations), dtype=float)
    iteration = 0
    for iteration in range(1, int(max_iterations) + 1):
        residuals = residual_vector(current)
        jacobian = numerical_jacobian(current)
        final_weights = (
            _huber_weights(residuals, huber_value)
            if robust
            else np.ones_like(residuals)
        )
        sqrt_weights = np.sqrt(final_weights)
        weighted_jacobian = jacobian * sqrt_weights[:, None]
        weighted_residuals = residuals * sqrt_weights
        correction = -np.linalg.pinv(weighted_jacobian) @ weighted_residuals
        current = current + correction
        for station in direction_stations:
            index = orientation_index[station]
            current[index] = _normalize_deg(current[index])
        if float(np.max(np.abs(correction))) < tolerance_value:
            converged = True
            break

    residuals = residual_vector(current)
    jacobian = numerical_jacobian(current)
    final_weights = (
        _huber_weights(residuals, huber_value) if robust else np.ones_like(residuals)
    )
    sqrt_weights = np.sqrt(final_weights)
    weighted_jacobian = jacobian * sqrt_weights[:, None]
    rank = int(np.linalg.matrix_rank(weighted_jacobian))
    parameter_count = int(current.size)
    if rank < parameter_count:
        raise ValueError(
            "Network is rank deficient. Add independent control/observations or "
            "improve the starting geometry."
        )

    dof = int(len(normalized_observations) - rank)
    weighted_ss = float(np.sum(final_weights * residuals**2))
    sigma0 = math.sqrt(weighted_ss / dof) if dof > 0 else None

    weight_matrix = np.diag(final_weights)
    normal = jacobian.T @ weight_matrix @ jacobian
    qxx = np.linalg.pinv(normal)
    covariance = qxx if sigma0 is None else qxx * sigma0**2
    qll = np.linalg.pinv(weight_matrix)
    qvv = qll - jacobian @ qxx @ jacobian.T
    qvv = (qvv + qvv.T) / 2.0
    redundancy = np.clip(np.diag(qvv @ weight_matrix), 0.0, 1.0)

    calculated = calculated_values(current)
    observation_rows: list[dict[str, object]] = []
    review_count = 0
    for index, (row, calc, normalized_residual, red, robust_weight) in enumerate(
        zip(
            normalized_observations,
            calculated,
            residuals,
            redundancy,
            final_weights,
            strict=True,
        ),
        start=1,
    ):
        sigma = float(row["sigma"])
        raw_residual = float(normalized_residual) * sigma
        if red > 1e-12:
            scale = (sigma0 if sigma0 is not None and sigma0 > 1e-12 else 1.0)
            standardized = float(normalized_residual) / (scale * math.sqrt(float(red)))
        else:
            standardized = None
        needs_review = standardized is not None and abs(standardized) >= review_value
        if needs_review:
            review_count += 1
        observation_rows.append(
            {
                "index": index,
                "kind": row["kind"],
                "from_id": row["from_id"],
                "to_id": row["to_id"],
                "target2_id": row["target2_id"],
                "observed": row["value"],
                "calculated": calc,
                "residual": raw_residual,
                "residual_unit": (
                    "project_linear_units" if row["kind"] == "distance" else "degrees"
                ),
                "sigma": sigma,
                "redundancy": float(red),
                "standardized_residual": standardized,
                "robust_weight": float(robust_weight),
                "status": "REVIEW" if needs_review else "OK",
            }
        )

    adjusted_points: list[dict[str, object]] = []
    for name in point_order:
        initial_n = float(point_map[name]["northing"])
        initial_e = float(point_map[name]["easting"])
        fixed = bool(point_map[name]["fixed"])
        adjusted_n, adjusted_e = coordinates(current, name)
        if fixed:
            sigma_n = 0.0
            sigma_e = 0.0
            correlation = 0.0
            semi_major = 0.0
            semi_minor = 0.0
            ellipse_azimuth = 0.0
        else:
            n_index, e_index = coordinate_index[name]
            block = covariance[np.ix_([n_index, e_index], [n_index, e_index])]
            sigma_n = math.sqrt(max(0.0, float(block[0, 0])))
            sigma_e = math.sqrt(max(0.0, float(block[1, 1])))
            denominator = sigma_n * sigma_e
            correlation = float(block[0, 1]) / denominator if denominator > 0 else 0.0
            eigenvalues, eigenvectors = np.linalg.eigh(block)
            order = np.argsort(eigenvalues)[::-1]
            major_value = max(0.0, float(eigenvalues[order[0]]))
            minor_value = max(0.0, float(eigenvalues[order[1]]))
            major_vector = eigenvectors[:, order[0]]
            semi_major = _ELLIPSE_95_SCALE * math.sqrt(major_value)
            semi_minor = _ELLIPSE_95_SCALE * math.sqrt(minor_value)
            ellipse_azimuth = (
                math.degrees(math.atan2(float(major_vector[1]), float(major_vector[0])))
                % 180.0
            )
        adjusted_points.append(
            {
                "point_id": name,
                "fixed": fixed,
                "initial_northing": initial_n,
                "initial_easting": initial_e,
                "northing": adjusted_n,
                "easting": adjusted_e,
                "shift_northing": adjusted_n - initial_n,
                "shift_easting": adjusted_e - initial_e,
                "horizontal_shift": math.hypot(
                    adjusted_n - initial_n,
                    adjusted_e - initial_e,
                ),
                "sigma_northing": sigma_n,
                "sigma_easting": sigma_e,
                "correlation_ne": correlation,
                "ellipse95_semi_major": semi_major,
                "ellipse95_semi_minor": semi_minor,
                "ellipse95_azimuth_deg": ellipse_azimuth,
            }
        )

    orientations = {
        station: float(current[index]) for station, index in orientation_index.items()
    }
    condition_number = float(np.linalg.cond(weighted_jacobian))
    return {
        "converged": converged,
        "iterations": iteration,
        "point_count": len(point_order),
        "adjusted_point_count": len(unknown_points),
        "observation_count": len(normalized_observations),
        "parameter_count": parameter_count,
        "rank": rank,
        "degrees_of_freedom": dof,
        "sigma0": sigma0,
        "condition_number": condition_number,
        "robust": bool(robust),
        "huber_k": huber_value,
        "review_threshold": review_value,
        "review_count": review_count,
        "redundancy_sum": float(np.sum(redundancy)),
        "points": adjusted_points,
        "orientations_deg": orientations,
        "observations": observation_rows,
        "quality_note": (
            "Residual/redundancy statistics use the final local linearization. "
            "Error ellipses are 95% 2D ellipses from the adjusted coordinate covariance. "
            "Flagged residuals require survey review; SurveySync does not auto-delete them."
        ),
    }
