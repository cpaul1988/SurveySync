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
    `src/cogokit/solvers/horizontal_curve.py` and the vertical-curve equations
    from `src/cogokit/solvers/vertical_curve.py`.
  - `surveysync/earthwork.py` adapts the cross-section/earthwork and slope-catch
    calculation approach from `src/cogokit/surveying/cross_sections.py` and
    `src/cogokit/surveying/stakeout.py`.
  - `surveysync/horizontal_alignment.py` adapts the tangent/circular-curve alignment
    geometry concepts from `src/cogokit/surveying/alignment.py` while using
    SurveySync's LEFT-positive offset convention.
  - `surveysync/landxml_io.py` adapts the supported LandXML 1.2 CgPoint, Parcel,
    and Alignment import/export structure from `src/cogokit/io/landxml.py`.
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
  - `surveysync/workflow_engine.py` adopts the declarative trigger/action
    separation as an architectural reference while remaining a local,
    SurveySync-native YAML engine with explicit human approval gates.

See the upstream Apache-2.0 LICENSE for the complete terms.

## pySurveying

- Project: https://github.com/hujinghaoabcd/pySurveying
- Copyright: Copyright (c) 2026 Jinghao Hu
- License: MIT
- SurveySync usage:
  - `surveysync/pysurveying_reference.py` implements a SurveySync-native
    independent validation path based on pySurveying's MIT-licensed adjustment
    and quality-control concepts.
  - The reference path uses analytic observation derivatives and
    `numpy.linalg.lstsq`, intentionally differing from SurveySync's production
    numerical-Jacobian solver so the two calculations can cross-check each other.
  - It independently compares adjusted coordinates, normalized residuals,
    redundancy numbers, sigma0, and 95% error-ellipse axes.
  - Review-only data snooping identifies possible gross-error observations
    without deleting or changing original survey evidence.
  - The MIT-licensed distance-control-network fixture remains adapted in
    `tests/test_v932_network_adjustment.py` for regression coverage.

MIT License notice:

Copyright (c) 2026 Jinghao Hu

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
OUT OF OR IN CONNECTION WITH THE SOFTWARE.

## jxl2txt

- Project: https://github.com/mrahnis/jxl2txt
- Copyright: Copyright (c) 2015, Michael A. Rahnis
- License: BSD 3-Clause
- SurveySync usage:
  - `surveysync/trimble_job.py` adopts jxl2txt's compatibility principle of
    tolerant JobXML intake while preserving SurveySync's native parser and
    official Trimble `.job` conversion path.
  - SurveySync does not copy jxl2txt's Click CLI or XSLT execution code and does
    not add lxml as a runtime dependency.
  - The 9.4 parser adds namespace/version independence, nested section discovery,
    encoding/BOM tolerance, preferred point-ID aliases, and a narrow safe
    text-recovery path for illegal control characters and bare ampersands.
  - `tests/test_v940_jxl_regression.py` provides SurveySync-owned regression
    fixtures for those compatibility cases.

BSD 3-Clause License notice:

Copyright (c) 2015, Michael A. Rahnis
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.
* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.
* Neither the name of Michael A. Rahnis nor the names of its contributors may
  be used to endorse or promote products derived from this software without
  specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.

## laspy (optional point-cloud capability)

- Project: https://github.com/laspy/laspy
- Upstream license: BSD-style 2-clause license
- SurveySync usage:
  - SurveySync does not vendor laspy source and does not require it for startup.
  - When laspy is already installed, `surveysync/pointcloud.py` can use it for
    richer LAS/LAZ metadata and bounded point-record QA sampling.
  - LAS header metadata remains available through SurveySync's standard-library
    reader when laspy is absent.

Upstream copyright notice:

Copyright (c) 2012, Grant Brown
Copyright (c) 2012, Howard Butler
Copyright (c) 2020, Thomas Montaigu

See the upstream LICENSE for the complete BSD terms.

## PDAL (optional point-cloud capability)

- Project: https://github.com/PDAL/PDAL
- Upstream license: BSD
- SurveySync usage:
  - SurveySync does not vendor PDAL source or binaries.
  - When the `pdal` CLI is already installed and available on PATH,
    `surveysync/pointcloud.py` can use `pdal info` as a metadata fallback for
    compressed LAZ/COPC sources.
  - PDAL is invoked without a shell and is not required for normal SurveySync
    startup or ordinary LAS header inspection.

Upstream overall PDAL copyright notice:

Copyright (c) 2025, Hobu, Inc.

See the upstream LICENSE.txt for the complete BSD terms.



## QGIS (optional external processing bridge)

- Project: https://github.com/qgis/QGIS
- License: GNU GPL v2
- SurveySync usage:
  - SurveySync does not vendor, embed, link against, or import QGIS application source.
  - `surveysync/gis_bridges.py` optionally discovers an installed `qgis_process`
    executable and invokes it as a separate process with `shell=False`.
  - QGIS remains an independently installed optional application.

See the upstream QGIS COPYING file for the complete GPL v2 terms.

## GRASS GIS (optional external processing bridge)

- Project: https://github.com/OSGeo/grass
- License: GNU GPL v2 or later
- SurveySync usage:
  - SurveySync does not vendor, embed, link against, or import GRASS GIS application source.
  - `surveysync/gis_bridges.py` optionally discovers an installed GRASS launcher
    and invokes validated GRASS modules as separate processes with `shell=False`.
  - GRASS remains an independently installed optional application.

See the upstream GRASS COPYING file for the complete GPL terms.

## pyproj / PROJ

- Project: https://github.com/pyproj4/pyproj
- Role: SurveySync's installed CRS/coordinate-operation dependency.
- SurveySync usage:
  - `surveysync/crs_diagnostics.py` exposes pyproj/PROJ metadata, area-of-use,
    operation-accuracy and grid-availability diagnostics.
  - SurveySync does not replace PROJ with hand-maintained CRS definitions.

## Existing geospatial dependencies

SurveySync also relies on established third-party packages through its locked
Python dependency files. Their licenses remain governed by their respective
upstream projects. Important examples include pyproj/PROJ, Shapely/GEOS,
PyMuPDF, OpenPyXL, FastAPI, Uvicorn, and pywebview.

Before each public release, dependency locks and this notice file should be
reviewed together.
