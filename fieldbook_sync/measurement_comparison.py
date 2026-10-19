"""Compare explicit OCR pipe records without pooling fields across different pipes.

Text agreement is deliberately separate from a measured text/leader/structure relation.
No part of this module can establish a spatial association or create a survey PointID.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MeasurementComparison:
    numerical_agreement: bool | None
    pipe_record_agreement: bool | None
    agreement: bool | None
    summary: str


def observation_from_text(text: str) -> dict[str, Any] | None:
    """Return one explicit record; a block with multiple field values is not one pipe.

    The established DIP/depth versus ductile-iron disambiguation is shared with the
    value checker. Newlines and semicolons are boundaries, never grounds for merging
    a depth in one region with a diameter in another region.
    """
    from .ocr_local import _comparison_measurements, _numeric_hits, _dedupe_numbers, _NUM

    text = str(text or "")[:12000]
    dips, diameters, azimuths = _comparison_measurements(text)
    dips = _dedupe_numbers(dips + _numeric_hits([rf"\bD\s*[:=#]\s*{_NUM}"], text))
    if any(len(values) > 1 for values in (dips, diameters, azimuths)):
        return None
    materials = set(re.findall(r"\b(?:RCP|PVC|CMP|HDPE|VCP)\b", text, flags=re.I))
    materials = {value.upper() for value in materials}
    # Decimal value-first DIP is a depth label, not a material. Only the established
    # unambiguous integer/inch material notation may contribute a DIP material.
    if re.search(r'(?<![\d.])\d{1,3}\s*(?:["”]|in(?:ch(?:es)?)?\s*)?\s+DIP\b', text, re.I):
        materials.add("DIP")
    if len(materials) > 1:
        return None
    result = {}
    for field, values in (("dip", dips), ("diameter_in", diameters), ("azimuth_deg", azimuths)):
        if values:
            result[field] = values[0]
    if materials:
        result["material"] = next(iter(materials))
    return result or None


def observation_matches_pipe(
    observation: dict[str, Any], pipe: Any, *, complete: bool = False
) -> bool:
    """Compare only observed fields; ``complete`` additionally requires every pipe field.

    Tolerances match the existing conservative OCR checker. Circular azimuth comparison
    handles 359/0 correctly. Non-finite values never agree.
    """
    tolerances = {"dip": 0.08, "diameter_in": 0.75, "azimuth_deg": 3.0}
    for field in (*tolerances, "material"):
        value = getattr(pipe, field, None)
        if complete and value is not None and str(value).strip() and field not in observation:
            return False
        if field not in observation:
            continue
        observed = observation[field]
        if value is None:
            return False
        if field == "material":
            if str(observed).strip().casefold() != str(value).strip().casefold():
                return False
            continue
        try:
            left, right = float(observed), float(value)
        except (ValueError, TypeError, OverflowError):
            return False
        if not math.isfinite(left) or not math.isfinite(right):
            return False
        difference = (
            abs((left - right + 180) % 360 - 180) if field == "azimuth_deg" else abs(left - right)
        )
        if difference > tolerances[field] + 1e-9:
            return False
    return bool(observation)


def _has_distinct_assignment(options: list[list[int]], size: int) -> bool:
    """Bounded bipartite matching preserves multiplicity without factorial searches."""
    owner = [-1] * size

    def assign(row: int, visited: set[int]) -> bool:
        for column in options[row]:
            if column in visited:
                continue
            visited.add(column)
            if owner[column] == -1 or assign(owner[column], visited):
                owner[column] = row
                return True
        return False

    return all(assign(row, set()) for row in range(len(options)))


def compare_measurement_records(text: str, evidence: Any) -> MeasurementComparison:
    from .ocr_local import _compare_ocr_values

    # Bounded input protects the regex and matching work on imported/cache payloads.
    if len(text or "") > 12000 or len(evidence.pipes or []) > 64:
        return MeasurementComparison(
            None, None, None, "OCR comparison limit reached; review the original page."
        )
    values_agree, summary = _compare_ocr_values(text, evidence)
    pipes = evidence.pipes or []
    segments = re.split(r"[;\n\r]+", text or "")
    if len(segments) > 128:
        return MeasurementComparison(
            values_agree,
            None,
            False if values_agree is False else None,
            summary + ". Too many text segments for a bounded pipe comparison.",
        )
    observations = []
    uncertain_block = False
    for segment in segments:
        observation = observation_from_text(segment)
        if observation:
            observations.append(observation)
        else:
            # Multiple values in a single block must not be mistaken for no values.
            from .ocr_local import _comparison_measurements

            if any(_comparison_measurements(segment)):
                uncertain_block = True
    if len(pipes) == 1:
        # Multiline annotations for a single extracted pipe can expose complementary
        # fields. They must not be treated as multiple complete pipes just because OCR
        # inserted a line break. Spatial binding still has a separate review gate.
        combined = observation_from_text(text)
        records_agree = observation_matches_pipe(combined, pipes[0]) if combined else None
    elif not observations or uncertain_block:
        records_agree = None
    else:
        records = [observation for observation in observations if len(observation) >= 2]
        options = [
            [i for i, pipe in enumerate(pipes) if observation_matches_pipe(observation, pipe)]
            for observation in records
        ]
        if not pipes or (records and not _has_distinct_assignment(options, len(pipes))):
            records_agree = False
        elif len(records) == len(pipes) and len(records) == len(observations):
            records_agree = True
        else:
            records_agree = None
    if values_agree is False or records_agree is False:
        agreement = False
    elif len(pipes) > 1 and records_agree is not True:
        agreement = None
    else:
        agreement = values_agree
    if records_agree is False:
        summary += ". Pipe records disagree: values cannot be assigned together to distinct extracted pipes."
    elif records_agree is True:
        summary += ". Explicit pipe records agree; their connection to drawn leaders still requires spatial review."
    elif len(pipes) > 1:
        summary += ". Page-wide value agreement does not establish individual pipe records."
    return MeasurementComparison(values_agree, records_agree, agreement, summary)
