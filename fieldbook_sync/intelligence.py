from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Iterable, Sequence

from .models import DipStatus, NetworkEdge, OcrCandidate, ResultRecord


def _angle_delta(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)




def _connected_point_candidate(raw: str | None) -> str:
    """Normalize a handwritten explicit destination such as ``to 3394``.

    The AI schema only places destination references in connected_point_raw, so this
    deliberately performs light syntax cleanup rather than fuzzy matching.
    """
    text=str(raw or "").strip()
    if not text:
        return ""
    match=re.search(r"(?:\bto\b|\bpoint\b|\bpt\b|#)\s*[:=#-]?\s*([A-Za-z0-9][A-Za-z0-9_.-]*)",text,re.I)
    if match:
        return match.group(1).strip()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*",text):
        return text
    return ""

def azimuth_between(e1: float, n1: float, e2: float, n2: float) -> float:
    """Survey azimuth: clockwise from north."""
    return math.degrees(math.atan2(e2 - e1, n2 - n1)) % 360.0


def calculate_smart_confidence(result: ResultRecord, ocr_candidates: Sequence[OcrCandidate] = ()) -> tuple[float, list[str]]:
    """Deterministic confidence score; never relies solely on a model's self-rating."""
    score = 0
    factors: list[str] = []
    exact_ocr = any(c.point_id == result.point_id and c.exact_match for c in ocr_candidates)
    if exact_ocr:
        score += 30; factors.append("Exact PointID located by local OCR (+30)")
    elif result.evidence_records:
        score += 18; factors.append("PointID present in AI evidence (+18)")

    agreements = [e.model_agreement for e in result.evidence_records if e.model_agreement is not None]
    if agreements and all(agreements):
        score += 25; factors.append("Independent engines agree (+25)")
    elif any(a is False for a in agreements):
        score -= 25; factors.append("Independent engines disagree (-25)")

    semantic_status = result.dip_status if result.dip_status != DipStatus.NOT_FOUND or result.status == DipStatus.NOT_FOUND else result.status
    if semantic_status == DipStatus.YES and any(p.dip is not None for p in result.pipes):
        score += 15; factors.append("Dip measurement present (+15)")
    elif semantic_status == DipStatus.NO and any(e.basis.value == "EXPLICIT_NO" for e in result.evidence_records):
        score += 15; factors.append("Explicit NOT DIPPED evidence (+15)")
    elif semantic_status == DipStatus.CNA and any(e.basis.value == "EXPLICIT_CNA" for e in result.evidence_records):
        score += 15; factors.append("Explicit CNA / Could Not Access evidence (+15)")
    elif semantic_status == DipStatus.CNL and any(e.basis.value == "EXPLICIT_CNL" for e in result.evidence_records):
        score += 15; factors.append("Explicit CNL / Could Not Locate evidence (+15)")

    if any(p.diameter_in is not None for p in result.pipes):
        score += 10; factors.append("Pipe diameter recognized (+10)")
    if any(p.azimuth_deg is not None for p in result.pipes):
        score += 10; factors.append("Pipe azimuth recognized (+10)")
    if result.code:
        score += 10; factors.append("Known survey structure code (+10)")
    if result.manually_overridden or result.review_state.value in {"ACCEPTED", "EDITED"}:
        score = max(score, 95); factors.append("Human reviewed/accepted (minimum 95)")
    if result.qa_needs_review:
        score = min(score, 79); factors.append("Detailed QA review caps confidence at 79")
    if not result.evidence_records:
        score = min(score, 25); factors.append("No field-book PointID match caps confidence at 25")
    return max(0.0, min(100.0, float(score))), factors


