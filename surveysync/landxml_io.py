"""LandXML 1.2 point, parcel, and horizontal-alignment I/O.

The parser/exporter is intentionally narrow and reviewable. It supports CgPoint,
Parcel CoordGeom Line, and Alignment CoordGeom Line/Curve records used by the
SurveySync 9.3.2 alignment workflow.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

from defusedxml import ElementTree as SafeET
from pathlib import Path
from typing import Any

from .horizontal_alignment import build_horizontal_alignment

LANDXML_NS = "http://www.landxml.org/schema/LandXML-1.2"
ET.register_namespace("", LANDXML_NS)


def _q(tag: str) -> str:
    return f"{{{LANDXML_NS}}}{tag}"


def _parse_coord_text(text: str | None) -> tuple[float, float, float | None]:
    parts = str(text or "").strip().split()
    if len(parts) < 2:
        raise ValueError("LandXML coordinate requires at least Northing and Easting.")
    northing = float(parts[0])
    easting = float(parts[1])
    elevation = float(parts[2]) if len(parts) >= 3 else None
    return northing, easting, elevation


def _element_tag(element: ET.Element) -> str:
    return element.tag.split("}", 1)[-1]


def import_landxml(path: Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValueError("LandXML file does not exist.")
    try:
        tree = SafeET.parse(source)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid LandXML/XML: {exc}") from exc
    root = tree.getroot()
    namespace = root.tag.split("}", 1)[0].lstrip("{") if "}" in root.tag else ""
    prefix = f"{{{namespace}}}" if namespace else ""

    points: list[dict[str, Any]] = []
    for point in root.iter(f"{prefix}CgPoint"):
        text = str(point.text or "").strip()
        if not text:
            continue
        try:
            northing, easting, elevation = _parse_coord_text(text)
        except ValueError:
            continue
        points.append(
            {
                "point_id": str(point.get("name") or "").strip(),
                "description": str(point.get("desc") or "").strip(),
                "northing": northing,
                "easting": easting,
                "elevation": elevation,
            }
        )

    parcels: list[dict[str, Any]] = []
    parcels_parent = root.find(f"{prefix}Parcels")
    if parcels_parent is not None:
        for parcel in parcels_parent.findall(f"{prefix}Parcel"):
            vertices: list[dict[str, float]] = []
            coord_geom = parcel.find(f"{prefix}CoordGeom")
            if coord_geom is not None:
                for line in coord_geom.findall(f"{prefix}Line"):
                    start = line.find(f"{prefix}Start")
                    if start is not None and start.text:
                        n, e, _ = _parse_coord_text(start.text)
                        vertices.append({"northing": n, "easting": e})
            parcels.append(
                {
                    "name": str(parcel.get("name") or "").strip(),
                    "vertices": vertices,
                }
            )

    alignments: list[dict[str, Any]] = []
    warnings: list[str] = []
    alignments_parent = root.find(f"{prefix}Alignments")
    if alignments_parent is not None:
        for alignment in alignments_parent.findall(f"{prefix}Alignment"):
            coord_geom = alignment.find(f"{prefix}CoordGeom")
            if coord_geom is None:
                continue
            all_geometry = list(coord_geom)
            unsupported = [
                _element_tag(child)
                for child in all_geometry
                if _element_tag(child) not in {"Line", "Curve"}
            ]
            if unsupported:
                warnings.append(
                    f"Alignment {alignment.get('name', '')!r} contains unsupported "
                    f"geometry: {', '.join(unsupported)}."
                )
            children = [child for child in all_geometry if _element_tag(child) in {"Line", "Curve"}]
            if not children:
                continue

            first = children[0]
            start_node = first.find(f"{prefix}Start")
            if start_node is None or not start_node.text:
                warnings.append(
                    f"Alignment {alignment.get('name', '')!r} has no valid start coordinate."
                )
                continue
            start_n, start_e, _ = _parse_coord_text(start_node.text)

            first_tag = _element_tag(first)
            if first_tag == "Line":
                end_node = first.find(f"{prefix}End")
                if end_node is None or not end_node.text:
                    warnings.append(
                        f"Alignment {alignment.get('name', '')!r} first line has no endpoint."
                    )
                    continue
                end_n, end_e, _ = _parse_coord_text(end_node.text)
                start_azimuth = math.degrees(math.atan2(end_e - start_e, end_n - start_n)) % 360.0
            else:
                center_node = first.find(f"{prefix}Center")
                if center_node is None or not center_node.text:
                    warnings.append(
                        f"Alignment {alignment.get('name', '')!r} first curve has no center."
                    )
                    continue
                center_n, center_e, _ = _parse_coord_text(center_node.text)
                radial = math.degrees(math.atan2(start_e - center_e, start_n - center_n)) % 360.0
                direction = "RIGHT" if str(first.get("rot") or "cw").lower() == "cw" else "LEFT"
                start_azimuth = (radial + (90.0 if direction == "RIGHT" else -90.0)) % 360.0

            raw_elements: list[dict[str, Any]] = []
            for child_index, child in enumerate(children, start=1):
                tag = _element_tag(child)
                start_node = child.find(f"{prefix}Start")
                end_node = child.find(f"{prefix}End")
                if (
                    start_node is None
                    or end_node is None
                    or not start_node.text
                    or not end_node.text
                ):
                    warnings.append(
                        f"Alignment {alignment.get('name', '')!r} element {child_index} is missing Start/End."
                    )
                    continue
                child_start_n, child_start_e, _ = _parse_coord_text(start_node.text)
                child_end_n, child_end_e, _ = _parse_coord_text(end_node.text)

                if tag == "Line":
                    length_attr = child.get("length")
                    length = (
                        float(length_attr)
                        if length_attr
                        else math.hypot(child_end_n - child_start_n, child_end_e - child_start_e)
                    )
                    raw_elements.append({"kind": "tangent", "length": length})
                else:
                    radius = float(child.get("radius") or 0.0)
                    if radius <= 0:
                        warnings.append(
                            f"Alignment {alignment.get('name', '')!r} curve {child_index} has invalid radius."
                        )
                        continue
                    length_attr = child.get("length")
                    if length_attr:
                        length = float(length_attr)
                        delta_deg = math.degrees(length / radius)
                    else:
                        center_node = child.find(f"{prefix}Center")
                        if center_node is None or not center_node.text:
                            warnings.append(
                                f"Alignment {alignment.get('name', '')!r} curve {child_index} lacks length/center."
                            )
                            continue
                        center_n, center_e, _ = _parse_coord_text(center_node.text)
                        start_radial = (
                            math.degrees(
                                math.atan2(child_start_e - center_e, child_start_n - center_n)
                            )
                            % 360.0
                        )
                        end_radial = (
                            math.degrees(math.atan2(child_end_e - center_e, child_end_n - center_n))
                            % 360.0
                        )
                        direction = (
                            "RIGHT" if str(child.get("rot") or "cw").lower() == "cw" else "LEFT"
                        )
                        delta_deg = (
                            (end_radial - start_radial) % 360.0
                            if direction == "RIGHT"
                            else (start_radial - end_radial) % 360.0
                        )
                    direction = "RIGHT" if str(child.get("rot") or "cw").lower() == "cw" else "LEFT"
                    raw_elements.append(
                        {
                            "kind": "curve",
                            "radius": radius,
                            "delta_deg": delta_deg,
                            "direction": direction,
                        }
                    )

            if not raw_elements:
                continue
            normalized = build_horizontal_alignment(
                start_northing=start_n,
                start_easting=start_e,
                start_azimuth_deg=start_azimuth,
                start_station=float(alignment.get("staStart") or 0.0),
                elements=raw_elements,
            )
            alignments.append(
                {
                    "name": str(alignment.get("name") or "").strip(),
                    "description": str(alignment.get("desc") or "").strip(),
                    "alignment": {
                        "start_northing": start_n,
                        "start_easting": start_e,
                        "start_azimuth_deg": start_azimuth,
                        "start_station": float(alignment.get("staStart") or 0.0),
                        "elements": raw_elements,
                    },
                    "derived": normalized,
                }
            )

    return {
        "source_path": str(source),
        "landxml_version": str(root.get("version") or ""),
        "point_count": len(points),
        "parcel_count": len(parcels),
        "alignment_count": len(alignments),
        "points": points,
        "parcels": parcels,
        "alignments": alignments,
        "warnings": warnings,
    }


def export_landxml(
    *,
    output_path: Path,
    points: list[dict[str, Any]],
    parcels: list[dict[str, Any]],
    alignments: list[dict[str, Any]],
) -> dict[str, Any]:
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    root = ET.Element(_q("LandXML"), {"version": "1.2"})

    if points:
        cg_points = ET.SubElement(root, _q("CgPoints"))
        for point in points:
            attrs = {"name": str(point.get("point_id") or "")}
            description = str(point.get("description") or "").strip()
            if description:
                attrs["desc"] = description
            node = ET.SubElement(cg_points, _q("CgPoint"), attrs)
            elevation = point.get("elevation")
            if elevation is None:
                node.text = f"{float(point['northing']):.6f} {float(point['easting']):.6f}"
            else:
                node.text = (
                    f"{float(point['northing']):.6f} {float(point['easting']):.6f} "
                    f"{float(elevation):.6f}"
                )

    if parcels:
        parcel_parent = ET.SubElement(root, _q("Parcels"))
        for parcel in parcels:
            vertices = list(parcel.get("vertices") or [])
            if len(vertices) < 3:
                continue
            parcel_node = ET.SubElement(
                parcel_parent,
                _q("Parcel"),
                {"name": str(parcel.get("name") or "")},
            )
            geom = ET.SubElement(parcel_node, _q("CoordGeom"))
            closed = vertices + [vertices[0]]
            for start_vertex, end_vertex in zip(closed, closed[1:], strict=True):
                line = ET.SubElement(geom, _q("Line"))
                start = ET.SubElement(line, _q("Start"))
                start.text = (
                    f"{float(start_vertex['northing']):.6f} {float(start_vertex['easting']):.6f}"
                )
                end = ET.SubElement(line, _q("End"))
                end.text = f"{float(end_vertex['northing']):.6f} {float(end_vertex['easting']):.6f}"

    if alignments:
        alignment_parent = ET.SubElement(root, _q("Alignments"))
        for item in alignments:
            name = str(item.get("name") or "")
            definition = dict(item.get("alignment") or item)
            derived = build_horizontal_alignment(**definition)
            alignment_node = ET.SubElement(
                alignment_parent,
                _q("Alignment"),
                {
                    "name": name,
                    "staStart": f"{float(derived['start_station']):.6f}",
                    "length": f"{float(derived['length']):.6f}",
                },
            )
            geom = ET.SubElement(alignment_node, _q("CoordGeom"))
            for element in derived["elements"]:
                if element["kind"] == "tangent":
                    node = ET.SubElement(
                        geom,
                        _q("Line"),
                        {
                            "dir": f"{float(element['start_azimuth_deg']):.8f}",
                            "length": f"{float(element['length']):.6f}",
                        },
                    )
                else:
                    node = ET.SubElement(
                        geom,
                        _q("Curve"),
                        {
                            "rot": "cw" if element["direction"] == "RIGHT" else "ccw",
                            "radius": f"{float(element['radius']):.6f}",
                            "length": f"{float(element['length']):.6f}",
                        },
                    )
                    center = ET.SubElement(node, _q("Center"))
                    center.text = (
                        f"{float(element['center_northing']):.6f} "
                        f"{float(element['center_easting']):.6f}"
                    )
                start = ET.SubElement(node, _q("Start"))
                start.text = (
                    f"{float(element['start_northing']):.6f} {float(element['start_easting']):.6f}"
                )
                end = ET.SubElement(node, _q("End"))
                end.text = (
                    f"{float(element['end_northing']):.6f} {float(element['end_easting']):.6f}"
                )

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(destination, encoding="utf-8", xml_declaration=True)
    return {
        "path": str(destination),
        "point_count": len(points),
        "parcel_count": len(parcels),
        "alignment_count": len(alignments),
        "landxml_version": "1.2",
    }
