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

Copyright (c) 2026 Devin Lowe

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

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
  - Reference/validation target only; no pySurveying adjustment source code is
    copied into SurveySync.
  - The MIT-licensed distance-control-network fixture is adapted into
    `tests/test_v932_network_adjustment.py` as an independent numerical
    cross-check of SurveySync's native least-squares engine.
  - pySurveying remains a reference for residual statistics, redundancy numbers,
    data snooping, robust adjustment, and error-ellipse expectations.

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
