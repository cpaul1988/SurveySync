# Optional QGIS / GRASS GIS Processing Bridges

## Architecture

SurveySync can call an installed QGIS or GRASS GIS runtime as an external processing
engine. QGIS and GRASS are GPL applications; SurveySync does not vendor, embed, link
against, or import their application source code.

The bridges discover local executables and invoke them with an argument array and
`shell=False`.

## QGIS

SurveySync looks for `qgis_process` through:

- `SURVEYSYNC_QGIS_PROCESS`;
- PATH;
- common QGIS / OSGeo4W installation folders.

Supported bridge operations:

- runtime status/version;
- processing-algorithm listing;
- algorithm help;
- explicit algorithm execution with scalar parameters.

Algorithm IDs are validated before invocation. Parameter names are restricted to
simple processing identifiers, and parameter values must be strings, numbers,
booleans or null.

## GRASS GIS

SurveySync looks for a GRASS launcher through:

- `SURVEYSYNC_GRASS`;
- PATH;
- common GRASS / QGIS / OSGeo4W installation folders.

The first bridge uses GRASS temporary-project execution:

`grass --tmp-project <CRS> --exec <module> ...`

Only normal GRASS processing module families `g.*`, `r.*`, `v.*`, `db.*` and
`i.*` are accepted. SurveySync uses the active project CRS unless a CRS is explicitly
provided for the run.

## API

- `GET /api/v9/gis-bridges/status`
- `GET /api/v9/gis-bridges/qgis/algorithms`
- `POST /api/v9/gis-bridges/qgis/help`
- `POST /api/v9/gis-bridges/qgis/run`
- `POST /api/v9/gis-bridges/grass/run`

QGIS and GRASS runs are audited as external GIS processing events.

## Safety and production boundary

SurveySync does not execute user-supplied shell fragments or arbitrary executables
through these routes. External GIS processes can still create or modify output files
requested by the user; SurveySync does not treat those outputs as professionally
accepted survey data automatically.

QGIS and GRASS are optional. Their absence must not prevent SurveySync startup or
normal GISSync operation.

Upstream:
- QGIS: https://github.com/qgis/QGIS — GPL-2.0
- GRASS GIS: https://github.com/OSGeo/grass — GPL-2.0-or-later
