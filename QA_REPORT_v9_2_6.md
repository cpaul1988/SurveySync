# SurveySync 9.2.6 BetaCandidate QA Report

## Scope

ControlSync production hardening: richer Trimble Access JobXML metadata, dual-source evidence merge, reviewed spatial grouping, DOP-aware field QC, reusable QC profiles, control packages, resizable dialogs and an ArcGIS/Esri-aligned CRS browser.

## Automated regression

The maintained release command includes all `tests/` plus the retained FieldBookSync legacy suites. `tests/test_v926_control_production.py` specifically covers:

- rich Access JobXML metadata and DOP thresholds;
- TBC inventory-only diagnostics and raw-JXL metadata merge without coordinate replacement;
- vertical spatial tolerance and manual misnumber review overrides;
- persisted QC profiles;
- ArcGIS-style CRS folder families;
- resizable/remembered modal UI contracts;
- complete ControlSync QC package provenance;
- control CSV/TXT/TSV header detection, user-confirmed column mapping, learned per-project mappings, and headerless PNEZD defaults.

Existing v9.2.5 tests continue to cover real-world InventoryData-style JXL structure, A/B/C grouping, spatial typo inference, strict time/epochs-duration/satellite rules, all-triplet best-three selection and Trimble JOB converter integration.

## Release gates

Final source gate: **246 passed, 0 failed**. Static-quality validation passed with zero blind broad-exception passes in the SurveySync core and the frozen FieldBookSync baseline unchanged. Python compileall, SurveySync JavaScript syntax and FieldBookSync JavaScript syntax passed. The project template database is schema 5 with `PRAGMA integrity_check=ok` and no foreign-key violations. Both Windows launchers were cross-built as GUI-subsystem executables.

The required feedback check found FBR-0015 still newest; no FBR-0016 or unprocessed legacy form response was present before packaging.

## Field validation still required

A raw Trimble Access JXL with a populated FieldBook should be tested on Ron's real controller output before calling every vendor-specific GNSS tag mapping complete. Installer/update behavior remains a Windows field gate.

- Headerless mapping safety regression: generic `Column N` layouts are never auto-reused across imports; P/N/E/Z/description suggestions remain reviewable.
