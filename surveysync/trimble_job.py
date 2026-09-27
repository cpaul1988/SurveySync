from __future__ import annotations

"""Trimble Access JOB / JobXML intake.

SurveySync never attempts to reverse engineer Trimble's binary ``.job`` format.
On Windows it uses Trimble's installed ASCII File Generator to create a temporary
JobXML representation, then parses the documented JobXML reductions.  The original
JOB remains the immutable project source evidence.
"""

import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable


class TrimbleJobError(RuntimeError):
    pass


def _local(tag: str) -> str:
    return str(tag or "").rsplit("}", 1)[-1]


def _attribute(node: ET.Element | None, *names: str) -> str:
    """Return the first matching attribute value without depending on namespace/case."""
    if node is None:
        return ""
    wanted = {name.casefold() for name in names}
    for key, value in node.attrib.items():
        if _local(key).casefold() in wanted:
            text = str(value or "").strip()
            if text:
                return text
    return ""


def _decode_xml_bytes(raw: bytes) -> tuple[str, str]:
    """Decode malformed XML for the narrow recovery path.

    ElementTree handles encoding declarations during normal parsing. This helper is
    only used after strict parsing failed, so it explicitly recognizes the common
    UTF BOMs/declarations that appear in Trimble JobXML exports.
    """
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), "utf-16"
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"

    head = raw[:512]
    match = re.search(
        br"""<\?xml[^>]*encoding\s*=\s*["']([^"']+)["']""",
        head,
        flags=re.IGNORECASE,
    )
    if match:
        encoding = match.group(1).decode("ascii", errors="ignore").strip() or "utf-8"
        try:
            return raw.decode(encoding), encoding
        except (LookupError, UnicodeDecodeError):
            pass

    # Some controller exports omit a BOM while still writing UTF-16.
    if len(raw) >= 4:
        if raw[1:2] == b"\x00" and raw[3:4] == b"\x00":
            return raw.decode("utf-16-le"), "utf-16-le"
        if raw[0:1] == b"\x00" and raw[2:3] == b"\x00":
            return raw.decode("utf-16-be"), "utf-16-be"

    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        # cp1252 is a practical final fallback for old Windows-authored exports.
        return raw.decode("cp1252"), "cp1252"


def _recover_jobxml_text(text: str) -> tuple[str, list[str]]:
    """Apply only safe text-level JobXML repairs.

    jxl2txt uses libxml2's recover mode. SurveySync deliberately avoids general
    structural recovery: it only removes illegal XML control characters and escapes
    bare ampersands, two field-text defects seen in hand-edited/vendor-generated XML.
    """
    actions: list[str] = []
    repaired = text

    cleaned = "".join(
        char
        for char in repaired
        if char in "\t\n\r" or ord(char) >= 0x20
    )
    if cleaned != repaired:
        repaired = cleaned
        actions.append("removed_illegal_xml_control_characters")

    bare_ampersand = re.compile(
        r"&(?!#\d+;|#x[0-9A-Fa-f]+;|amp;|lt;|gt;|apos;|quot;)"
    )
    escaped = bare_ampersand.sub("&amp;", repaired)
    if escaped != repaired:
        repaired = escaped
        actions.append("escaped_bare_ampersands")

    # ElementTree receives Unicode in recovery mode, so an encoding declaration
    # would no longer describe the input byte stream.
    without_declaration = re.sub(
        r"^\ufeff?\s*<\?xml[^>]*\?>",
        "",
        repaired,
        count=1,
        flags=re.IGNORECASE,
    )
    if without_declaration != repaired:
        repaired = without_declaration
        actions.append("removed_encoding_declaration_for_recovery")

    return repaired, actions


