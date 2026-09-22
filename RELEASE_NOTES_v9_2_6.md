# SurveySync 9.2.6 BetaCandidate Release Notes

SurveySync 9.2.6 is a ControlSync production-quality release built on the 9.2.5 hardening/JXL foundation.

## ControlSync

- Reads richer Trimble Access JobXML field-observation evidence when present: observation date/time, epochs, occupation duration, satellites, PDOP/HDOP/VDOP, fix/solution type, receiver model/serial, antenna type and antenna height.
- Keeps TBC inventory-only JobXML support. The importer diagnoses coordinate-only JXLs and identifies which field-QC evidence is unavailable.
- Can merge a raw Access JXL into already-imported project/grid control observations by PointID. Only missing observation metadata is enriched; N/E/Z are not replaced.
- Retains every candidate three-shot combination and selects the best passing triplet after coordinate and field-QC validation.
- Adds editable Control QC profiles, including 0.045 ft H/V defaults, spatial tolerances, 60-minute shot separation, 300 epochs or five minutes, minimum satellites, and optional DOP limits.
- Adds horizontal plus optional vertical spatial clustering, probable-misnumber review, and explicit Confirm / Reject / Reassign decisions without changing raw source labels.
- Adds richer observation filtering/table columns, status-aware map display, import diagnostics and Why? provenance.
- Adds a complete QC package ZIP with accepted control, reshoot list, XLSX workbook and machine-readable provenance.
- Adds duplicate/re-import diagnostics and additional control-observation database indexes for larger projects.
- Adds a ControlSync delimited-file header/mapping wizard. CSV/TXT/TSV imports now detect delimiter/header rows, recognize common survey/GNSS headings and units, preview source rows, ask the user to resolve ambiguous columns, and remember approved mappings per project/header signature. Headerless PNEZD/PNEZ-style control files receive safe synthetic columns and a reviewable default mapping. For safety, headerless mappings are reviewed on every import and are not silently reused from another same-width file.

## Coordinate systems and windows

- The CRS browser follows the documented ArcGIS/Esri organization: Geographic Coordinate Systems and Projected Coordinate Systems, with projected families including State Plane, UTM, National Grids, County Systems, State Systems, Continental and World where systems exist in the installed EPSG/ESRI catalog.
- State Plane browsing is datum -> state -> coordinate system, making systems such as NAD 1983 (2011) / Missouri East easier to locate.
- The Coordinate System picker opens substantially larger, is freely resizable, and remembers its last dimensions.
- SurveySync modal workflows use remembered resizable dialogs; FieldBookSync dialogs are resizable and remember their size as well.

## Source evidence rules

SurveySync never fabricates raw GNSS evidence. A TBC-exported JXL whose `FieldBook` is empty can provide project coordinates but cannot prove shot time, DOP, satellite count, occupation length, epochs or receiver metadata. Those values stay UNVERIFIED until a source containing them is imported or merged.

Direct `.jxl` reading does not require TBC. Proprietary `.job` conversion still uses Trimble's official conversion utility when available.

## Compatibility

Existing SurveySync projects are migrated to project DB schema 5 with the normal pre-migration safety backup. Raw source files and prior solution revisions remain unchanged.
