# CRS Diagnostics

SurveySync uses pyproj/PROJ as the authoritative coordinate-reference and
coordinate-operation engine. The v9.4 CRS diagnostics layer exposes the evidence
behind a transformation instead of presenting a CRS code alone.

## Diagnostics

The engine reports:

- CRS authority, name, type, datum, ellipsoid and prime meridian;
- axis order, direction, units and conversion factors;
- CRS area of use;
- projected coordinate-operation method and published accuracy where available;
- all PROJ operations available between a source and target CRS;
- operations that are known but unavailable in the current runtime;
- transformation grids referenced by unavailable operations and whether each grid is available;
- whether PROJ reports the best-known operation as available;
- optional sample-coordinate transformation and source/target area-of-use checks.

Project diagnostics additionally compare the configured SurveySync horizontal
units with the horizontal axis unit reported by PROJ. A mismatch is a REVIEW
condition; SurveySync does not silently change the project units or CRS.

## Axis order

Authority definitions can use latitude/northing-first axis order. SurveySync's
public coordinate APIs intentionally use `always_xy=True`, so callers continue
to supply easting/longitude first and northing/latitude second. CRS diagnostics
surface an informational axis-order notice rather than silently changing this API
contract.

## Local site / modified ground

When a SurveySync Local Site is enabled, diagnostics report that state explicitly.
CRS transformation and local grid/ground transformation remain separate operations.
The local affine transform must be reversed to grid before a geodetic CRS operation.

## API

- `POST /api/v9/crs/profile`
- `POST /api/v9/crs/operations`
- `POST /api/v9/crs/project-diagnostics`

Running project diagnostics writes a `CRS_DIAGNOSTICS_RUN` audit event.

## Production boundary

A PROJ operation with a published accuracy is not a professional certification that
the project datum, epoch, vertical datum, localization, control or field procedures
are correct. Missing grids, area-of-use warnings and unit mismatches are review
signals. SurveySync does not auto-download transformation grids or silently select a
different project CRS.