def _parse_jobxml_root(source: Path) -> tuple[ET.Element, dict]:
    """Parse JobXML strictly first, then use a narrow jxl2txt-inspired recovery path."""
    try:
        root = ET.parse(source).getroot()
        parse_meta = {
            "xml_parse_mode": "strict",
            "xml_recovery_used": False,
            "xml_recovery_actions": [],
            "xml_encoding": "",
        }
    except ET.ParseError as strict_error:
        try:
            raw = source.read_bytes()
            text, encoding = _decode_xml_bytes(raw)
            repaired, actions = _recover_jobxml_text(text)
            if not actions:
                raise TrimbleJobError(
                    f"Trimble JobXML could not be parsed: {strict_error}"
                ) from strict_error
            root = ET.fromstring(repaired)
        except TrimbleJobError:
            raise
        except (ET.ParseError, OSError, UnicodeError) as recovery_error:
            raise TrimbleJobError(
                "Trimble JobXML could not be parsed strictly or by the safe "
                f"text-recovery path: {recovery_error}"
            ) from strict_error
        parse_meta = {
            "xml_parse_mode": "recovered_text",
            "xml_recovery_used": True,
            "xml_recovery_actions": actions,
            "xml_encoding": encoding,
            "strict_parse_error": str(strict_error),
        }

    root_name = _local(root.tag)
    if root_name.casefold() not in {"jobfile", "jobxml"}:
        raise TrimbleJobError(
            f"Selected XML is not recognized as Trimble JobXML (root element: {root_name or '(blank)'})."
        )
    parse_meta["xml_root"] = root_name
    return root, parse_meta


def _first_descendant(node: ET.Element, name: str) -> ET.Element | None:
    wanted = name.casefold()
    for child in node.iter():
        if child is node:
            continue
        if _local(child.tag).casefold() == wanted:
            return child
    return None


def _children(node: ET.Element, name: str) -> list[ET.Element]:
    wanted = name.casefold()
    return [child for child in list(node) if _local(child.tag).casefold() == wanted]


def _first_child(node: ET.Element, *names: str) -> ET.Element | None:
    wanted = {n.casefold() for n in names}
    for child in list(node):
        if _local(child.tag).casefold() in wanted:
            return child
    return None


def _text(node: ET.Element | None, *names: str) -> str:
    if node is None:
        return ""
    wanted = {n.casefold() for n in names}
    for child in node.iter():
        if child is node:
            continue
        if _local(child.tag).casefold() in wanted:
            return str(child.text or "").strip()
    return ""


def _float(value: str) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _first_text(node: ET.Element | None, names: tuple[str, ...]) -> tuple[str, str]:
    """Return (local_tag, text) for the first preferred matching descendant."""
    if node is None:
        return "", ""
    descendants=[child for child in node.iter() if child is not node]
    # Respect the caller's preferred tag order. This matters for vendor records
    # that may contain a generic <Name> before the actual <PointName>.
    for wanted in names:
        folded=wanted.casefold()
        for child in descendants:
            local=_local(child.tag)
            if local.casefold() == folded:
                value=str(child.text or "").strip()
                if value:
                    return local, value
    return "", ""


def _duration_seconds_from_text(value: str, tag: str = "") -> float | None:
    text=str(value or "").strip()
    if not text:
        return None
    low=text.lower()
    try:
        if ":" in low:
            parts=[float(x) for x in low.split(":")]
            if len(parts)==3:
                return parts[0]*3600.0+parts[1]*60.0+parts[2]
            if len(parts)==2:
                return parts[0]*60.0+parts[1]
        m=re.match(r"^([0-9]*\.?[0-9]+)\s*(h|hr|hrs|hour|hours)$",low)
        if m:
            return float(m.group(1))*3600.0
        m=re.match(r"^([0-9]*\.?[0-9]+)\s*(m|min|mins|minute|minutes)$",low)
        if m:
            return float(m.group(1))*60.0
        m=re.match(r"^([0-9]*\.?[0-9]+)\s*(s|sec|secs|second|seconds)$",low)
        if m:
            return float(m.group(1))
        number=float(low)
        # Explicit minute tags are uncommon but should be honored when present.
        if "minute" in str(tag or "").casefold():
            return number*60.0
        return number
    except (TypeError, ValueError):
        return None


