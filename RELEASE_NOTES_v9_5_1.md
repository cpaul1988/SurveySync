# SurveySync 9.5.1-beta.1 — CAD drawing and geometry review

Unpublished candidate based on Stable 9.5.0.

BoundarySync now includes CAD Drawing & Geometry QA: upload a DXF, choose units, confirm coordinate alignment, then review modelspace layers and entities alongside project points. Lines, polylines, curves, text and supported blocks retain their source identity. Unsupported content is listed explicitly.

Checks flag exact duplicate straight segments, zero-length segments, self-intersections, straight crossings and nearby endpoint gaps. Curved screening is approximate and labelled. An explicitly ordered open chain reports every join and closing gap against 0.10 international ft. Nothing is automatically snapped, closed or adjusted, even within tolerance.

Original DXF bytes are retained with SHA-256 and context. CSV/JSON review reports include findings, limitations and ordered closure. Imports run in a time-limited worker; stale project/point context is rejected.

Limits and workflow: docs/CAD_REVIEW.md. DWG, paperspace, full CAD typography, automatic corrections, snapping, curved inter-entity intersections and partial overlap detection remain outside this release. Windows acceptance must pass before publication or promotion.
