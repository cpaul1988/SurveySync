# ReportSync Excel Template Mapper

## Purpose

The Template Mapper lets SurveySync populate company/client Excel deliverables
without hard-coding every workbook layout.

The source workbook remains immutable. Mapping configuration is stored separately and
rendering always creates a new workbook.

## Supported templates

- `.xlsx`
- `.xlsm` (VBA is preserved by openpyxl when rendering)

The current mapper supports scalar cells and one repeating canonical-point table.

## Placeholders

SurveySync recognizes text placeholders in the form:

`{{project.name}}`

Supported scalar context includes:

- project ID, name, number, client, CRS, horizontal/vertical units and revision;
- generated UTC/date/product;
- counts of points, immutable sources and open QA issues;
- audit-chain verified state, head hash and event count.

A cell containing exactly one placeholder can be learned automatically as a scalar
cell mapping when the template is registered. Placeholders embedded in text are also
replaced during rendering, for example:

`Client: {{project.client}}`

## Point tables

A reusable mapping can declare:

- worksheet;
- first data row;
- Excel column to canonical-point field mappings.

Supported point fields are PointID, Northing, Easting, Elevation, Description,
PointClass, ReviewState, CRS and project units. Formatting from the first template
row is copied down as rows are populated.

## Source and output provenance

Registering a template imports the original workbook into the immutable ReportSync
source registry. Deleting a mapping does not delete that source evidence.

Rendered workbooks are registered as `DRAFT` ReportSync deliverables with:

- template ID;
- immutable template source ID and SHA-256;
- mapping used;
- point count;
- render timestamp.

DRAFT status deliberately prevents ReportSync's FINAL-deliverable notification policy
from being triggered accidentally.

## API

- `POST /api/v9/reports/templates/inspect`
- `GET /api/v9/reports/templates`
- `POST /api/v9/reports/templates`
- `POST /api/v9/reports/templates/mapping`
- `POST /api/v9/reports/templates/render`
- `POST /api/v9/reports/templates/delete`

## Boundary

The mapper does not infer the professional meaning of unlabeled cells. Templates that
do not use placeholders require an explicit mapping. Formulas and workbook layout
remain the responsibility of the template author; SurveySync only writes mapped cells
and point-table values into the rendered copy.
