from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from pathlib import Path

CODE_RE = re.compile(r"^(?P<line>\d+)(?:-(?P<event>BS|ES|PC|PT|CL))?$", re.I)


def _norm_header(v: str) -> str:
    return str(v or "").strip().lower().replace(" ", "_").replace("-", "_")


def parse_coded_points(path: Path) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    try: dialect = csv.Sniffer().sniff(text[:4096], delimiters=",\t;")
    except Exception: dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames: raise ValueError("Coded point file does not contain a header row.")
    normalized={_norm_header(f):f for f in reader.fieldnames}
    def pick(*names):
        return next((normalized[n] for n in names if n in normalized), None)
    f_id=pick("point_id","point","pt","number","pnt")
    f_n=pick("northing","north","n","y")
    f_e=pick("easting","east","e","x")
    f_z=pick("elevation","elev","z","height")
    f_code=pick("code","description","desc","feature_code","field_code")
    if not all((f_id,f_n,f_e,f_code)):
        raise ValueError("Field-to-Finish input needs PointID, Northing, Easting, and Code/Description columns.")
    out=[]
    for row_no,row in enumerate(reader,start=2):
        code=str(row.get(f_code,"") or "").strip()
        if not code: continue
        try:
            out.append({"point_id":str(row.get(f_id,"") or "").strip(),"northing":float(row[f_n]),"easting":float(row[f_e]),"elevation":float(row[f_z]) if f_z and str(row.get(f_z,"")).strip() else None,"code":code,"source_row":row_no})
        except Exception as exc:
            raise ValueError(f"Invalid coded point on row {row_no}: {exc}") from exc
    if not out: raise ValueError("No coded points were found.")
    return out


def build_linework(points: list[dict]) -> dict:
    """Build Carlson-style line strings from -BS/-ES/-PC/-PT/-CL events.

    Line identifiers are exact numeric codes, so 500, 5001 and 5002 can run at
    the same time without colliding. Curve events are preserved in vertex
    metadata for CAD/GIS export and later true-arc fitting.
    """
    active: dict[str,list[dict]]={}
    completed=[]; flags=[]; ignored=0
    for point in points:
        m=CODE_RE.match(str(point.get("code") or "").strip())
        if not m:
            ignored += 1; continue
        line=m.group("line"); event=(m.group("event") or "").upper()
        vertex={"point_id":point.get("point_id",""),"northing":point["northing"],"easting":point["easting"],"elevation":point.get("elevation"),"event":event or "CONTINUE","source_row":point.get("source_row")}
        if event == "BS":
            if line in active and active[line]:
                flags.append(f"Line {line}: new -BS encountered before previous line ended; previous partial line retained for review.")
                completed.append({"line_id":line,"status":"REVIEW","vertices":active[line],"reason":"restarted_before_end"})
            active[line]=[vertex]
            continue
        if line not in active:
            # A bare line code can legitimately continue a line whose -BS was
            # omitted by an older crew workflow, but we mark it for review.
            active[line]=[vertex]
            flags.append(f"Line {line}: sequence began without -BS at Point {point.get('point_id','')}.")
        else:
            active[line].append(vertex)
        if event == "ES":
            verts=active.pop(line)
            completed.append({"line_id":line,"status":"COMPLETE","vertices":verts,"reason":""})
        elif event == "CL":
            # Close line: append the starting coordinate as a derived display
            # vertex while retaining the original observations unchanged.
            verts=active.pop(line)
            if verts:
                closed=list(verts)+[{**verts[0],"event":"DERIVED_CLOSE","source_row":None}]
                completed.append({"line_id":line,"status":"COMPLETE_CLOSED","vertices":closed,"reason":"closed_by_CL"})
    for line,verts in active.items():
        completed.append({"line_id":line,"status":"OPEN","vertices":verts,"reason":"missing_ES"})
        flags.append(f"Line {line}: no -ES/-CL was found.")

    for line in completed:
        curve_open=False
        for v in line["vertices"]:
            if v["event"]=="PC":
                if curve_open: flags.append(f"Line {line['line_id']}: nested -PC before -PT.")
                curve_open=True
            elif v["event"]=="PT":
                if not curve_open: flags.append(f"Line {line['line_id']}: -PT found without preceding -PC.")
                curve_open=False
        if curve_open: flags.append(f"Line {line['line_id']}: -PC has no matching -PT.")
    return {"line_count":len(completed),"lines":completed,"qc_flags":flags,"ignored_code_count":ignored}


def to_geojson(result: dict) -> dict:
    features=[]
    for line in result.get("lines",[]):
        coords=[[v["easting"],v["northing"]] for v in line.get("vertices",[]) if v.get("easting") is not None and v.get("northing") is not None]
        if len(coords)<2: continue
        features.append({"type":"Feature","geometry":{"type":"LineString","coordinates":coords},"properties":{"LineID":line["line_id"],"Status":line["status"],"Events":" | ".join(f"{v.get('point_id')}:{v.get('event')}" for v in line.get("vertices",[]))}})
    return {"type":"FeatureCollection","name":"SurveySync_FieldToFinish","features":features}