def apply_survey_qc(
    results: Sequence[ResultRecord],
    *,
    elevation_is_rim: bool = False,
    min_dip: float = 0.05,
    max_dip: float = 80.0,
    max_diameter_in: float = 144.0,
) -> None:
    for r in results:
        flags: list[str] = []
        for idx, p in enumerate(r.pipes, start=1):
            p.qc_flags = []
            if p.dip is not None:
                if p.dip < min_dip:
                    p.qc_flags.append(f"Pipe {idx}: dip {p.dip:g} is below expected minimum {min_dip:g}.")
                if p.dip > max_dip:
                    p.qc_flags.append(f"Pipe {idx}: dip {p.dip:g} exceeds expected maximum {max_dip:g}.")
                if elevation_is_rim and r.elevation is not None:
                    p.invert_elevation = r.elevation - p.dip
                    if p.invert_elevation > r.elevation:
                        p.qc_flags.append(f"Pipe {idx}: calculated invert is above the structure elevation.")
                else:
                    p.invert_elevation = None
            else:
                p.invert_elevation = None
            if p.diameter_in is not None:
                if p.diameter_in <= 0:
                    p.qc_flags.append(f"Pipe {idx}: diameter must be positive.")
                elif p.diameter_in > max_diameter_in:
                    p.qc_flags.append(f"Pipe {idx}: diameter {p.diameter_in:g}\" exceeds QC threshold {max_diameter_in:g}\".")
            if p.azimuth_deg is not None and not (0 <= p.azimuth_deg < 360):
                p.qc_flags.append(f"Pipe {idx}: azimuth must be between 0° and 360°.")
            if p.leader_direction_deg is not None and not (0 <= p.leader_direction_deg < 360):
                p.qc_flags.append(f"Pipe {idx}: visual leader direction must be between 0° and 360°.")
            if p.azimuth_deg is not None and p.leader_direction_deg is not None:
                visual_error=_angle_delta(p.azimuth_deg,p.leader_direction_deg)
                if visual_error > 35.0:
                    p.qc_flags.append(
                        f"Pipe {idx}: written azimuth and field-note leader direction disagree by {visual_error:.1f}°. Review the sketch association."
                    )
            flags.extend(p.qc_flags)
        r.qc_flags = flags


