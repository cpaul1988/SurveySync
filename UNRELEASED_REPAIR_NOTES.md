# Unreleased repair candidate — verified 9.4 audit defects

Corrects repeat LandXML import, PointID header handling, invalid numeric input, exact-closure JSON, mixed-unit pipe grades, large-coordinate polygon precision, blocked navigation/Exit commands, native shutdown, damaged-ledger recovery, and manual Ron control repeat/identity/code output.

Adds explicit level-book row-layout selection without changing Ron's reduction formulas. Preserves the last valid manual control result on failed recalculation and keeps original survey data/report history.

See `docs/VERIFIED_AUDIT_REPAIRS.md` and the repair PR for evidence and limits. This is not published 9.4.0 Beta.4 or a new Stable release. The existing version stamp remains for unreleased regression testing only. Do not distribute the candidate as the previously approved installer.