def _optional_float_text(value: str) -> float | None:
    text=str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _observation_metadata(node: ET.Element | None) -> dict:
    """Extract common Trimble GNSS occupation/quality metadata.

    JobXML element names vary across Trimble Access generations and export styles.
    SurveySync intentionally uses a broad alias set and never invents missing values.
    """
    if node is None:
        return {}
    _date_tag,date=_first_text(node,("StartDate","ObservationDate","OccupationDate","Date"))
    _time_tag,time=_first_text(node,("StartDateTime","ObservationStart","OccupationStart","ObservationTime","StartTime","TimeStamp","Timestamp","UTC","Time"))
    observed=time
    if date and time and date not in time:
        observed=f"{date} {time}"
    elif date and not time:
        observed=date
    epoch_tag,epoch_text=_first_text(node,("EpochCount","Epochs","NumberOfEpochs","NumEpochs","ObservationEpochs"))
    sat_tag,sat_text=_first_text(node,("SatelliteCount","Satellites","NumberOfSatellites","NumSatellites","SatellitesUsed","SVCount","SVs","NumberSV"))
    dur_tag,dur_text=_first_text(node,("DurationSeconds","ObservationSeconds","OccupationSeconds","DurationMinutes","ObservationMinutes","OccupationMinutes","ObservationDuration","OccupationDuration","Duration"))
    _pdop_tag,pdop_text=_first_text(node,("PDOP","Pdop","PositionDOP","PositionDilutionOfPrecision"))
    _hdop_tag,hdop_text=_first_text(node,("HDOP","Hdop","HorizontalDOP","HorizontalDilutionOfPrecision"))
    _vdop_tag,vdop_text=_first_text(node,("VDOP","Vdop","VerticalDOP","VerticalDilutionOfPrecision"))
    _fix_tag,fix_type=_first_text(node,("FixType","SolutionType","PositionType","GPSQuality","GNSSQuality","RTKStatus","Quality","SolutionStatus"))
    _rx_tag,receiver_model=_first_text(node,("ReceiverModel","ReceiverType","RoverModel","GNSSReceiver","ReceiverName","InstrumentModel"))
    _serial_tag,receiver_serial=_first_text(node,("ReceiverSerialNumber","ReceiverSerial","SerialNumber","SerialNo","InstrumentSerialNumber"))
    _ant_tag,antenna_type=_first_text(node,("AntennaType","AntennaModel","AntennaName","Antenna"))
    _ah_tag,antenna_height_text=_first_text(node,("AntennaHeight","HeightOfAntenna","InstrumentHeight","AntennaHeightValue","MeasuredHeight"))
    def intish(value: str):
        try:
            return int(round(float(value))) if value else None
        except (TypeError,ValueError):
            return None
    return {
        "observed_utc": observed,
        "observed_time_provided": 1 if bool(time) else 0,
        "epoch_count": intish(epoch_text),
        "duration_seconds": _duration_seconds_from_text(dur_text,dur_tag),
        "satellite_count": intish(sat_text),
        "pdop": _optional_float_text(pdop_text),
        "hdop": _optional_float_text(hdop_text),
        "vdop": _optional_float_text(vdop_text),
        "fix_type": str(fix_type or "").strip(),
        "receiver_model": str(receiver_model or "").strip(),
        "receiver_serial": str(receiver_serial or "").strip(),
        "antenna_type": str(antenna_type or "").strip(),
        "antenna_height": _optional_float_text(antenna_height_text),
    }


def _merge_observation_metadata(current: dict | None, incoming: dict) -> dict:
    out=dict(current or {})
    for key,value in incoming.items():
        if value not in (None, ""):
            # Prefer an explicit field observation over an earlier blank/default.
            if key == "observed_time_provided":
                out[key]=max(int(out.get(key) or 0), int(value or 0))
            elif out.get(key) in (None, ""):
                out[key]=value
            elif key in {"satellite_count", "epoch_count", "duration_seconds"}:
                # Multiple raw GNSS records may describe one occupation; keep the
                # strongest available observation metadata without fabricating it.
                try:
                    out[key]=max(float(out[key]), float(value))
                    if key in {"satellite_count", "epoch_count"}: out[key]=int(round(out[key]))
                except (TypeError, ValueError):
                    pass
            elif key in {"pdop", "hdop", "vdop"}:
                # DOP is a quality ceiling, so retain the worst reported value when
                # multiple FieldBook records describe the same occupation.
                try: out[key]=max(float(out[key]),float(value))
                except (TypeError,ValueError): pass
    return out


