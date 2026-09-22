# SurveySync v9.2.5 BetaCandidate Release Notes

SurveySync 9.2.5 combines the planned correctness/diagnostic hardening pass with the new Control Survey workspace requested after Ronald's Trimble Business Center workflow review. It intentionally leaves the large 9.3.0 API-router modularization for the next major refactor.

## Control Survey workspace

ControlSync now follows a simplified project-first workflow instead of centering the operator on a manual three-shot form:

1. Create/open the SurveySync project.
2. Choose the project coordinate system from the locally installed EPSG/ESRI PROJ library using an ESRI-style folder browser (Projected / Geographic, State Plane by state, UTM by datum family) or search by name/WKID.
3. Optionally enable **Local Site / modified-ground** settings using explicit grid and local origins, a grid-to-ground factor and clockwise rotation.
4. Load the complete repeated-control dataset. TBC-style `P,N,E,elev,Code` headers are recognized; labels such as `7A`, `7B`, `7C` are grouped as Control `7` while the original shot labels remain immutable. The same grouping rule is also applied when an export puts full shot labels in a `control_id` column, so `100A`, `100B`, `100C` become one Control `100`, not three separate controls. Existing project databases with the older split IDs are repaired automatically as metadata-only normalization.
5. Review all observations in a spatial map, Project Explorer and observation table.
6. Run every control through Ronald's validated arithmetic-average/residual method. Every possible three-shot combination is evaluated; the strongest passing triplet is selected and preserved with full provenance.
7. Export accepted controls and a separate reshoot list. If Control 7 has used 7A/7B/7C, the default three requested reshoots are 7D/7E/7F; likewise 100A/100B/100C continue as 100D/100E/100F rather than double-lettering from the shot label.
8. Control grouping also performs a configurable horizontal spatial cross-check (automatic default: 0.25 ft or 0.075 m). Example: `1A` + `1B` with nearby `2C` is flagged as a probable misnumber; if the cluster has a clear repeated-ID majority and suffix `C` is unused, QC associates that observation with Control `1` as inferred `1C` without renaming or rewriting the raw `2C` source observation. Conflicting/tied clusters remain REVIEW-only.

Default Control Survey QC tolerances are **0.045 ft horizontal** and **0.045 ft vertical**. They remain user-editable project/run inputs rather than hidden constants. The existing single-control and exact three-point workbook tools remain under Advanced / Manual Control Tools.

### Field-observation validity checks

Control Survey QC can now enforce field-observation requirements in addition to coordinate residuals. The default Control Survey workspace requires the selected three shots to be at least **60 minutes apart**, each shot to contain either **300 or more epochs OR at least 5 minutes of occupation**, and each shot to use **at least 5 satellites**. TBC/custom CSV exports may supply shot time, epoch count, duration and satellite count using common header names; those values are stored in the project database with the raw observation.

Explicit failures disqualify that candidate triplet. If required metadata is missing, the control is marked **REVIEW / UNVERIFIED** rather than fabricating a pass or a reshoot. Older project rows are migrated with `observed_time_provided=0`, so historical import timestamps are not mistaken for real field observation times. The strict requirement is visible in the UI and can be disabled only for legacy/unverified analysis.

## Direct Trimble JOB / JobXML control intake

ControlSync's **Load Control Survey Data** action now accepts `.job`, `.jxl`, and `.xml` in addition to CSV/TXT/TSV. A `.job` is converted with Trimble's installed ASCII File Generator using the existing official SurveySync conversion path; the immutable original JOB remains the project source evidence and the derived JobXML is stored under the project-derived ControlSync workspace.

Reduced Point ID/Northing/Easting/Elevation/Code records feed the same naming, spatial-grouping, field-QC and all-triplet best-three pipeline as delimited control files. SurveySync now supports both normal JobXML `Reductions` and TBC-style JobXML where `Reductions` is empty but usable points are stored under `InventoryData`. Non-shot PRS/reference/base points are retained in the immutable JXL source but excluded from repeated-control QC groups. SurveySync also performs best-effort extraction of GNSS occupation metadata from JobXML FieldBook records, including shot time, epoch count, observation duration and satellite count. Missing vendor metadata remains UNVERIFIED rather than being fabricated.

