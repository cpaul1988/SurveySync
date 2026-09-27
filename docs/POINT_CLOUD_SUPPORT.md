# SurveySync Point-Cloud Support

## Scope

SurveySync 9.4 adds optional point-cloud support under TopoSync for LAS and LAZ/COPC
sources without making a heavy point-cloud runtime mandatory for normal SurveySync use.

## Capability tiers

### Built-in LAS metadata

SurveySync can inspect standard LAS 1.0-1.4 headers using only Python's standard
library. The built-in reader reports:

- LAS version;
- point format and record length;
- point count;
- scale and offset;
- XYZ bounds;
- VLR count;
- compressed-point flag;
- file size.

The built-in path reads the header only and does not load millions of point records.

### Optional laspy

If `laspy` is installed in the SurveySync runtime, the point-cloud module can use
it for richer LAS/LAZ metadata and bounded QA point sampling. LAZ reading still
requires a compression backend supported by the installed laspy environment.

SurveySync does not automatically install laspy because the core desktop application
must remain usable without optional point-cloud packages.

### Optional PDAL

If the `pdal` command-line tool is available on PATH, SurveySync can use
`pdal info` as a metadata fallback for compressed LAZ/COPC datasets.

SurveySync invokes PDAL with an argument list and never uses `shell=True`.

## Source preservation

`POST /api/v9/pointcloud/import` first inspects the source, then stores the
original LAS/LAZ file in SurveySync's immutable project Source registry under
TopoSync. SurveySync does not rewrite the original source.

A `POINT_CLOUD_IMPORTED` audit event records the selected reader, point count,
bounds, file type and source identity.

## API

- `GET /api/v9/pointcloud/status` — installed capability status.
- `POST /api/v9/pointcloud/inspect` — read metadata without importing.
- `POST /api/v9/pointcloud/import` — preserve source and audit metadata.
- `POST /api/v9/pointcloud/sample` — bounded QA preview when laspy is available.
- `GET /api/v9/pointcloud/sources` — list imported TopoSync LAS/LAZ sources.

Point sampling is deliberately capped at 10,000 records and is described as a QA
preview. It is not a random/statistical sample and is not used for survey acceptance.

## Production boundary

This module does not yet perform surface generation, contouring, ground
classification, registration, strip adjustment, or coordinate transformation of
point-cloud data. Those operations should use a reviewed PDAL/TopoSync processing
pipeline in a later phase.

The project CRS shown by SurveySync is context only. Importing a LAS/LAZ file does
not prove that its coordinates were authored in the project CRS.

## Upstream projects

- laspy: https://github.com/laspy/laspy
- PDAL: https://github.com/PDAL/PDAL

Both are treated as optional external capabilities. SurveySync does not vendor their
source code.
