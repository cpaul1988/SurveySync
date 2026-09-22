from __future__ import annotations

import json
import logging
import math
import zipfile
from pathlib import Path
from uuid import uuid4
from xml.sax.saxutils import escape

from pyproj import CRS, Transformer

from .audit import utc_now
from .project import SurveyProject

logger = logging.getLogger(__name__)


def sync_fieldbook_results(project: SurveyProject, results) -> dict:
    """Copy reviewed/derived FieldBook structures into canonical UtilitySync tables.

    This does not change FieldBook evidence. Utility tables are derived snapshots
    with explicit source_kind and can be regenerated from the field-book module.
    """
    now=utc_now(); structure_count=pipe_count=0
    with project.db.connect() as conn:
        conn.execute("DELETE FROM utility_pipes WHERE structure_id IN (SELECT structure_id FROM utility_structures WHERE source_kind='fieldbook')")
        conn.execute("DELETE FROM utility_structures WHERE source_kind='fieldbook'")
        for r in results:
            sid=uuid4().hex
            conn.execute(
                "INSERT INTO utility_structures(structure_id,point_id,source_kind,northing,easting,elevation,code,status,attributes_json,created_utc,modified_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (sid,r.point_id,"fieldbook",r.northing,r.easting,r.elevation,r.code,r.review_state.value,json.dumps({"category":r.category,"dip_status":r.dip_status.value,"qa_needs_review":r.qa_needs_review,"smart_confidence":r.smart_confidence,"qc_flags":r.qc_flags},sort_keys=True),now,now)
            ); structure_count+=1
            for idx,p in enumerate(r.pipes,start=1):
                conn.execute(
                    "INSERT INTO utility_pipes(pipe_id,structure_id,pipe_index,dip,invert_elevation,diameter_in,material,azimuth_deg,connected_structure_id,grade_percent,source_kind,status,attributes_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (uuid4().hex,sid,idx,p.dip,p.invert_elevation,p.diameter_in,p.material,p.azimuth_deg,None,None,"fieldbook","REVIEWED" if r.review_state.value in {"ACCEPTED","EDITED"} else "UNREVIEWED",json.dumps({"connected_point_id":p.connected_point_id,"connection_score":p.connection_score,"qc_flags":p.qc_flags,"notes":p.notes},sort_keys=True))
                ); pipe_count+=1
    project.db.audit("UtilitySync","FIELDBOOK_RESULTS_SYNCED",object_type="utility_dataset",object_id=project.manifest["project_id"],details={"structures":structure_count,"pipes":pipe_count})
    return {"structures":structure_count,"pipes":pipe_count}


def _distance_point_segment(px,py,ax,ay,bx,by) -> float:
    vx=bx-ax; vy=by-ay; wx=px-ax; wy=py-ay
    denom=vx*vx+vy*vy
    if denom<=0: return math.hypot(px-ax,py-ay)
    t=max(0.0,min(1.0,(wx*vx+wy*vy)/denom))
    qx=ax+t*vx; qy=ay+t*vy
    return math.hypot(px-qx,py-qy)


def _angle_delta(a,b): return abs((a-b+180.0)%360.0-180.0)

def _azimuth(ax,ay,bx,by): return math.degrees(math.atan2(bx-ax,by-ay))%360.0


def load_spatial_layers(project: SurveyProject, role: str | None=None) -> list[dict]:
    sql="SELECT * FROM spatial_layers"; params=()
    if role: sql+=" WHERE role=?"; params=(role,)
    sql+=" ORDER BY ts_utc DESC"
    with project.db.connect() as conn: rows=conn.execute(sql,params).fetchall()
    out=[]
    for row in rows:
        d=dict(row); path=project.paths.root/d["stored_json_path"]
        if path.is_file():
            try: d["data"]=json.loads(path.read_text(encoding="utf-8"))
            except Exception: d["data"]={}
        out.append(d)
    return out


