# SurveySync Known Issues / Validation Limits

- Field Note Profiles guide interpretation; they do not guarantee handwriting recognition accuracy. Real field-book review remains required.
- Auto profile detection is performed during analysis. The v9.1.3 pre-analysis preview intentionally does not claim a confidence score before OCR/vision has inspected the page.
- `BRT_STANDARD` is BRT-aware but SurveySync does not claim a deterministic OpenCV circle/leader detector.
- Direct proprietary Trimble `.job` conversion requires the official Trimble ASCII/File and Report Generator on Windows. `.jxl`/JobXML can be parsed directly.
- Windows installer compilation requires Inno Setup 6. The build helper searches per-user and Program Files locations.
- Optional local OCR/vision runtimes still require real-machine smoke testing after installation.
- `.fnp` training examples can contain page imagery; treat exported bundles as project/client data even though prompt summaries intentionally omit raw prior values.

- v9.2.1 Import Staging is integrated with the canonical point-file path first; specialized legacy Control/GIS/FieldBook import screens remain direct workflows for compatibility and should be migrated to the shared staging framework in later releases.
- The v9.2.1 project map is a visual-QC overview, not a full GIS renderer and not a coordinate transformation engine.
- Recovery snapshots are bounded safety copies, not a substitute for normal project backups/versioned storage.

## v9.2.3 ControlSync reference limitation

The older generic arithmetic/weighted Control Survey Database workflow remains available for compatibility. v9.2.5 adds the TBC-inspired project/load/map/export workflow and Ronald's validated best-three QC behavior, but SurveySync still does not claim to reproduce Trimble Business Center's full GNSS/network-adjustment engine, site calibration, or proprietary report logic.

## v9.2.4 database-manager boundaries
Project Data Manager is intentionally not a general SQLite editor. Deleting immutable evidence, altering audit rows, and directly editing calculated solution tables are not supported. FieldBookSync still keeps some module-specific working JSON/state under `Modules/FieldBookSync`; the shared DB is the project-wide survey foundation, not a forced replacement for every module cache in this release.

## v9.2.5 hardening boundaries

Historical 9.2.5 limitation: application/router modules were monolithic and silent broad handlers remained. In 9.3.0, domain extraction reduces those modules, orchestration growth is frozen again, and all 22 silent FieldBookSync broad handlers log recovery failures. Broad catches and compatibility coupling still require incremental cleanup.

## v9.2.5 Control Survey / Local Site boundaries

The Local Site model is a transparent affine modified-ground transform (one scale factor, clockwise rotation, grid/local origins). It is not a full TBC site calibration, geoid/vertical-datum engine, GNSS network adjustment, or least-squares localization. Production use should be validated against known grid/ground control before relying on a newly entered Local Site definition.

The Control Survey loader accepts delimited repeated-control files plus Trimble `.job` and `.jxl/.xml`. JobXML can be parsed directly, including TBC exports with points under `InventoryData`; proprietary binary `.job` still requires Trimble's official converter. Direct raw-GNSS network adjustment inside ControlSync is not claimed in 9.2.5.

### Control field metadata boundary
Strict field QC can only verify what the source export provides. If shot time, epochs/duration or satellite count are omitted, SurveySync reports the selected candidate as UNVERIFIED/REVIEW instead of inferring values. Time-only exports can validate spacing within a 24-hour clock; include the observation date when shots span multiple days.

- **Trimble JOB converter dependency:** direct binary `.job` intake requires Trimble's installed ASCII File Generator / File and Report Generator. JobXML `.jxl/.xml` can be read directly. FieldBook occupation metadata varies by Trimble Access/JobXML generation; unavailable time/epoch/duration/satellite fields remain UNVERIFIED and are never synthesized.

- FBR-0015 Trimble GISSync Browse-button failure is fixed in 9.2.5 source with native-dialog fallback; binary `.job` conversion still requires Trimble's official converter.

## v9.2.6 ControlSync boundaries

- A JXL can only supply GNSS occupation fields that are actually present. TBC InventoryData-only exports with an empty FieldBook cannot verify DOP, satellites, shot times, epochs/duration or receiver/antenna evidence.
- JobXML tag names vary by Trimble Access generation/export style. The reader supports broad aliases and never invents missing values, but a real raw Access JXL remains the final interoperability test for a specific controller/export version.
- Direct `.job` binary decoding is intentionally not reverse-engineered; official Trimble conversion components are used when `.job` must be converted. Direct `.jxl` needs no TBC.
- The CRS browser mirrors documented ArcGIS coordinate-system folder organization over the EPSG/ESRI catalog available through PROJ. Esri's proprietary installed-folder metadata is not exposed to SurveySync.


## 9.3.0 engineering hardening

See `ENGINEERING_STANDARDS.md` and the root `RELEASE_NOTES_v9_3_0.md` for shared release gates, dependency locks, domain extraction, diagnostics and standalone TopoSync rod-height range QC. Windows acceptance and distribution signing remain outstanding.


### 9.3.0 TopoSync range QC

Standalone point import, editable code classifications, feature-chain range detection, evidence reports and reviewed-copy exports are implemented in `surveysync/topo` and `surveysync/static/topo_qc.js`. See [TopoSync workflow and limits](TOPO_ROD_HEIGHT_QC.md). Synthetic regression coverage is in `tests/test_topo_rod_ranges.py`; real field and Windows acceptance remain pending. Supplied branding replaces the product globe/installer assets.

## v9.3.1 validation boundaries

- Survey Data Inspector is a preflight/normalization aid, not a coordinate-transformation engine. A displayed project CRS/units label is context, not proof that an external source was authored in that CRS.
- Inspector remote-coordinate outliers are heuristic review flags. They are not proof of a survey blunder and do not alter source data.
- Binary Trimble `.job` inspection still depends on the official Trimble conversion component; JXL/JobXML can be parsed directly.
- Interrupted-session recovery only offers automatic restore when the interrupted project's path matches the currently open project and a recovery snapshot exists. Restore remains an explicit human action.
- Support Center automatic error retry is bounded/backed off and depends on a configured reachable tracker endpoint. Local diagnostic records remain available when sync fails.
- TopoSync review-history calibration is advisory. It does not self-train the rod-height detector, change thresholds automatically, or make a statistical probability claim.
- Real field-verified positive and negative rod-height datasets are still required to validate production false-positive/false-negative behavior.

