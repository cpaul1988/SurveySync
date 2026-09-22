# SurveySync v9.2.5 BetaCandidate QA Report

## Scope

- Coordinate-sanity row alignment and PointID attribution regression coverage.
- Non-finite Northing/Easting pair handling and remote-coordinate outlier regression coverage.
- SurveySync core exception-visibility audit, persistent logging, and static-quality gate.
- Project coordinate-system library and Local Site / modified-ground round-trip validation.
- TBC-style `P,N,E,elev,Code` control import and suffix grouping.
- Best-three combination QC at 0.045 horizontal / 0.045 vertical defaults.
- Accepted-control/reshoot generation, next-shot suffix generation, immutable solution provenance and candidate persistence.
- Custom control export profiles, Code/Description output, WGS84 export semantics and alternate projected-CRS validation.
- Field-observation metadata parsing and strict QC: 60-minute shot separation, 300 epochs OR 5 minutes, and at least 5 satellites.
- Full retained regression suite for SurveySync/FieldBookSync.

## Automated gates

The complete maintained source regression suite passed **234 tests with 0 failures**. `python -m compileall`, SurveySync and FieldBookSync JavaScript syntax checks, the release-documentation gate, and the static-quality gate all passed in the packaging environment.

The static gate reports **0** blind broad-exception passes in `surveysync`, a frozen FieldBookSync baseline of **22**, broad-handler ceilings of 144/149 respectively, no duplicate route registrations/module-level functions, no mutable default arguments, and no forbidden eval/exec, pickle, shell=True, or common committed-key patterns.

Focused v9.2.5 Control Survey tests verify:

- direct ControlSync JobXML intake preserves Point ID/N/E/Z/Code and available GNSS shot time, epoch count, occupation duration and satellite count;
- real TBC-style JobXML with empty `Reductions` falls back to `InventoryData`; non-shot PRS/reference points remain source evidence but are excluded from repeated-control QC groups;
- the CRS selector exposes Projected/Geographic folders, State Plane by state and UTM-by-datum navigation while retaining search;
- FBR-0015 Trimble GISSync Browse uses a resilient native-dialog fallback instead of silently failing;
- the ControlSync API accepts a `.job` source through the official converter adapter and immediately feeds the converted observations into strict Control QC;
- offline CRS-library search returns installed Missouri East definitions;
- Local Site grid→ground and ground→grid transforms round-trip numerically;
- project coordinate settings persist into the project database;
- `7A/7B/7C/7D` group as Control `7` while shot labels remain intact;
- `100A/100B/100C` also group as Control `100` when the full shot labels arrive in a `control_id` column;
- legacy project rows previously stored as separate `100A`/`100B`/`100C` control IDs are normalized to `100` before QC without modifying coordinates or source PointIDs;
- a failed `100A/100B/100C` control requests `100D/100E/100F`, not `100AA/100AB/100AC`;
- the passing best triplet excludes the deliberately bad fourth observation;
- a failing `8A/8B/8C` control requests `8D/8E/8F`;
- TBC-style `Code` survives into accepted-control output;
- QC runs and every candidate triplet are persisted;
- default accepted/reshoot CSV/XLSX deliverables are written;
- saved custom export profiles can be read back;
- geographic exports use Latitude/Longitude fields rather than mislabeled N/E angular values; and
- geographic CRSs are rejected as a Northing/Easting target export, directing the user to the explicit geographic mode instead;
- field metadata parses from common Time/Epochs/Duration/Satellites headers and persists in project SQLite;
- a compliant 60+ minute / 300-epoch-or-5-minute / 5+ satellite triplet passes strict field QC;
- a <60-minute spacing or <5-satellite observation disqualifies the triplet; and
- missing required field metadata produces REVIEW/UNVERIFIED rather than a false PASS.

## Windows Beta validation still required

- Build/install over the current 9.2.x Windows build.
- Create a new project and search/select the real project CRS from the library.
- Configure a known Local Site / modified-ground project and compare a known grid/local coordinate pair against a trusted survey package before relying on the transform for production.
- Load Ronald's real multi-shot control data and verify the spatial map/grouping.
- Compare SurveySync's selected best three, averages and residuals with Ronald's control workbook for representative PASS and RESHOOT controls.
- Verify next reshoot labels match the project's actual point-naming practice.
- Open the default Accepted Control / Reshoot outputs and a saved custom exporter profile.
- Exercise coordinate sanity with one non-finite axis value plus a known remote point; verify correct PointIDs and no source modification.
- Verify `surveysync.log` is written and included in diagnostics.
- Re-smoke project database/Data Manager, feedback Intake, snapshots, updater consent, and FieldBookSync Review.

## Boundary / non-claim

The Local Site implementation is an explicit affine modified-ground transform (origins + one grid-to-ground factor + clockwise rotation). 9.2.5 does **not** claim full Trimble Business Center site calibration, geoid modeling, GNSS network adjustment, or automatic derivation of ground parameters. Those require separate validated reference data/workflows.
