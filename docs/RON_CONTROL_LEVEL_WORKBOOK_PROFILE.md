# Ron Control / 3-Wire Workbook Profiles — SurveySync v9.1.0

## Authoritative source workbooks

SurveySync v9.1.0 was validated against the two workbooks supplied by Ron/CP on 2026-09-13:

- `3 Point Control Averaged Template.xlsx`  
  SHA-256: `5ac2de69de57b6c687d9b2466d134c95cbab4b098ca846a8492d102dcfeb911c`
- `3 Wire Level Loop Template.xlsx`  
  SHA-256: `65f08aa550822dc1ccc0b37165682db377f492b74dfd6ed328e010c650556b96`

The source workbooks are not required at runtime. Their formulas were transcribed into deterministic, tested SurveySync services so calculations can be reproduced and audited without modifying the original survey evidence.

## 3-point control profile

For each final control point, exactly three source survey shots are used. The workbook looks up each source PointID in `Survey Data` and computes:

- Final Northing = `AVERAGE(Northing A, Northing B, Northing C)` — workbook `K2`
- Final Easting = `AVERAGE(Easting A, Easting B, Easting C)` — workbook `L2`
- Final Elevation = `AVERAGE(Elevation A, Elevation B, Elevation C)` — workbook `M2`
- Horizontal residual per shot = `SQRT((Northing-AvgN)^2 + (Easting-AvgE)^2)` — workbook `F2:F4`
- Vertical display: A/B use `Elevation-AvgElevation`; C uses `AvgElevation-Elevation` exactly as the workbook does — workbook `H2:H4`
- Output code is inherited from the first/A shot — workbook `N2=E2`

SurveySync retains a conventional signed `dz = Elevation-AvgElevation` for tolerance QC while separately preserving the workbook's displayed C-row sign convention. Source PointIDs and each source observation remain traceable in the audit trail.

## 3-wire level profile

The workbook reduces each three-wire observation using:

- Averaged plus/backsight = `AVERAGE(upper, middle, lower)` — example `C4=AVERAGE(D3:D5)`
- Averaged minus/foresight = `AVERAGE(upper, middle, lower)` — example `E7=AVERAGE(F6:F8)`
- Stadia plus = `(upper-lower) * 100` — example `H4=(D3-D5)*100`
- Stadia minus = `(upper-lower) * 100` — example `I7=(F6-F8)*100`
- Height of instrument = prior/start elevation + averaged backsight — example `G5=B3+C4`
- Next point elevation = height of instrument - averaged foresight — example `G8=G5-E7`
- Setup stadia balance = backsight stadia - foresight stadia — example `H8=H4-I7`
- Close = computed ending elevation - starting benchmark elevation — workbook `I87=G86-B3`

The workbook provides reduction and closure math but **does not contain a closure-adjustment formula**. Therefore the Ron workbook profile defaults to **No adjustment**. SurveySync may separately apply an explicitly selected deterministic adjustment (`setups` or `distance`), but that adjustment is labeled as SurveySync logic and is not represented as Ron's workbook method.

## Professional-review rule

Raw observations are never overwritten. OCR/AI-extracted level entries remain reviewable evidence until accepted. Calculated solutions are derived revisions with the calculation profile, parameters, source records, software version, timestamp and review/audit history.


## 9.3.0 engineering hardening

See `ENGINEERING_STANDARDS.md` and the root `RELEASE_NOTES_v9_3_0.md` for shared release gates, dependency locks, domain extraction, diagnostics and standalone TopoSync rod-height range QC. Windows acceptance and distribution signing remain outstanding.
