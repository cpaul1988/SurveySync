# SurveySync 9.4 Open-Source Integration Plan

## Scope

This plan covers repositories forked under `cpaul1988` on September 26, 2026 and identifies what can safely and usefully inform SurveySync 9.4.

SurveySync should prefer small, reviewable adaptations and optional bridges over importing entire external applications. Existing SurveySync project provenance, audit, review gates, CRS/unit behavior, Ronald/EDSI workflows, and source-evidence protections remain authoritative.

## Recommended integrations

### PyMap3D — direct algorithm/reference use

Repository: `cpaul1988/pymap3d`  
Upstream: `geospace-code/pymap3d`  
License: BSD-2-Clause

High-value SurveySync uses:

- geodetic <-> ECEF
- ECEF <-> ENU/NED
- geodetic <-> local tangent-plane coordinates
- azimuth/elevation/slant-range calculations
- GNSS baseline vector review
- independent validation fixtures for pyproj-backed transformations

9.4 target: add a **GNSS Local Frame** tool in ControlSync/GISSync with explicit ellipsoid/CRS context and round-trip QA. Prefer small attributed adaptations or independent implementation validated against PyMap3D rather than adding a large dependency surface.

### Surveyor — direct algorithm/reference use

Repository: `cpaul1988/Surveyor`  
Upstream: `pejovic/Surveyor`  
License: MIT

The R package covers 1D/2D network design, least-squares adjustment, coordinate transformations, reliability measures, error-ellipse visualization, and deformation analysis.

SurveySync 9.3.2 already has a separate 2D least-squares network adjustment. 9.4 should use Surveyor as an independent reference for:

- epoch-to-epoch deformation analysis
- stable-point determination
- 1D/2D deformation significance tests
- network design / observation-plan simulation
- reliability visualizations and review tables

Do not replace Ronald's existing best-three ControlSync workflow.

### GDAL/OGR — optional external format bridge

Repository: `cpaul1988/gdal`  
Upstream: `OSGeo/gdal`  
License: MIT-style core with bundled components carrying their own notices.

High-value SurveySync uses:

- vector/raster format discovery
- conversion through `ogr2ogr` / `gdal_translate`
- GeoPackage, GeoJSON, KML/KMZ, DXF and additional GIS interchange
- dataset metadata inspection
- raster/georeferencing support for future plat/map workflows

9.4 target: add a **GDAL Bridge** that detects an existing GDAL/QGIS/OSGeo4W installation and exposes available drivers. Do **not** bundle the entire GDAL stack in the SurveySync installer yet. SurveySync native import/export remains the fallback when GDAL is unavailable.

### Leaflet — local interactive map UI

Repository: `cpaul1988/Leaflet`  
Upstream: `Leaflet/Leaflet`  
License: BSD-2-Clause

High-value SurveySync uses:

- local WebView map preview
- point/control-network visualization
- alignment/station-offset visualization
- rod-height candidate spatial review
- parcel/boundary/COGO preview
- layer visibility and feature selection

9.4 target: vendor a pinned Leaflet release locally with attribution and no CDN dependency. The first map should be a reusable Map Preview component shared by COGOSync, ControlSync, GISSync, and TopoSync.

### PROJ — continue through pyproj

Repository: `cpaul1988/PROJ`  
Upstream: `OSGeo/PROJ`  
License: MIT-style

SurveySync already uses pyproj/PROJ as the authoritative CRS transformation engine.

9.4 target:

- expose richer CRS/operation metadata
- datum/coordinate-operation inspection
- transformation accuracy and area-of-use display
- preserve pyproj as the Python integration layer rather than adding a second native PROJ integration.

### GeoPandas — patterns and optional advanced backend

Repository: `cpaul1988/geopandas`  
Upstream: `geopandas/geopandas`  
License: BSD-3-Clause

Useful for:

- tabular/spatial joins
- geometry + attribute workflows
- GeoPackage/GeoJSON/Parquet patterns
- batch geoprocessing and reporting

Recommendation: do not make GeoPandas a mandatory 9.4 runtime dependency. Its dependency stack is comparatively heavy. Use it as a reference and consider an optional advanced-data backend later.

## Reference / external-bridge only

### QGIS

Repository: `cpaul1988/QGIS`  
Upstream: `qgis/QGIS`  
License: GPL-2.0

Useful references:

- layer tree and map UI
- processing-tool UX
- CRS selection
- symbology/label concepts
- provider architecture

Do not copy QGIS GPL code into SurveySync unless the project intentionally accepts the resulting GPL obligations. A future optional `qgis_process` bridge may call a separately installed QGIS.

### GRASS GIS

Repository: `cpaul1988/grass`  
Upstream: `OSGeo/grass`  
License: GPL-2.0-or-later

Useful references:

- terrain/surface processing
- raster/vector QA
- topology
- hydrology/DTM workflows

Do not embed GRASS GPL code in SurveySync. A separately installed external-process bridge can be evaluated later.

### GeoEasy

Repository: `cpaul1988/GeoEasy`  
Upstream: `zsiki/GeoEasy`  
License: GPL-2.0

Useful references:

- survey calculation workflows
- network adjustment UX
- DTM concepts
- regression calculations
- field-survey data organization

Reference only. Do not copy GPL implementation code into SurveySync.

## Idea-only / no code reuse

### TitleDesk

Repository: `cpaul1988/titledesk`  
Upstream: `THE-HARNESS-LAB/titledesk`  
License: commercial; all rights reserved; no derivative works.

Do not copy code, binaries, assets, or protected implementation details.

General product/workflow ideas that are independently implementable:

- provenance-linked extracted values
- proposal -> review -> acceptance workflow
- duplicate-safe content hashing
- monotonic progress reporting
- client workbook/template mapping
- append-only audit concepts
- local-first data handling
- deliverable package assembly

SurveySync already implements several of these independently. A **ReportSync Template Mapper** is the most useful remaining product concept, implemented from SurveySync's own code.

### Buzz

Repository: `cpaul1988/buzz`  
Upstream: `block/buzz`  
License: Apache-2.0

Already reviewed for 9.3.2. Continue using architectural ideas around auditability, workflow state, release discipline, and service boundaries. Do not import its unrelated Nostr/Postgres/Redis/chat stack.

## Proposed 9.4 feature order

1. New SurveySync brand asset system.
2. Shared local Map Preview component using pinned Leaflet.
3. GNSS Local Frame / ECEF-ENU tools validated against PyMap3D.
4. ControlSync epoch deformation analysis validated against Surveyor.
5. GISSync optional GDAL driver/format bridge.
6. Rich CRS operation metadata through pyproj/PROJ.
7. ReportSync Template Mapper.
8. Later: optional QGIS/GRASS external processing bridges.

## Release / licensing requirements

- Add every directly used third-party project to `THIRD_PARTY_NOTICES.md`.
- Pin vendored versions/commits.
- Add independent numerical regression fixtures before exposing survey computations.
- Never silently modify source survey evidence.
- External GPL tools must remain separately installed unless SurveySync intentionally changes its licensing/distribution model.
- Commercial/no-derivatives repositories are idea-only.
