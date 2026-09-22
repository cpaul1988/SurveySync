from __future__ import annotations

import math
import re
from functools import lru_cache
from typing import Any

from pyproj import CRS, Transformer, database

UNIT_ALIASES = {
    "us_survey_feet": "US survey foot",
    "international_feet": "foot",
    "meters": "metre",
}



_US_STATES = (
    "Alabama","Alaska","Arizona","Arkansas","California","Colorado","Connecticut","Delaware","Florida","Georgia",
    "Hawaii","Idaho","Illinois","Indiana","Iowa","Kansas","Kentucky","Louisiana","Maine","Maryland","Massachusetts",
    "Michigan","Minnesota","Mississippi","Missouri","Montana","Nebraska","Nevada","New Hampshire","New Jersey",
    "New Mexico","New York","North Carolina","North Dakota","Ohio","Oklahoma","Oregon","Pennsylvania","Rhode Island",
    "South Carolina","South Dakota","Tennessee","Texas","Utah","Vermont","Virginia","Washington","West Virginia",
    "Wisconsin","Wyoming","Puerto Rico","Virgin Islands","Guam","American Samoa"
)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


@lru_cache(maxsize=1)
def _crs_catalog() -> tuple[dict, ...]:
    out=[]
    for item in database.query_crs_info(allow_deprecated=False):
        kind=str(getattr(item.type,"value",item.type) or "")
        if kind not in {"PROJECTED_CRS","GEOGRAPHIC_2D_CRS","GEOGRAPHIC_3D_CRS","GEODETIC_CRS"}:
            continue
        area=getattr(item,"area_of_use",None)
        out.append({
            "authority":str(item.auth_name or ""),
            "code":str(item.code or ""),
            "id":f"{item.auth_name}:{item.code}",
            "name":str(item.name or ""),
            "type":kind,
            "area":getattr(area,"name","") if area else "",
            "projection_method":str(getattr(item,"projection_method_name","") or ""),
        })
    return tuple(out)


def _is_projected(row: dict) -> bool:
    return row.get("type") == "PROJECTED_CRS"


def _state_name(row: dict) -> str:
    name=str(row.get("name") or "").replace("_"," ")
    area=str(row.get("area") or "")
    # Prefer the jurisdiction segment in PROJ's area-of-use text. Searching the
    # whole county list can misclassify Missouri East as Mississippi because
    # "Mississippi" is also a Missouri county name.
    area_head=area
    marker="United States (USA) - "
    if marker in area:
        area_head=area.split(marker,1)[1].split(" - ",1)[0]
    for state in _US_STATES:
        if area_head.casefold().startswith(state.casefold()):
            return state
    name_fold=name.casefold()
    for state in _US_STATES:
        if state.casefold() in name_fold:
            return state
    return ""


def _is_state_plane(row: dict) -> bool:
    if not _is_projected(row):
        return False
    name=str(row.get("name") or "")
    low=name.casefold()
    if "utm" in low:
        return False
    if "stateplane" in low or "state plane" in low:
        return True
    state=_state_name(row)
    area=str(row.get("area") or "").casefold()
    datumish=("nad27" in low or "nad83" in low or "nad_1927" in low or "nad_1983" in low or "natrf" in low)
    return bool(state and datumish and ("united states" in area or "usa" in area))


def _utm_datum(row: dict) -> str:
    name=str(row.get("name") or "").replace("_"," ")
    if "utm" not in name.casefold():
        return ""
    return name.split("/",1)[0].strip() if "/" in name else name.split("UTM",1)[0].strip() or "Other UTM"


def _geographic_group(row: dict) -> str:
    name=str(row.get("name") or "").casefold()
    area=str(row.get("area") or "").casefold()
    if name.startswith("wgs") or "world" in area:
        return "World / WGS"
    if name.startswith("nad") or "north america" in area or any(x in area for x in ("united states","canada","mexico")):
        return "North America / NAD"
    if name.startswith("itrf") or "international terrestrial reference" in name:
        return "ITRF / Global Reference Frames"
    if any(x in name for x in ("etrs","ed50","osgb","rgf","dhdn","etrf")) or "europe" in area:
        return "Europe"
    return "Other Geographic Systems"