## Coordinate System and Local Site settings

New-project flow now immediately opens Coordinate System / Local Site setup. The CRS picker browses the installed PROJ database offline using Projected and Geographic folders, including State Plane by state and UTM by datum family, while retaining free-text EPSG/ESRI search. SurveySync stores the underlying grid CRS separately from optional Local Site settings so project/ground coordinates and geodetic transformations remain auditable.

The Local Site model in 9.2.5 is an explicit, reversible modified-ground transform consisting of:

- grid origin Northing/Easting,
- local/ground origin Northing/Easting,
- grid-to-ground scale factor, and
- clockwise rotation.

SurveySync never infers a ground factor or rotation from loaded control data. This is intentionally a transparent modified-ground transform, not a claim to reproduce every TBC site-calibration/geoid capability.

## Control QC provenance and outputs

For each control, SurveySync records every evaluated candidate triplet, ranking, selected triplet, source observation IDs, residuals, active immutable solution revision, tolerances and coordinate context. A failed control preserves its closest candidate for review but is placed on the reshoot list rather than silently adjusted.

The default deliverables are:

- Accepted Control CSV,
- Reshoot List CSV, and
- Control QC XLSX with run metadata, CRS/units and Local Site settings.

Accepted-control output includes Point/Control ID, Northing, Easting, Elevation, Code/Description, residuals, source observations, numbering warnings, field-QC status/minimum time gap and overall QC status. Reshoot/review output includes field failures and missing-metadata details.

## Custom control exporters

ControlSync now supports reusable accepted-control export profiles. Operators can choose fields such as Point/Control ID, N/E/Z, Code, residuals, source observations, QC status, WGS84 latitude/longitude and output CRS. Profiles are saved in the project database and can be loaded again.

Coordinate output defaults to the project's active coordinate system / Local Site. WGS84 latitude/longitude is available explicitly, and a different projected CRS can be selected for a specific deliverable. SurveySync reverses the Local Site transform back to the underlying grid before a PROJ transformation. Geographic exports use latitude/longitude headers rather than placing angular values under Northing/Easting labels.

## Coordinate-sanity correctness fix

`surveysync/coordinate_sanity.py` now validates Northing/Easting as one row-aligned pair. Rows with a non-finite value on either axis are excluded from geometric statistics together and reported by their real PointID. Outlier distances remain attached to the same row/PointID throughout the calculation. The remote-point threshold also no longer depends on total project span, which could previously hide a very remote point by inflating the threshold.

SurveySync still never swaps, transforms, or repairs coordinates automatically; these checks only create review evidence.

## Error visibility

The SurveySync core now has its own rotating persistent log under the normal SurveySync logs directory. Core configuration, snapshot/recovery, source preservation, QA-rule/profile loading, reporting, comparison, notifications, GIS scoring, local-AI fallbacks, and route-level best-effort operations now log diagnostic context instead of using blind `except Exception: pass` handlers. FieldBookSync state backup/recovery persistence received the same treatment.

## Static quality build gate

Windows/source builds run `scripts/validate_static_quality.py`. The gate prevents new blind broad-exception passes, caps broad Exception-handler growth, blocks `eval`/`exec`, `shell=True`, pickle imports, mutable defaults, duplicate route registrations, duplicate module-level function names, and common committed credential patterns. It also freezes the size/route count of `surveysync/router.py` and `fieldbook_sync/app.py` until the planned 9.3.0 domain split.

## GISSync Trimble Browse reliability

FBR-0015 is fixed in this source: the GISSync Trimble JOB/JobXML Browse button now uses the same resilient picker path as the rest of SurveySync. If the pywebview native dialog fails, SurveySync falls back to the local Windows/Tk file picker instead of appearing to do nothing.

## Retained behavior

9.2.5 retains the 9.2.4 one-project/one-database architecture and Project Data Manager, 9.2.3 append-only Control Survey Database and universal Browse changes, 9.2.2 feedback compatibility fix, 9.2.1 Operations Center, and 9.2.0 active revision management.
