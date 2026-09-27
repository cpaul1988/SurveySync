# pySurveying Independent Validation Engine

## Purpose

SurveySync uses a second control-network calculation path to catch numerical,
convention, and implementation errors before a network adjustment is trusted.

The production result still comes from `surveysync/network_adjustment.py`.
The independent validator lives in `surveysync/pysurveying_reference.py`.

The validator is based on the MIT-licensed pySurveying project's public
least-squares and quality-control behavior, while using SurveySync's explicit
northing/easting conventions.

## Why the second solver is genuinely different

The two calculations intentionally do not share the same numerical machinery.

| Calculation | Production SurveySync | Independent validator |
|---|---|---|
| Linearization | numerical central-difference Jacobian | analytic observation derivatives |
| Correction solve | pseudoinverse | NumPy least-squares |
| Network observations | distance, azimuth, direction, angle | distance, azimuth, direction, angle |
| Robust option | Huber | Huber |
| QC | sigma0, redundancy, standardized residuals, ellipses | same outputs calculated independently |

This reduces the chance that one implementation defect is repeated in both
calculations.

## API behavior

`POST /api/v9/control/network-adjust` continues to return the normal native
adjustment result and now includes an `independent_validation` object.

Validation status:

- **PASS** — native and reference values agree within the configured numerical
  tolerances.
- **REVIEW** — both calculations ran but at least one comparison exceeded a
  tolerance.
- **UNAVAILABLE** — the native adjustment succeeded but the independent
  calculation could not be completed.

An independent-validator failure does not discard or replace the native
calculation. It is recorded for review.

## Values compared

The automatic cross-check compares:

- adjusted horizontal coordinates;
- normalized observation residuals;
- observation redundancy numbers;
- unit-weight standard deviation (sigma0);
- 95% error-ellipse semi-major and semi-minor axes;
- convergence state.

The validator also returns the maximum observed difference for the major
comparison groups so a reviewer can see how close the two calculations were.

## Default comparison tolerances

The reference adapter currently uses these numerical agreement tolerances:

- coordinate difference: 0.0001 project linear unit;
- normalized residual difference: 0.0001;
- redundancy difference: 0.0001;
- 95% ellipse-axis difference: 0.0001 project linear unit;
- sigma0 difference: 0.0001.

These are implementation-comparison tolerances, not field acceptance
tolerances and not a substitute for the project's governing survey standard.

## Data snooping

The reference module also provides repeated standardized-residual screening.
It can identify observations that deserve review and can show which observation
would be excluded in a trial re-adjustment.

It never deletes, edits, or silently excludes original survey evidence.
Any proposed exclusion requires survey review.

## Provenance and licensing

Upstream project: https://github.com/hujinghaoabcd/pySurveying

Upstream version evaluated: 0.3.0

License: MIT

Copyright: Copyright (c) 2026 Jinghao Hu

SurveySync attribution and the required MIT notice are preserved in
`THIRD_PARTY_NOTICES.md`.

## Production rule

The independent validator is a QC layer, not a professional judgment engine.
A REVIEW status should lead to investigation of conventions, stochastic
assumptions, constraints, observation entry, geometry, and software behavior
before a result is accepted.