def _fieldbook_metadata_by_point(fieldbook: ET.Element | None) -> tuple[dict[str, dict], dict]:
    """Best-effort GNSS occupation metadata keyed by point label.

    Unlike the older parser, metadata from multiple records for one point is merged.
    This matters because Trimble Access can store coordinates, occupation settings,
    DOP/quality, receiver details and timestamps in separate neighboring records.
    """
    if fieldbook is None:
        return {}, {"fieldbook_present": False, "record_types": {}, "point_metadata_records": 0}
    by_point: dict[str, dict] = {}
    record_types: dict[str, int] = {}
    matched=0
    record_tokens=("point","gnss","gps","occupation","observation","station","rtk","vector")
    for node in fieldbook.iter():
        if node is fieldbook or not list(node):
            continue
        local_name=_local(node.tag)
        local=local_name.casefold()
        record_types[local_name]=record_types.get(local_name,0)+1
        if not any(token in local for token in record_tokens):
            continue
        _tag,name=_first_text(node,("PointName","PointID","PointId","Name","StationName","Station","TargetName","TargetPoint","RoverPoint","RoverPointName"))
        name=str(name or "").strip()
        if not name:
            continue
        meta=_observation_metadata(node)
        if not any(v not in (None, "", 0) for k,v in meta.items() if k != "observed_time_provided"):
            continue
        matched+=1
        meta["fieldbook_record_type"]=local_name
        by_point[name]=_merge_observation_metadata(by_point.get(name),meta)
    return by_point, {"fieldbook_present": True, "record_types": record_types, "point_metadata_records": matched}


def ascii_generator_candidates() -> list[Path]:
    """Return likely official Trimble ASCII File Generator locations.

    The utility is installed by Trimble office components / File and Report
    Generator.  An explicit environment variable wins so managed workstations can
    point SurveySync at a nonstandard installation without editing application code.
    """
    raw: list[str] = []
    env = os.environ.get("SURVEYSYNC_TRIMBLE_ASCII_GENERATOR", "").strip().strip('"')
    if env:
        raw.append(env)
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    common = [
        rf"{program_files_x86}\Common Files\Trimble\ASCII File Generator\AsciiFileGenerator.exe",
        rf"{program_files}\Common Files\Trimble\ASCII File Generator\AsciiFileGenerator.exe",
        rf"{program_files_x86}\Trimble\ASCII File Generator\AsciiFileGenerator.exe",
        rf"{program_files}\Trimble\ASCII File Generator\AsciiFileGenerator.exe",
    ]
    raw.extend(common)
    which = shutil.which("AsciiFileGenerator.exe") or shutil.which("AsciiFileGenerator")
    if which:
        raw.append(which)
    out: list[Path] = []
    seen: set[str] = set()
    for value in raw:
        key = os.path.normcase(os.path.abspath(os.path.expanduser(value)))
        if key in seen:
            continue
        seen.add(key)
        out.append(Path(value))
    return out


def find_ascii_generator(explicit: str | Path | None = None) -> Path | None:
    candidates = ([Path(explicit)] if explicit else []) + ascii_generator_candidates()
    for candidate in candidates:
        try:
            if candidate.expanduser().is_file():
                return candidate.expanduser().resolve()
        except OSError:
            continue
    return None


def trimble_runtime_status() -> dict:
    exe = find_ascii_generator()
    return {
        "ascii_generator_ready": bool(exe),
        "ascii_generator_path": str(exe) if exe else "",
        "job_direct_import_ready": bool(exe),
        "jxl_direct_import_ready": True,
        "conversion_method": "Trimble ASCII File Generator -> Trimble JobXML",
        "note": (
            "Direct .job import is ready." if exe else
            "Install Trimble File and Report Generator / office converters, or set SURVEYSYNC_TRIMBLE_ASCII_GENERATOR. "
            "SurveySync will not reverse-engineer the proprietary JOB binary format."
        ),
    }


def convert_job_to_jxl(
    job_path: str | Path,
    output_path: str | Path,
    *,
    generator_path: str | Path | None = None,
    timeout_seconds: int = 180,
) -> dict:
    """Convert one Trimble Access ``.job`` to JobXML using Trimble's official utility.

    Official ASCII File Generator command-line convention:
        AsciiFileGenerator.exe INPUT.job "Trimble JobXML" OUTPUT.jxl
    """
    source = Path(job_path).expanduser().resolve()
    if not source.is_file():
        raise TrimbleJobError(f"Trimble JOB file was not found: {source}")
    if source.suffix.lower() != ".job":
        raise TrimbleJobError("Trimble JOB conversion requires a .job input file.")
    exe = find_ascii_generator(generator_path)
    if exe is None:
        raise TrimbleJobError(
            "Trimble's ASCII File Generator was not found. Install Trimble File and Report Generator / the current "
            "Trimble office converters on this Windows PC, then retry. SurveySync preserves the original .job and does "
            "not attempt to decode Trimble's proprietary JOB binary directly."
        )
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    command = [str(exe), str(source), "Trimble JobXML", str(output)]
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=max(30, int(timeout_seconds)),
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise TrimbleJobError(f"Trimble JOB conversion timed out after {timeout_seconds} seconds.") from exc
    except OSError as exc:
        raise TrimbleJobError(f"Could not start Trimble ASCII File Generator: {exc}") from exc
    if completed.returncode != 0 or not output.is_file() or output.stat().st_size <= 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-1200:]
        raise TrimbleJobError(
            f"Trimble ASCII File Generator did not create JobXML (exit {completed.returncode})."
            + (f" {detail}" if detail else "")
        )
    return {
        "input_path": str(source),
        "jobxml_path": str(output),
        "generator_path": str(exe),
        "return_code": completed.returncode,
    }


