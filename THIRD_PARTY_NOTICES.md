# SurveySync Third-Party Notices

This file records third-party open-source code that is copied, adapted, vendored,
or materially used as an implementation reference in SurveySync.

SurveySync's own project license is a separate decision by the repository owner.
Nothing in this file changes the licensing terms of third-party projects.

## Cogokit

- Project: https://github.com/devinmlowe/cogokit
- Copyright: Copyright (c) 2026 Devin Lowe
- License: MIT
- SurveySync usage:
  - `surveysync/cogo_extended.py` adapts portions of
    `src/cogokit/solvers/horizontal_curve.py`.
  - SurveySync changes the public API to SurveySync naming/conventions, uses
    degrees at the API boundary, and returns plain dictionaries for FastAPI/UI use.

MIT License notice:

> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the condition that the copyright notice and
> permission notice are included in all copies or substantial portions.

The software is provided "AS IS", without warranty of any kind.

## Buzz

- Project: https://github.com/block/buzz
- User fork inspected: https://github.com/cpaul1988/buzz
- Copyright: Block, Inc. and contributors
- License: Apache License 2.0
- SurveySync usage:
  - No Buzz Rust source file is copied into SurveySync in this integration.
  - The append-only SHA-256 audit-chain design in `surveysync/audit.py` is
    architecturally inspired by Buzz's `crates/buzz-audit`.
  - The Beta-candidate / exact-artifact Stable-promotion workflow is informed by
    Buzz's desktop release/promotion separation.

See the upstream Apache-2.0 LICENSE for the complete terms.

## pySurveying

- Project: https://github.com/hujinghaoabcd/pySurveying
- Copyright: Copyright (c) 2026 Jinghao Hu
- License: MIT
- Current SurveySync usage:
  - Reference/validation target only; no pySurveying source code is copied in
    this integration branch.
  - Planned use is independent validation of least-squares control networks,
    residual statistics, redundancy numbers, data snooping, and error ellipses.

## jxl2txt

- Project: https://github.com/mrahnis/jxl2txt
- License: BSD 3-Clause
- Current SurveySync usage:
  - Reference/test-expansion target only; no jxl2txt source code is copied in
    this integration branch.
  - Planned use is to expand Trimble JobXML/XSLT regression cases around the
    existing SurveySync JobXML parser.

## Existing geospatial dependencies

SurveySync also relies on established third-party packages through its locked
Python dependency files. Their licenses remain governed by their respective
upstream projects. Important examples include pyproj/PROJ, Shapely/GEOS,
PyMuPDF, OpenPyXL, FastAPI, Uvicorn, and pywebview.

Before each public release, dependency locks and this notice file should be
reviewed together.
