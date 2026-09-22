# SurveySync v9.1.1 Release Notes

## Beta candidate — field intake and FieldBook accuracy patch

SurveySync 9.1.1 is a focused v9.1 stabilization and workflow-completion build. It keeps the v9.1.0 survey-platform expansion and addresses the newest beta feedback before adding another large module release.

### Point Range — FBR-0009 + prior range feedback

- **Current Project Points** is now the default Point Range source. Every numeric PointID already loaded in the active SurveySync project is treated as occupied.
- Added an explicit **Choose Point File / Browse** workflow for PMs who need to evaluate a separate point file instead of the current project.
- File mode supports normal text survey point files and Trimble JobXML/JXL; Trimble `.job` can be used when the official Trimble ASCII File Generator is installed.
- Existing numeric PointIDs are never offered for reuse.
- Low-to-high remains the default. High-to-low and largest-capacity ordering remain available.
- Each run now creates matching **CSV, TXT, and XLSX** crew-allocation reports.
- This directly addresses **FBR-0009 — Point Range doesn't allow me to pick file** and completes the intent of FBR-0002/FBR-0006.

### Direct Trimble Access JOB / JobXML intake

- Added direct SurveySync intake for `.job`, `.jxl`, and `.xml` JobXML files.
- The original Trimble file is preserved in immutable SurveySync Source evidence.
- SurveySync does **not** reverse-engineer the proprietary `.job` binary. For `.job`, it locates Trimble's installed **ASCII File Generator / File and Report Generator** and creates a derived `Trimble JobXML` representation.
- Parsed JobXML grid points can be added to the canonical SurveySync point registry.
- Existing PointIDs are not overwritten. Conflicts are returned for review.
- JobXML metadata and small coordinate-system/environment hints are retained without silently making a professional CRS decision.
- FieldBookSync survey import, raw-job pairing, and FieldBookSync Point Range intake also recognize `.job` / `.jxl` / `.xml`.

### BRT standard FieldBook note intelligence

FieldBookSync now has explicit awareness of the standard BRT field-note sketch used in the supplied field book:

- structure/manhole circle;
- visible north orientation;
- structure PointID associated with the circle;
- individual leaders for each pipe/connection;
- dip, diameter, material, azimuth and notes kept with the correct leader;
- visual leader direction kept separately from the written azimuth;
- handwritten destination references such as `to 3394` retained as explicit topology rather than replaced by a nearest-point guess.

When an explicit destination exists, SurveySync gives that field evidence precedence and uses coordinates, written azimuth, drawn leader direction and reciprocal pipe direction only as independent QC checks. Disagreement is routed to review rather than silently corrected.

### Ron 3-point control deliverables

The validated Ron workbook calculation profile is unchanged. v9.1.1 completes the deliverable workflow:

- every Ron 3-point solve writes a detailed QC TXT report;
- a passing solution writes a **FINAL control TXT**;
- a failing solution writes a **GPS RESHOOT TXT** naming the source PointIDs that exceeded horizontal and/or vertical tolerance;
- solution ID, revision, source PointIDs and tolerances remain auditable.

### Feedback / beta validation

The shared Intake tracker was checked immediately before this build. **FBR-0009** is the newest entry; no later Intake item was present at build start.

RP successfully submitted FBR-0009 from SurveySync v9.1.0 and it reached the shared tracker. That provides an external success case after the earlier FBR-0008 HTTP 500 report. Local-first persistence and retry protections remain in place.

### Preserved v9.1.0 work

- Project Manager and one-click project switching.
- Native Windows GUI launcher / single-window correction.
- Ron 3-point and 3-wire workbook profiles.
- Evidence-first Windows AI + PaddleOCR-VL + targeted Qwen pipeline.
- UtilitySync/GIS/Control/Report foundations.
- Shared Check & Update flow and global themes.

### Beta release gates

This source build still requires final installed-Windows validation before Stable promotion, including direct `.job` conversion on a workstation with Trimble's converter installed, installed Paddle/local-AI smoke testing, and an end-to-end Check & Update test from v9.1.0 to v9.1.1.