def parse_jobxml_points(path: str | Path) -> dict:
    """Parse grid points from Trimble JobXML without binding to one schema version.

    Parsing is namespace-agnostic and accepts Reductions/InventoryData sections
    nested beneath wrapper elements used by different Trimble products. Strict XML
    parsing is always attempted first; the fallback only repairs field-text defects
    (illegal control characters or bare ampersands), never structural XML damage.
    """
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise TrimbleJobError(f"JobXML file was not found: {source}")

    root, parse_meta = _parse_jobxml_root(source)

    reductions = _first_descendant(root, "Reductions")
    inventory = _first_descendant(root, "InventoryData")
    fieldbook = _first_descendant(root, "FieldBook")
    environment = _first_descendant(root, "Environment")

    points: list[dict] = []
    skipped = 0
    duplicate_names: list[str] = []
    seen: set[str] = set()
    fieldbook_meta, fieldbook_scan = _fieldbook_metadata_by_point(fieldbook)

    def append_points(container: ET.Element | None, *, skip_existing: bool = False) -> int:
        nonlocal skipped
        if container is None:
            return 0
        added = 0
        for point in container.iter():
            if _local(point.tag).casefold() != "point":
                continue

            _name_tag, name_text = _first_text(
                point, ("PointName", "PointID", "PointId", "Name")
            )
            name = (
                str(name_text or "").strip()
                or _attribute(point, "PointName", "PointID", "PointId", "Name")
            )
            if not name:
                skipped += 1
                continue
            if skip_existing and name in seen:
                continue

            grid = _first_child(point, "Grid")
            if grid is None:
                grid = _first_descendant(point, "Grid")
            coordinate_node = grid if grid is not None else point

            _north_tag, north_text = _first_text(
                coordinate_node, ("North", "Northing")
            )
            _east_tag, east_text = _first_text(
                coordinate_node, ("East", "Easting")
            )
            _elev_tag, elevation_text = _first_text(
                coordinate_node, ("Elevation", "Height", "Elev")
            )
            north = _float(north_text)
            east = _float(east_text)
            elevation = _float(elevation_text)
            if north is None or east is None:
                skipped += 1
                continue

            _code_tag, code_text = _first_text(
                point, ("Code", "FeatureCode", "Description")
            )
            _method_tag, method_text = _first_text(point, ("SurveyMethod",))
            _class_tag, classification_text = _first_text(
                point, ("Classification",)
            )
            code = str(code_text or "").strip() or _attribute(
                point, "Code", "FeatureCode", "Description"
            )
            survey_method = str(method_text or "").strip() or _attribute(
                point, "SurveyMethod"
            )
            classification = str(classification_text or "").strip() or _attribute(
                point, "Classification"
            )

            if name in seen:
                duplicate_names.append(name)
            seen.add(name)

            point_meta = _observation_metadata(point)
            fb_meta = fieldbook_meta.get(name, {})
            merged_meta = {
                key: (
                    point_meta.get(key)
                    if point_meta.get(key) not in (None, "")
                    else fb_meta.get(key)
                )
                for key in (
                    "observed_utc",
                    "epoch_count",
                    "duration_seconds",
                    "satellite_count",
                    "pdop",
                    "hdop",
                    "vdop",
                    "fix_type",
                    "receiver_model",
                    "receiver_serial",
                    "antenna_type",
                    "antenna_height",
                    "fieldbook_record_type",
                )
            }
            # A reduction/inventory point usually has no observation-time fields at
            # all; its default 0 flag must not overwrite a real FieldBook time.
            merged_meta["observed_time_provided"] = (
                int(bool(point_meta.get("observed_time_provided")))
                if point_meta.get("observed_utc")
                else int(bool(fb_meta.get("observed_time_provided")))
            )
            points.append(
                {
                    "point_id": name,
                    "northing": north,
                    "easting": east,
                    "elevation": elevation,
                    "code": code,
                    "survey_method": survey_method,
                    "classification": classification,
                    **merged_meta,
                }
            )
            added += 1
        return added

    reduction_count = append_points(reductions)
    # TBC-produced JobXML can legitimately contain an empty Reductions section
    # while storing usable grid points under InventoryData. Prefer reductions,
    # then use InventoryData only to supplement point IDs not already present.
    inventory_count = append_points(inventory, skip_existing=bool(reduction_count))
    point_source = (
        "Reductions"
        if reduction_count
        else ("InventoryData" if inventory_count else "")
    )

    fieldbook_record_counts: dict[str, int] = {}
    if fieldbook is not None:
        for child in fieldbook.iter():
            if child is fieldbook:
                continue
            tag = _local(child.tag)
            if list(child):
                fieldbook_record_counts[tag] = fieldbook_record_counts.get(tag, 0) + 1

    env_summary: dict[str, str] = {}
    if environment is not None:
        # Preserve coordinate-system hints without making a professional CRS
        # decision from vendor-specific records.
        for key in (
            "CoordinateSystemName",
            "Projection",
            "Datum",
            "GeoidModel",
            "DistanceUnits",
            "VerticalDatum",
        ):
            value = _text(environment, key)
            if value:
                env_summary[key] = value

    namespace_uri = ""
    root_tag = str(root.tag or "")
    if root_tag.startswith("{") and "}" in root_tag:
        namespace_uri = root_tag[1:].split("}", 1)[0]

    metadata = {
        "job_name": _attribute(root, "jobName", "JobName") or source.stem,
        "jobxml_version": _attribute(root, "version", "Version"),
        "product": _attribute(root, "product", "Product"),
        "product_version": _attribute(root, "productVersion", "ProductVersion"),
        "product_db_version": _attribute(
            root, "productDBVersion", "ProductDBVersion"
        ),
        "timestamp": _attribute(root, "TimeStamp", "Timestamp", "timestamp"),
        "schema_location": _attribute(root, "schemaLocation"),
        "namespace_uri": namespace_uri,
        "point_count": len(points),
        "point_source": point_source,
        "reduction_point_count": reduction_count,
        "inventory_point_count": inventory_count,
        "skipped_point_records": skipped,
        "duplicate_point_ids": sorted(set(duplicate_names)),
        "fieldbook_record_counts": fieldbook_record_counts,
        "fieldbook_scan": fieldbook_scan,
        "environment": env_summary,
        "gnss_metadata_counts": {
            key: sum(1 for point in points if point.get(key) not in (None, ""))
            for key in (
                "observed_utc",
                "epoch_count",
                "duration_seconds",
                "satellite_count",
                "pdop",
                "hdop",
                "vdop",
                "fix_type",
                "receiver_model",
                "receiver_serial",
                "antenna_type",
                "antenna_height",
            )
        },
        **parse_meta,
    }
    return {"metadata": metadata, "points": points}


def numeric_point_ids(points: Iterable[dict]) -> tuple[list[int], int]:
    ids: list[int] = []
    ignored = 0
    for point in points:
        value = str(point.get("point_id") or "").strip()
        if re.fullmatch(r"\d+", value):
            ids.append(int(value))
        elif value:
            ignored += 1
    return sorted(set(ids)), ignored


def prepare_jobxml(
    path: str | Path,
    work_dir: str | Path,
    *,
    generator_path: str | Path | None = None,
) -> tuple[Path, dict]:
    """Return a JobXML path for either a .jxl or a directly supplied .job."""
    source = Path(path).expanduser().resolve()
    suffix = source.suffix.lower()
    if suffix in {".jxl", ".xml"}:
        return source, {"converted": False, "input_path": str(source), "jobxml_path": str(source)}
    if suffix != ".job":
        raise TrimbleJobError("Select a Trimble Access .job or JobXML .jxl file.")
    work = Path(work_dir).expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)
    out = work / f"{source.stem}_SurveySync.jxl"
    result = convert_job_to_jxl(source, out, generator_path=generator_path)
    result["converted"] = True
    return out, result