def _state_plane_datum(row: dict) -> str:
    name=str(row.get("name") or "").replace("_"," ").casefold()
    rules=(("NAD 1983 (2011)",("nad83(2011)","nad 1983 (2011)","nad83 2011")),("NAD 1983 NSRS2007",("nsrs2007",)),("NAD 1983 HARN",("harn",)),("NAD 1983 CSRS",("csrs",)),("NAD 1983",("nad83","nad 1983")),("NAD 1927",("nad27","nad 1927")),("NATRF2022",("natrf2022","natrf")))
    for label,tokens in rules:
        if any(token in name for token in tokens):return label
    return "Other"


def _geo_region(row: dict) -> str:
    area=str(row.get("area") or "").casefold();name=str(row.get("name") or "").casefold()
    checks=(("North America",("north america","united states","canada","mexico","greenland")),("South America",("south america","argentina","brazil","chile","colombia","peru")),("Europe",("europe","france","germany","spain","italy","united kingdom","ireland")),("Africa",("africa",)),("Asia",("asia","china","japan","india","korea")),("Australia and New Zealand",("australia","new zealand")),("Pacific Ocean",("pacific",)),("Atlantic Ocean",("atlantic",)),("Indian Ocean",("indian ocean",)),("Polar",("antarctica","arctic")))
    for label,tokens in checks:
        if any(t in area for t in tokens):return label
    if name.startswith(("wgs","itrf")) or "world" in area:return "World"
    return "Other"


def _projected_family(row: dict) -> str:
    name=str(row.get("name") or "").casefold();area=str(row.get("area") or "").casefold()
    if _is_state_plane(row):return "State Plane"
    if _utm_datum(row):return "UTM"
    if "county" in name:return "County Systems"
    if "state" in name and "plane" not in name:return "State Systems"
    if "world" in area or any(x in name for x in ("world","web mercator","equal earth","robinson","winkel")):return "World"
    if any(x in area for x in ("north america","south america","europe","africa","asia","australia")) and any(x in name for x in ("albers","lambert","equidistant","mercator")):return "Continental"
    if any(x in name for x in ("national grid","national","grid zone","map grid")):return "National Grids"
    if any(x in area for x in ("antarctica","arctic")) or "polar" in name:return "Polar"
    return "Country Systems"