def infer_network(
    results: Sequence[ResultRecord],
    *,
    max_distance: float = 1500.0,
    max_bearing_error: float = 25.0,
    reciprocal_tolerance: float = 25.0,
) -> list[NetworkEdge]:
    """Build reviewable utility connectivity without silently changing field evidence.

    v9.1.3 gives an explicit handwritten destination (for example ``to 3394``)
    precedence over geometric inference.  Coordinates, the written azimuth and the
    BRT sketch leader direction are then used only as independent QC checks.  Pipes
    without an explicit destination retain the existing nearby-geometry suggestion
    workflow.
    """
    edges: list[NetworkEdge] = []
    used_pairs: set[tuple[str, int, str]] = set()
    by_id={str(r.point_id):r for r in results}
    by_fold={str(r.point_id).casefold():r for r in results}

    # Pass 1: explicit field-note topology. Never replace this with a nearest-point guess.
    explicit_pipe_keys: set[tuple[str,int]] = set()
    for src in results:
        for pi, pipe in enumerate(src.pipes, start=1):
            candidate=_connected_point_candidate(pipe.connected_point_raw)
            if not candidate:
                continue
            explicit_pipe_keys.add((src.point_id,pi))
            dst=by_id.get(candidate) or by_fold.get(candidate.casefold())
            if dst is None:
                pipe.qc_flags.append(f"Pipe {pi}: handwritten destination '{candidate}' is not a loaded survey structure.")
                continue
            if dst.point_id == src.point_id:
                pipe.qc_flags.append(f"Pipe {pi}: handwritten destination points back to the same structure; review the field note.")
                continue

            dist=None; bearing=None; bearing_err=None; leader_err=None
            reciprocal_best=None; reciprocal_pipe_index=None; expected_reverse=None
            if src.easting is not None and src.northing is not None and dst.easting is not None and dst.northing is not None:
                sx,sy=float(src.easting),float(src.northing)
                dx,dy=float(dst.easting),float(dst.northing)
                dist=math.hypot(dx-sx,dy-sy)
                bearing=azimuth_between(sx,sy,dx,dy)
                expected_reverse=(bearing+180.0)%360.0
                if pipe.azimuth_deg is not None:
                    bearing_err=_angle_delta(pipe.azimuth_deg,bearing)
                if pipe.leader_direction_deg is not None:
                    leader_err=_angle_delta(pipe.leader_direction_deg,bearing)
                for dpi,dp in enumerate(dst.pipes,start=1):
                    reverse_value=dp.azimuth_deg if dp.azimuth_deg is not None else dp.leader_direction_deg
                    if reverse_value is None:
                        continue
                    err=_angle_delta(reverse_value,expected_reverse)
                    if reciprocal_best is None or err < reciprocal_best:
                        reciprocal_best=err; reciprocal_pipe_index=dpi

            conflicts=[]
            if bearing_err is not None and bearing_err > max_bearing_error:
                conflicts.append(f"written azimuth differs from coordinate bearing by {bearing_err:.1f}°")
            if leader_err is not None and leader_err > max_bearing_error:
                conflicts.append(f"drawn leader differs from coordinate bearing by {leader_err:.1f}°")
            if reciprocal_best is not None and reciprocal_best > reciprocal_tolerance:
                conflicts.append(f"reciprocal pipe differs by {reciprocal_best:.1f}°")
            if dist is not None and dist > max_distance:
                # An explicit field note is still retained; distance is a QC warning, not a deletion rule.
                conflicts.append(f"referenced structure is {dist:.1f} project units away (QC limit {max_distance:g})")

            status="REVIEW" if conflicts else "STRONG"
            score=65.0 if conflicts else (95.0 if bearing is not None else 85.0)
            edge=NetworkEdge(
                from_point=src.point_id,to_point=dst.point_id,from_pipe_index=pi,
                to_pipe_index=reciprocal_pipe_index,distance=round(dist,3) if dist is not None else None,
                azimuth_from=pipe.azimuth_deg,
                azimuth_to_expected=round(expected_reverse,3) if expected_reverse is not None else None,
                reciprocal_error_deg=round(reciprocal_best,3) if reciprocal_best is not None else None,
                bearing_error_deg=round(bearing_err,3) if bearing_err is not None else None,
                leader_error_deg=round(leader_err,3) if leader_err is not None else None,
                score=score,status=status,
                notes=(
                    "Explicit handwritten field-note destination reference; coordinate, written-azimuth and sketch-leader checks agree."
                    if not conflicts else
                    "Explicit handwritten destination retained, but QC review is required: " + "; ".join(conflicts) + "."
                ),
            )
            key=(edge.from_point,edge.from_pipe_index,edge.to_point)
            if key not in used_pairs:
                used_pairs.add(key); edges.append(edge)
            pipe.connected_point_id=dst.point_id; pipe.connection_score=edge.score
            if conflicts:
                pipe.qc_flags.append("Explicit destination conflicts with independent geometry: " + "; ".join(conflicts) + ".")

    # Pass 2: geometry suggestion only when no explicit destination was written.
    usable=[r for r in results if r.easting is not None and r.northing is not None]
    if not usable:
        return edges
    cell_size=max(float(max_distance),1e-9)
    grid: dict[tuple[int,int],list[ResultRecord]]={}
    for result in usable:
        key=(math.floor(float(result.easting)/cell_size),math.floor(float(result.northing)/cell_size))
        grid.setdefault(key,[]).append(result)

    for src in usable:
        sx=float(src.easting); sy=float(src.northing)
        cell_x=math.floor(sx/cell_size); cell_y=math.floor(sy/cell_size)
        nearby=[]
        for ox in (-1,0,1):
            for oy in (-1,0,1):
                nearby.extend(grid.get((cell_x+ox,cell_y+oy),()))
        for pi,pipe in enumerate(src.pipes,start=1):
            if (src.point_id,pi) in explicit_pipe_keys:
                continue
            direction=pipe.azimuth_deg if pipe.azimuth_deg is not None else pipe.leader_direction_deg
            if direction is None:
                continue
            best: NetworkEdge|None=None
            for dst in nearby:
                if dst.point_id==src.point_id:
                    continue
                dx=float(dst.easting)-sx; dy=float(dst.northing)-sy
                dist=math.hypot(dx,dy)
                if dist<=0 or dist>max_distance:
                    continue
                bearing=azimuth_between(sx,sy,float(dst.easting),float(dst.northing))
                bearing_err=_angle_delta(direction,bearing)
                if bearing_err>max_bearing_error:
                    continue
                reciprocal_best=None; reciprocal_pipe_index=None
                expected_reverse=(bearing+180.0)%360.0
                for dpi,dp in enumerate(dst.pipes,start=1):
                    reverse_value=dp.azimuth_deg if dp.azimuth_deg is not None else dp.leader_direction_deg
                    if reverse_value is None:
                        continue
                    err=_angle_delta(reverse_value,expected_reverse)
                    if reciprocal_best is None or err<reciprocal_best:
                        reciprocal_best=err; reciprocal_pipe_index=dpi
                direction_score=max(0.0,1.0-bearing_err/max_bearing_error)
                reciprocal_score=0.0 if reciprocal_best is None else max(0.0,1.0-reciprocal_best/max(reciprocal_tolerance,1e-6))
                distance_score=max(0.0,1.0-dist/max_distance)
                score=100.0*(0.52*direction_score+0.33*reciprocal_score+0.15*distance_score)
                status="STRONG" if score>=78 and reciprocal_best is not None and reciprocal_best<=reciprocal_tolerance else "SUGGESTED"
                if reciprocal_best is not None and reciprocal_best>reciprocal_tolerance:
                    status="REVIEW"
                edge=NetworkEdge(
                    from_point=src.point_id,to_point=dst.point_id,from_pipe_index=pi,to_pipe_index=reciprocal_pipe_index,
                    distance=round(dist,3),azimuth_from=pipe.azimuth_deg,azimuth_to_expected=round(expected_reverse,3),
                    reciprocal_error_deg=round(reciprocal_best,3) if reciprocal_best is not None else None,
                    bearing_error_deg=round(_angle_delta(pipe.azimuth_deg,bearing),3) if pipe.azimuth_deg is not None else None,
                    leader_error_deg=round(_angle_delta(pipe.leader_direction_deg,bearing),3) if pipe.leader_direction_deg is not None else None,
                    score=round(score,1),status=status,
                    notes="Suggested from survey coordinates and pipe direction agreement; verify before using as authoritative connectivity.",
                )
                if best is None or edge.score>best.score:
                    best=edge
            if best:
                key=(best.from_point,best.from_pipe_index,best.to_point)
                if key not in used_pairs:
                    used_pairs.add(key); edges.append(best)
                    pipe.connected_point_id=best.to_point; pipe.connection_score=best.score
                    if best.status=="REVIEW":
                        pipe.qc_flags.append("Suggested connection has weak reciprocal direction agreement.")
    return edges


def refresh_result_intelligence(
    results: Sequence[ResultRecord],
    ocr_candidates: Sequence[OcrCandidate],
    *,
    elevation_is_rim: bool = False,
) -> None:
    """Refresh per-result QC/confidence without performing network inference."""
    apply_survey_qc(results, elevation_is_rim=elevation_is_rim)
    for result in results:
        score, factors = calculate_smart_confidence(result, ocr_candidates)
        result.smart_confidence = score
        result.confidence_factors = factors

def refresh_intelligence(
    results: Sequence[ResultRecord],
    ocr_candidates: Sequence[OcrCandidate],
    *,
    elevation_is_rim: bool = False,
    network_max_distance: float = 1500.0,
    network_bearing_tolerance: float = 25.0,
) -> list[NetworkEdge]:
    refresh_result_intelligence(results, ocr_candidates, elevation_is_rim=elevation_is_rim)
    return infer_network(
        results,
        max_distance=network_max_distance,
        max_bearing_error=network_bearing_tolerance,
        reciprocal_tolerance=network_bearing_tolerance,
    )