def _gis_lines_project_xy(project: SurveyProject, role="supplemental_utility") -> list[dict]:
    crs=project.manifest.get("crs") or ""
    if not crs: raise ValueError("Set the SurveySync project CRS before comparing supplemental GIS to surveyed utility data.")
    tr=Transformer.from_crs(CRS.from_epsg(4326),CRS.from_user_input(crs),always_xy=True)
    segments=[]
    for layer in load_spatial_layers(project,role):
        for feat in (layer.get("data") or {}).get("features",[]):
            geom=feat.get("geometry") or {}; typ=geom.get("type"); coords=geom.get("coordinates")
            lines=[]
            if typ=="LineString": lines=[coords]
            elif typ=="MultiLineString": lines=coords or []
            elif typ=="Polygon": lines=coords or []
            elif typ=="MultiPolygon": lines=[ring for poly in (coords or []) for ring in poly]
            for line in lines:
                if not isinstance(line,list): continue
                xy=[]
                for c in line:
                    if not isinstance(c,(list,tuple)) or len(c)<2: continue
                    try: x,y=tr.transform(float(c[0]),float(c[1]));xy.append((x,y))
                    except Exception:
                        logger.debug("Skipped invalid supplemental GIS coordinate during UtilitySync scoring.", exc_info=True)
                for a,b in zip(xy,xy[1:]):
                    segments.append({"a":a,"b":b,"layer_id":layer["layer_id"],"properties":feat.get("properties") or {}})
    return segments


def score_supplemental_gis(project: SurveyProject, edges: list[dict], structures: list[dict], *, tolerance: float=30.0, angle_tolerance: float=35.0) -> list[dict]:
    """Attach non-authoritative GIS support scores to inferred sewer connections."""
    segments=_gis_lines_project_xy(project)
    by_id={str(s.get("point_id")):s for s in structures}
    out=[]
    for edge in edges:
        e=dict(edge); a=by_id.get(str(e.get("from_point"))); b=by_id.get(str(e.get("to_point")))
        support=None
        if a and b and None not in (a.get("easting"),a.get("northing"),b.get("easting"),b.get("northing")):
            ax,ay=float(a["easting"]),float(a["northing"]);bx,by=float(b["easting"]),float(b["northing"])
            edge_az=_azimuth(ax,ay,bx,by)
            best=None
            for seg in segments:
                (sx1,sy1),(sx2,sy2)=seg["a"],seg["b"]
                da=_distance_point_segment(ax,ay,sx1,sy1,sx2,sy2);db=_distance_point_segment(bx,by,sx1,sy1,sx2,sy2)
                seg_az=_azimuth(sx1,sy1,sx2,sy2); angle=min(_angle_delta(edge_az,seg_az),_angle_delta(edge_az,(seg_az+180)%360))
                # Both structures close to the same mapped line is strong supporting evidence.
                score=100*max(0,1-(da+db)/(2*max(tolerance,1e-9)))*max(0,1-angle/max(angle_tolerance,1e-9))
                cand={"score":score,"from_distance":da,"to_distance":db,"angle_error_deg":angle,"layer_id":seg["layer_id"],"properties":seg["properties"]}
                if best is None or cand["score"]>best["score"]:best=cand
            if best and best["score"]>0: support=best
        e["supplemental_gis"]=support
        base=float(e.get("score") or 0.0)
        if support:
            e["combined_support_score"]=round(min(100.0,base*0.8+support["score"]*0.2),1)
            e["notes"]=(str(e.get("notes") or "")+" Supplemental GIS supports this connection; GIS remains reference evidence only.").strip()
        else:e["combined_support_score"]=base
        out.append(e)
    return out


def pipe_grades(structures: list[dict], edges: list[dict]) -> list[dict]:
    by_id={str(s.get("point_id")):s for s in structures}
    out=[]
    for e in edges:
        a=by_id.get(str(e.get("from_point")));b=by_id.get(str(e.get("to_point")))
        if not a or not b: continue
        dist=e.get("distance")
        if dist is None and None not in (a.get("easting"),a.get("northing"),b.get("easting"),b.get("northing")):
            dist=math.hypot(float(b["easting"])-float(a["easting"]),float(b["northing"])-float(a["northing"]))
        pi=int(e.get("from_pipe_index") or 0)
        p1=(a.get("pipes") or [])
        p2=(b.get("pipes") or [])
        inv1=p1[pi-1].get("invert_elevation") if pi>0 and pi<=len(p1) else None
        inv2=None
        tpi=e.get("to_pipe_index")
        if tpi and 0<int(tpi)<=len(p2):inv2=p2[int(tpi)-1].get("invert_elevation")
        if inv1 is not None and inv2 is not None and dist and float(dist)>0:
            grade=(float(inv1)-float(inv2))/float(dist)*100.0
            out.append({"from_point":e.get("from_point"),"to_point":e.get("to_point"),"distance":dist,"from_invert":inv1,"to_invert":inv2,"grade_percent":grade,"flow_direction":"from_to" if grade>0 else "to_from" if grade<0 else "flat","qc_flag":"ADVERSE_GRADE" if grade<0 else ""})
    return out