def browse_crs_library(path: str = "", *, limit: int = 600) -> dict:
    """Browse local PROJ definitions with an ArcGIS/Esri-style category tree.

    The installed CRS catalog does not expose Esri's proprietary folder metadata,
    so SurveySync reproduces the familiar ArcGIS folder structure deterministically
    from CRS type, name and area-of-use while preserving EPSG/ESRI authority IDs.
    """
    clean="/".join(x for x in str(path or "").strip("/").split("/") if x)
    parts=clean.split("/") if clean else []
    catalog=list(_crs_catalog());limit=max(1,min(int(limit or 600),1600))
    def folder(name,child,count=None):
        d={"name":name,"path":child,"kind":"folder"}
        if count is not None:d["count"]=count
        return d
    def systems(rows):
        return sorted(rows,key=lambda r:(str(r.get("name") or "").casefold(),str(r.get("authority")),str(r.get("code"))))[:limit]
    breadcrumbs=[{"name":"Coordinate Systems","path":""}];folders=[];rows=[]
    projected=[r for r in catalog if _is_projected(r)];geo=[r for r in catalog if not _is_projected(r)]
    if not parts:
        folders=[folder("Geographic Coordinate Systems","geographic",len(geo)),folder("Projected Coordinate Systems","projected",len(projected))]
    elif parts[0]=="projected":
        breadcrumbs.append({"name":"Projected Coordinate Systems","path":"projected"})
        families=("Continental","Country Systems","County Systems","National Grids","Polar","State Plane","State Systems","UTM","World")
        if len(parts)==1:
            counts={f:sum(1 for r in projected if _projected_family(r)==f) for f in families}
            folders=[folder(f,f"projected/{_slug(f)}",counts[f]) for f in families if counts[f]]
        else:
            family=next((f for f in families if _slug(f)==parts[1]),parts[1].replace("_"," ").title())
            breadcrumbs.append({"name":family,"path":f"projected/{parts[1]}"})
            fam=[r for r in projected if _projected_family(r)==family]
            if family=="State Plane":
                if len(parts)==2:
                    datums=sorted(set(_state_plane_datum(r) for r in fam),key=str.casefold)
                    folders=[folder(d,f"projected/state_plane/{_slug(d)}",sum(1 for r in fam if _state_plane_datum(r)==d)) for d in datums]
                elif len(parts)==3:
                    datum=next((_state_plane_datum(r) for r in fam if _slug(_state_plane_datum(r))==parts[2]),parts[2].replace("_"," ").title())
                    breadcrumbs.append({"name":datum,"path":clean})
                    subset=[r for r in fam if _state_plane_datum(r)==datum]
                    states=sorted(set(_state_name(r) or "Other US" for r in subset),key=str.casefold)
                    folders=[folder(st,f"{clean}/{_slug(st)}",sum(1 for r in subset if (_state_name(r) or "Other US")==st)) for st in states]
                else:
                    datum_slug,state_slug=parts[2],parts[3]
                    datum=next((_state_plane_datum(r) for r in fam if _slug(_state_plane_datum(r))==datum_slug),datum_slug.replace("_"," ").title())
                    state=next((st for st in _US_STATES if _slug(st)==state_slug),"Other US" if state_slug=="other_us" else state_slug.replace("_"," ").title())
                    breadcrumbs.extend([{"name":datum,"path":f"projected/state_plane/{datum_slug}"},{"name":state,"path":clean}])
                    rows=systems([r for r in fam if _state_plane_datum(r)==datum and (_state_name(r) or "Other US")==state])
            elif family=="UTM":
                if len(parts)==2:
                    datums=sorted(set(_utm_datum(r) or "Other UTM" for r in fam),key=str.casefold)
                    folders=[folder(d,f"projected/utm/{_slug(d)}",sum(1 for r in fam if (_utm_datum(r) or "Other UTM")==d)) for d in datums]
                else:
                    datum=next(((_utm_datum(r) or "Other UTM") for r in fam if _slug(_utm_datum(r) or "Other UTM")==parts[2]),parts[2].replace("_"," ").title())
                    breadcrumbs.append({"name":datum,"path":clean});rows=systems([r for r in fam if (_utm_datum(r) or "Other UTM")==datum])
            else:
                rows=systems(fam)
    elif parts[0]=="geographic":
        breadcrumbs.append({"name":"Geographic Coordinate Systems","path":"geographic"})
        if len(parts)==1:
            regions=sorted(set(_geo_region(r) for r in geo),key=str.casefold)
            preferred=["World","North America","South America","Europe","Africa","Asia","Australia and New Zealand","Pacific Ocean","Atlantic Ocean","Indian Ocean","Polar","Other"]
            regions=sorted(regions,key=lambda x:(preferred.index(x) if x in preferred else 99,x))
            folders=[folder(g,f"geographic/{_slug(g)}",sum(1 for r in geo if _geo_region(r)==g)) for g in regions]
        else:
            region=next((_geo_region(r) for r in geo if _slug(_geo_region(r))==parts[1]),parts[1].replace("_"," ").title())
            breadcrumbs.append({"name":region,"path":clean});rows=systems([r for r in geo if _geo_region(r)==region])
    else:
        raise ValueError(f"Unknown coordinate-system library folder: {path}")
    return {"path":clean,"breadcrumbs":breadcrumbs,"folders":folders,"systems":rows,"truncated":len(rows)>=limit,"organization":"ArcGIS-style"}


def inspect_crs(value: str) -> dict:
    raw = str(value or "").strip()
    if not raw:
        return {"valid": False, "input": "", "message": "CRS is blank."}
    try:
        crs = CRS.from_user_input(raw)
    except Exception as exc:
        return {"valid": False, "input": raw, "message": str(exc)}
    axes = []
    for axis in crs.axis_info:
        axes.append(
            {
                "name": axis.name,
                "abbrev": axis.abbrev,
                "direction": axis.direction,
                "unit_name": axis.unit_name,
                "unit_conversion_factor": axis.unit_conversion_factor,
            }
        )
    auth = crs.to_authority()
    return {
        "valid": True,
        "input": raw,
        "name": crs.name,
        "authority": f"{auth[0]}:{auth[1]}" if auth else "",
        "is_projected": crs.is_projected,
        "is_geographic": crs.is_geographic,
        "axes": axes,
        "wkt": crs.to_wkt(),
    }


