"""Bounded, read-only DXF geometry review. Never repair or close source geometry."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from typing import Any

METERS = {
    "meters": 1.0,
    "international_feet": 0.3048,
    "us_survey_feet": 1200 / 3937,
    "inches": 0.0254,
    "millimeters": 0.001,
    "centimeters": 0.01,
}
MAX_ENTITIES = 10000
MAX_VERTICES = 150000
MAX_FINDINGS = 5000
MAX_PAIRS = 200000


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def xyz(value, scale):
    result = [float(v) * scale for v in value]
    if len(result) != 3 or not all(math.isfinite(v) and abs(v) <= 1e12 for v in result):
        raise ValueError("Invalid or out-of-range DXF coordinate.")
    return result


def read_drawing(path, drawing_units, project_units):
    """Read only modelspace; expand bounded INSERTs with parent provenance."""
    import ezdxf
    from ezdxf.path import make_path
    from ezdxf.math import Vec3
    from ezdxf import DXFError

    scale = METERS[drawing_units] / METERS[project_units]
    # Display chords only. Curve QA is explicitly approximate, endpoints are exact.
    flatness = 0.001 * 0.3048 / METERS[project_units]
    doc = ezdxf.readfile(path)
    entities: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    seen_count = vertices_count = 0
    source_counts = Counter(e.dxftype() for e in doc.modelspace())
    if sum(source_counts.values()) > MAX_ENTITIES:
        raise ValueError("Drawing exceeds 10,000 modelspace entities; split the drawing first.")

    def omit(identity, kind, reason):
        if len(omitted) >= MAX_FINDINGS:
            raise ValueError("Too many unsupported entities; no partial import retained.")
        omitted.append({"entity_id": identity, "type": kind, "reason": reason})

    def visit(e, identity, inherited="0", stack=()):
        nonlocal seen_count, vertices_count
        seen_count += 1
        if seen_count > MAX_ENTITIES:
            raise ValueError("Expanded blocks exceed 10,000 entities; no partial import retained.")
        kind = e.dxftype()
        layer = e.dxf.get("layer", "0")
        if layer == "0" and stack:
            layer = inherited
        if kind == "INSERT":
            name = e.dxf.name
            block = doc.blocks.get(name)
            if name in stack or len(stack) >= 12:
                omit(identity, kind, "Recursive block or nesting exceeds 12 levels.")
                return
            if block is None or block.block is None or block.block.is_xref:
                omit(identity, kind, "Missing block or external reference is not loaded.")
                return
            if e.has_extension_dict:
                omit(identity, kind, "Block extension data (including clipping) is not supported.")
                return
            if e.mcount > MAX_ENTITIES:
                raise ValueError("Block array exceeds entity limit.")
            instances = e.multi_insert() if e.mcount > 1 else [e]
            for index, instance in enumerate(instances):

                def skipped(child, reason):
                    omit(identity, child.dxftype(), "Block transform: " + reason)

                for j, child in enumerate(
                    instance.virtual_entities(skipped_entity_callback=skipped)
                ):
                    visit(child, f"{identity}/{index}/{j}", layer, (*stack, name))
                for j, attr in enumerate(instance.attribs):
                    visit(attr, f"{identity}/{index}/attr{j}", layer, (*stack, name))
            return
        base = {
            "entity_id": identity,
            "handle": identity.split("/")[0],
            "type": kind,
            "layer": layer,
            "block_path": list(stack),
            "closed": False,
            "curved": False,
            "text": "",
            "segments": [],
        }
        try:
            if kind in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF"):
                point = e.dxf.insert if kind == "MTEXT" else e.ocs().to_wcs(e.dxf.insert)
                base["points"] = [xyz(point, scale)]
                base["text"] = (e.plain_text() if kind in ("TEXT", "MTEXT") else e.dxf.text)[:4000]
                base["text_rotation"] = float(e.dxf.get("rotation", 0))
            elif kind == "POINT":
                base["points"] = [xyz(e.dxf.location, scale)]
            elif kind == "LINE":
                base["points"] = [xyz(e.dxf.start, scale), xyz(e.dxf.end, scale)]
                base["segments"] = [[base["points"][0], base["points"][1]]]
            elif kind in ("LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE"):
                if kind == "POLYLINE" and not (e.is_2d_polyline or e.is_3d_polyline):
                    omit(identity, kind, "Mesh/polyface POLYLINE is not linework.")
                    return
                if kind == "POLYLINE" and e.dxf.flags & 6:
                    omit(
                        identity,
                        kind,
                        "Curve-fit/spline-fit POLYLINE needs explicit CAD conversion.",
                    )
                    return
                if kind in ("LWPOLYLINE", "POLYLINE"):
                    base["closed"] = bool(e.closed if kind == "LWPOLYLINE" else e.is_closed)
                    raw = (
                        list(e.get_points("xyb"))
                        if kind == "LWPOLYLINE"
                        else [
                            (v.dxf.location.x, v.dxf.location.y, v.dxf.get("bulge", 0))
                            for v in e.vertices
                        ]
                    )
                    verts = (
                        list(e.vertices_in_wcs())
                        if kind == "LWPOLYLINE"
                        else list(e.points_in_wcs())
                    )
                    exact = [xyz(v, scale) for v in verts]
                    base["curved"] = any(
                        r[2] != 0
                        for r in raw[: len(raw) if base["closed"] else max(0, len(raw) - 1)]
                    )
                    for i in range(len(exact) if base["closed"] else max(0, len(exact) - 1)):
                        if raw[i][2] == 0:
                            base["segments"].append([exact[i], exact[(i + 1) % len(exact)]])
                    base["endpoints"] = [exact[0], exact[-1]] if exact else []
                    if not base["curved"]:
                        base["points"] = exact + ([exact[0]] if base["closed"] and exact else [])
                else:
                    base["curved"] = True
                    base["closed"] = kind == "CIRCLE" or (
                        kind == "ELLIPSE"
                        and math.isclose(
                            e.dxf.end_param - e.dxf.start_param, math.tau, abs_tol=1e-12
                        )
                    )
                if "points" not in base:
                    path_ = make_path(e)
                    # Bound the generator, including very large radii.
                    pts = []
                    for p in path_.flattening(flatness / scale, segments=8):
                        pts.append(xyz(Vec3(p), scale))
                        if len(pts) + vertices_count > MAX_VERTICES:
                            raise OverflowError("Drawing exceeds 150,000 display vertices.")
                    base["points"] = pts
                    if kind == "ARC":
                        base["points"][0] = xyz(e.start_point, scale)
                        base["points"][-1] = xyz(e.end_point, scale)
                    elif kind == "ELLIPSE":
                        exact_ends = list(e.vertices([e.dxf.start_param, e.dxf.end_param]))
                        base["points"][0] = xyz(exact_ends[0], scale)
                        base["points"][-1] = xyz(exact_ends[1], scale)
            else:
                omit(identity, kind, "Unsupported entity; no substitute geometry generated.")
                return
            if not base["points"]:
                omit(identity, kind, "Entity has no vertices.")
                return
            if "endpoints" not in base:
                base["endpoints"] = [base["points"][0], base["points"][-1]]
            vertices_count += len(base["points"])
            if vertices_count > MAX_VERTICES:
                raise OverflowError("Drawing exceeds 150,000 display vertices.")
            base["planar"] = (
                max(p[2] for p in base["points"]) - min(p[2] for p in base["points"]) <= 1e-9
            )
            entities.append(base)
        except (
            DXFError,
            TypeError,
            ValueError,
            ZeroDivisionError,
            AttributeError,
            IndexError,
        ) as exc:
            omit(identity, kind, str(exc)[:500])

    for i, e in enumerate(doc.modelspace()):
        visit(e, e.dxf.get("handle") or f"index-{i}")
    header_units = {
        1: "inches",
        2: "international_feet",
        4: "millimeters",
        5: "centimeters",
        6: "meters",
        21: "us_survey_feet",
    }.get(int(doc.header.get("$INSUNITS", 0)))
    unit_warning = (
        "DXF header units differ from your explicit selection. Verify the drawing scale before using measurements."
        if header_units and header_units != drawing_units
        else "DXF header units are absent/unsupported; explicit unit selection is authoritative."
        if not header_units
        else "DXF header and explicitly selected units agree."
    )
    layers = []
    for name in sorted({e["layer"] for e in entities}):
        layer = doc.layers.get(name)
        layers.append(
            {
                "name": name,
                "count": sum(e["layer"] == name for e in entities),
                "default_visible": not (layer.is_off() or layer.is_frozen()),
            }
        )
    return {
        "schema": 1,
        "reader": "ezdxf " + ezdxf.__version__,
        "dxf_version": doc.dxfversion,
        "header_insunits": int(doc.header.get("$INSUNITS", 0)),
        "unit_warning": unit_warning,
        "drawing_units": drawing_units,
        "project_units": project_units,
        "scale_to_project": scale,
        "curve_display_chord_tolerance": flatness,
        "entities": entities,
        "layers": layers,
        "unsupported": omitted,
        "modelspace_counts": dict(source_counts),
        "paper_layout_count": len(list(doc.layouts)) - 1,
        "notice": "Modelspace review only. Curves are approximated for display and intersection screening; original DXF is retained. Text is an anchor/label preview, not CAD typography. No geometry is changed.",
    }


def analyze(drawing, search_ft=1.0):
    """Plan-view screening; proximity is not proof of intended connectivity."""
    from shapely.geometry import LineString, Point
    from shapely import STRtree, __version__ as shapely_version
    from shapely.errors import GEOSException

    if not math.isfinite(search_ft) or not 0.1 <= search_ft <= 10:
        raise ValueError("Gap search must be between 0.10 and 10 international feet.")
    unit = METERS[drawing["project_units"]]
    threshold = 0.1 * 0.3048 / unit
    radius = search_ft * 0.3048 / unit
    issues: list[dict[str, Any]] = []
    segments, owners, endpoints, endpoint_owners = [], [], [], []
    duplicate: dict[tuple, str] = {}

    def add(kind, ids, message, value=None, approximate=False):
        if len(issues) >= MAX_FINDINGS:
            raise ValueError(
                "More than 5,000 findings; split the drawing. No partial QA result produced."
            )
        item = dict(
            kind=kind,
            entity_ids=list(dict.fromkeys(ids)),
            message=message,
            value=value,
            approximate=approximate,
        )
        item["issue_id"] = digest(item)
        issues.append(item)

    for e in drawing["entities"]:
        if len(e["points"]) < 2:
            continue
        eid = e["entity_id"]
        if not e["planar"]:
            add("nonplanar", [eid], "Nonplanar entity: plan-view geometry checks excluded.")
            continue
        for a, b in e["segments"]:
            if a == b:
                add("zero_length", [eid], "Exact repeated vertex / zero-length straight segment.")
                continue
            key = tuple(sorted((tuple(a), tuple(b))))
            if key in duplicate:
                add(
                    "duplicate_segment",
                    [duplicate[key], eid],
                    "Exact coincident straight segment, including reversed direction.",
                )
            else:
                duplicate[key] = eid
        try:
            line = LineString([p[:2] for p in e["points"]])
            if not line.is_simple and line.length:
                add(
                    "self_intersection",
                    [eid],
                    "Entity crosses or touches itself in plan view.",
                    approximate=e["curved"],
                )
        except GEOSException as exc:
            add("geometry_error", [eid], str(exc)[:300])
            continue
        if not e["closed"] and len(e["endpoints"]) == 2:
            for p in e["endpoints"]:
                endpoints.append(Point(p[:2]))
                endpoint_owners.append(eid)
        # Only exact straight segments are compared between entities.
        for a, b in e["segments"]:
            if a != b:
                segments.append(LineString([a[:2], b[:2]]))
                owners.append(eid)
    pairs = 0
    if endpoints:
        tree = STRtree(endpoints)
        for i, p in enumerate(endpoints):
            for raw_j in tree.query(p, predicate="dwithin", distance=radius):
                j = int(raw_j)
                if j <= i:
                    continue
                pairs += 1
                if pairs > MAX_PAIRS:
                    raise ValueError("Endpoint density exceeds QA budget; split the drawing.")
                gap = p.distance(endpoints[j])
                if gap > 0:
                    add(
                        "endpoint_gap",
                        [endpoint_owners[i], endpoint_owners[j]],
                        "Nearby endpoints; confirm intended connectivity. "
                        + ("Exceeds" if gap > threshold else "Within")
                        + " 0.10-foot tolerance; not adjusted.",
                        {
                            "gap_project_units": gap,
                            "gap_ft": gap * unit / 0.3048,
                            "over_tolerance": gap > threshold,
                        },
                    )
    if segments:
        tree = STRtree(segments)
        for i, line in enumerate(segments):
            for raw_j in tree.query(line):
                j = int(raw_j)
                if j <= i or owners[i] == owners[j]:
                    continue
                pairs += 1
                if pairs > MAX_PAIRS:
                    raise ValueError("Segment density exceeds QA budget; split the drawing.")
                cross = line.intersection(segments[j])
                if cross.geom_type == "Point" and line.crosses(segments[j]):
                    add(
                        "crossing",
                        [owners[i], owners[j]],
                        "Straight entities cross in XY; review whether intentional.",
                        [cross.x, cross.y],
                    )
    return {
        "issues": issues,
        "threshold_ft": 0.1,
        "gap_search_ft": search_ft,
        "engine": "Shapely " + shapely_version,
        "scope": "XY screening; crossings may be intentional or grade-separated. Exact duplicates check XYZ. Curve intersections are approximate; curved inter-entity intersections and overlapping partial segments are not tested. Gaps outside the search radius are not enumerated.",
    }


def closure(drawing, selections):
    """Explicit ordered chain; never infer order, join gaps, or force closure."""
    if not selections or len(selections) > 1000:
        raise ValueError("Select 1–1,000 ordered linework entities.")
    lookup = {e["entity_id"]: e for e in drawing["entities"]}
    ordered = []
    used = set()
    for item in selections:
        eid = item["entity_id"]
        if eid in used or eid not in lookup:
            raise ValueError("Closure selection contains duplicate or unknown entities.")
        used.add(eid)
        e = lookup[eid]
        if len(e["points"]) < 2 or not e["planar"]:
            raise ValueError("Closure requires planar linework with two endpoints.")
        if e["closed"]:
            raise ValueError(
                "DXF-closed entities already encode a closing edge. Use original open record linework to measure survey misclosure."
            )
        a, b = e["endpoints"]
        ordered.append((b, a) if item.get("reverse") else (a, b))
    unit = METERS[drawing["project_units"]]
    gaps = []
    for i in range(len(ordered)):
        end = ordered[i][1]
        start = ordered[(i + 1) % len(ordered)][0]
        de, dn = start[0] - end[0], start[1] - end[1]
        distance = math.hypot(de, dn)
        gaps.append(
            {
                "after_entity": selections[i]["entity_id"],
                "to_entity": selections[(i + 1) % len(ordered)]["entity_id"],
                "closing_gap": i == len(ordered) - 1,
                "delta_easting": de,
                "delta_northing": dn,
                "gap_project_units": distance,
                "gap_ft": distance * unit / 0.3048,
                "over_tolerance": distance * unit / 0.3048 > 0.1,
            }
        )
    return {
        "ordered_selection": selections,
        "gaps": gaps,
        "closing_gap": gaps[-1],
        "threshold_ft": 0.1,
        "status": "INVESTIGATE"
        if any(g["over_tolerance"] for g in gaps)
        else "WITHIN_TOLERANCE_REVIEW_REQUIRED",
        "notice": "End-to-start distances in explicit order, not an adjusted traverse. All joins must be reviewed. 0.10 ft means international feet (0.03048 m). No snapping, forced closure or coordinate adjustment is performed.",
    }