def _supplemental_points_project_xy(project: SurveyProject, role="supplemental_utility") -> list[dict]:
    crs=project.manifest.get("crs") or ""
    if not crs: raise ValueError("Set the project CRS before building a utility completion map.")
    tr=Transformer.from_crs(CRS.from_epsg(4326),CRS.from_user_input(crs),always_xy=True)
    pts=[]
    for layer in load_spatial_layers(project,role):
        for feat in (layer.get("data") or {}).get("features",[]):
            geom=feat.get("geometry") or {}
            if geom.get("type")!="Point":continue
            c=geom.get("coordinates") or []
            if len(c)<2:continue
            try:x,y=tr.transform(float(c[0]),float(c[1]))
            except Exception:continue
            pts.append({"easting":x,"northing":y,"properties":feat.get("properties") or {},"layer_id":layer["layer_id"],"lon":float(c[0]),"lat":float(c[1])})
    return pts


def completion_status(project: SurveyProject, structures: list[dict], *, match_tolerance: float=25.0) -> dict:
    gis_points=_supplemental_points_project_xy(project)
    surveyed=[s for s in structures if s.get("easting") is not None and s.get("northing") is not None]
    missing=[]
    for gp in gis_points:
        nearest=None
        for s in surveyed:
            d=math.hypot(float(s["easting"])-gp["easting"],float(s["northing"])-gp["northing"])
            if nearest is None or d<nearest[0]:nearest=(d,s)
        if nearest is None or nearest[0]>match_tolerance:
            missing.append({**gp,"nearest_distance":nearest[0] if nearest else None})
    no_dip=[];complete=[]
    for s in surveyed:
        pipes=s.get("pipes") or []
        has_dip=any(p.get("dip") is not None for p in pipes)
        (complete if has_dip else no_dip).append(s)
    return {"missing":missing,"surveyed_no_dip":no_dip,"complete":complete,"match_tolerance":match_tolerance}


def export_completion_kmz(project: SurveyProject, structures: list[dict], output_path: Path, *, match_tolerance: float=25.0) -> dict:
    status=completion_status(project,structures,match_tolerance=match_tolerance)
    crs=CRS.from_user_input(project.manifest.get("crs") or "")
    tr=Transformer.from_crs(crs,CRS.from_epsg(4326),always_xy=True)
    def placemark(name,desc,lon,lat,style):
        return f'<Placemark><name>{escape(str(name))}</name><description>{escape(str(desc))}</description><styleUrl>#{style}</styleUrl><Point><coordinates>{lon:.9f},{lat:.9f},0</coordinates></Point></Placemark>'
    items=[]
    for i,g in enumerate(status["missing"],start=1):
        label=(g.get("properties") or {}).get("name") or (g.get("properties") or {}).get("PointID") or f"GIS-{i}"
        items.append(placemark(label,"MISSING — supplemental GIS structure not matched to surveyed structure",g["lon"],g["lat"],"missing"))
    for s in status["surveyed_no_dip"]:
        lon,lat=tr.transform(float(s["easting"]),float(s["northing"]));items.append(placemark(s.get("point_id"),"SURVEYED — dip still needed",lon,lat,"nodip"))
    for s in status["complete"]:
        lon,lat=tr.transform(float(s["easting"]),float(s["northing"]));items.append(placemark(s.get("point_id"),"COMPLETE — surveyed structure with dip",lon,lat,"complete"))
    kml='''<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>SurveySync Utility Completion</name>
<Style id="missing"><IconStyle><color>ff0000ff</color><scale>1.2</scale></IconStyle></Style>
<Style id="nodip"><IconStyle><color>ff00a5ff</color><scale>1.1</scale></IconStyle></Style>
<Style id="complete"><IconStyle><color>ff00aa00</color><scale>1.0</scale></IconStyle></Style>'''+''.join(items)+"</Document></kml>"
    output_path=Path(output_path);output_path.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output_path,"w",zipfile.ZIP_DEFLATED) as zf:zf.writestr("doc.kml",kml.encode("utf-8"))
    project.db.audit("CrewSync","UTILITY_COMPLETION_KMZ_EXPORTED",object_type="deliverable",object_id=output_path.name,details={"missing":len(status["missing"]),"surveyed_no_dip":len(status["surveyed_no_dip"]),"complete":len(status["complete"]),"path":str(output_path)})
    return {"path":str(output_path),"missing":len(status["missing"]),"surveyed_no_dip":len(status["surveyed_no_dip"]),"complete":len(status["complete"])}