def search_crs_library(query: str = "", *, limit: int = 80, projected_only: bool = True) -> list[dict]:
    """Search the installed PROJ CRS database.

    SurveySync intentionally uses the local PROJ database rather than a web service so
    CRS selection works offline in the Windows desktop application. EPSG and ESRI
    definitions are both included because many US state-plane/legacy foot definitions
    are published under one authority or the other.
    """
    text = " ".join(str(query or "").strip().lower().split())
    limit = max(1, min(int(limit or 80), 250))
    out: list[dict] = []
    for row in _crs_catalog():
        kind = str(row.get("type") or "")
        if projected_only and "PROJECTED" not in kind:
            continue
        haystack = f"{row.get('id','')} {row.get('name','')} {row.get('area','')}".lower()
        if text and not all(token in haystack for token in text.split()):
            continue
        out.append(dict(row))
        if len(out) >= limit:
            break
    return out


def transform_xy(x: float, y: float, source: str, target: str) -> dict:
    src = CRS.from_user_input(source)
    dst = CRS.from_user_input(target)
    transformer = Transformer.from_crs(src, dst, always_xy=True)
    ox, oy = transformer.transform(float(x), float(y))
    return {"x": ox, "y": oy, "source": src.to_string(), "target": dst.to_string()}


def normalize_local_site(settings: dict | None) -> dict:
    raw: dict[str, Any] = dict(settings or {})
    enabled = bool(raw.get("enabled", False))
    factor = float(raw.get("grid_to_ground_factor", 1.0) or 1.0)
    if not math.isfinite(factor) or factor <= 0:
        raise ValueError("Grid-to-ground factor must be a positive finite number.")
    rotation = float(raw.get("rotation_deg", 0.0) or 0.0)
    if not math.isfinite(rotation):
        raise ValueError("Local-site rotation must be finite.")

    def number(key: str) -> float:
        value = float(raw.get(key, 0.0) or 0.0)
        if not math.isfinite(value):
            raise ValueError(f"Local-site {key.replace('_', ' ')} must be finite.")
        return value

    return {
        "enabled": enabled,
        "name": str(raw.get("name") or "Local Site").strip() or "Local Site",
        "grid_origin_northing": number("grid_origin_northing"),
        "grid_origin_easting": number("grid_origin_easting"),
        "local_origin_northing": number("local_origin_northing"),
        "local_origin_easting": number("local_origin_easting"),
        "grid_to_ground_factor": factor,
        # Positive rotation is clockwise, matching common survey/local-site usage.
        "rotation_deg": rotation,
        "factor_direction": "grid_to_ground",
    }


def grid_to_local(easting: float, northing: float, settings: dict | None) -> tuple[float, float]:
    site = normalize_local_site(settings)
    if not site["enabled"]:
        return float(easting), float(northing)
    dx = float(easting) - site["grid_origin_easting"]
    dy = float(northing) - site["grid_origin_northing"]
    theta = math.radians(site["rotation_deg"])
    c, s = math.cos(theta), math.sin(theta)
    # Clockwise rotation in the local EN plane, then grid -> ground scale.
    local_e = site["local_origin_easting"] + site["grid_to_ground_factor"] * (dx * c + dy * s)
    local_n = site["local_origin_northing"] + site["grid_to_ground_factor"] * (-dx * s + dy * c)
    return local_e, local_n


def local_to_grid(easting: float, northing: float, settings: dict | None) -> tuple[float, float]:
    site = normalize_local_site(settings)
    if not site["enabled"]:
        return float(easting), float(northing)
    factor = site["grid_to_ground_factor"]
    u = (float(easting) - site["local_origin_easting"]) / factor
    v = (float(northing) - site["local_origin_northing"]) / factor
    theta = math.radians(site["rotation_deg"])
    c, s = math.cos(theta), math.sin(theta)
    dx = u * c - v * s
    dy = u * s + v * c
    grid_e = site["grid_origin_easting"] + dx
    grid_n = site["grid_origin_northing"] + dy
    return grid_e, grid_n


def project_xy_to_target(
    easting: float,
    northing: float,
    *,
    project_crs: str,
    local_site: dict | None,
    target_crs: str,
) -> tuple[float, float]:
    """Convert stored project coordinates to another CRS.

    When a local-site/modified-ground system is enabled, SurveySync first reverses the
    local affine ground transform back to grid coordinates, then asks PROJ to perform
    the CRS transformation. This keeps project-local values and geodetic transforms
    conceptually separate and auditable.
    """
    if not project_crs:
        raise ValueError("Project coordinate system is not set.")
    grid_e, grid_n = local_to_grid(easting, northing, local_site)
    if str(target_crs or "").strip() in {"", project_crs}:
        return grid_e, grid_n
    transformed = transform_xy(grid_e, grid_n, project_crs, target_crs)
    return float(transformed["x"]), float(transformed["y"])
