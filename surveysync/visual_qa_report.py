"""Complete, snapshot-bound review packages; no coordinate writes or implied approval."""

from __future__ import annotations

import csv
import hashlib
from html import escape
import io
import json
import re
from datetime import datetime, timezone
from zipfile import ZipFile, ZIP_DEFLATED

import fitz

from . import __version__
from .visual_qa import digest

MAX_REPORT_ROWS = 50000


def report_evidence(project, data, title, prepared_by):
    """Read saved export events; never mix stale decisions into current evidence."""
    exports = []
    count = sum(len(i["point_uuids"]) for i in data["issues"])
    historical = 0
    with project.db.connect() as conn:
        for row in conn.execute(
            "SELECT event_id,ts_utc,details_json FROM audit_events "
            "WHERE action='VISUAL_QA_COPY_GENERATED' ORDER BY rowid"
        ):
            details = json.loads(row["details_json"])
            if details.get("snapshot") != data["snapshot"]:
                historical += 1
                continue
            count += len(details["changes"])
            if count > MAX_REPORT_ROWS:
                raise ValueError(
                    "QA report exceeds 50,000 detail rows. No partial report was generated."
                )
            exports.append(
                {
                    "event_id": row["event_id"],
                    "ts_utc": row["ts_utc"],
                    "reason": details.get("reason", ""),
                    "changes": details["changes"],
                }
            )
    count = sum(len(i["point_uuids"]) for i in data["issues"]) + sum(
        len(e["changes"]) for e in exports
    )
    if count > MAX_REPORT_ROWS:
        raise ValueError("QA report exceeds 50,000 detail rows. No partial report was generated.")
    evidence = {
        "schema_version": 1,
        "title": title,
        "prepared_by": prepared_by,
        "prepared_by_note": "User-entered label, not an authenticated signature.",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "application_version": __version__,
        "scope": "All current project findings; screen filters are ignored.",
        "snapshot": data["snapshot"],
        "project": data["project"],
        "settings": data["settings"],
        "notice": data["notice"],
        "points": data["points"],
        "issues": data["issues"],
        "sources": data["sources"],
        "correction_exports": exports,
        "historical_exports_excluded": historical,
        "source_note": "Source hashes are registered import hashes, not a new verification of retained files.",
        "correction_note": "Each event is a separate previously generated copy, not a cumulative adjustment. Unsaved previews are excluded. Canonical coordinates remain unchanged.",
        "csv_note": "Formula-like text is apostrophe-prefixed in CSV only; JSON preserves exact values. Blank numeric fields mean unavailable, never zero.",
    }
    evidence["report_id"] = digest(evidence)
    return evidence


def csv_bytes(headers, rows):
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(
            [
                "'" + v
                if isinstance(v, str)
                and (
                    v.lstrip().startswith(("=", "+", "-", "@")) or v.startswith(("\t", "\r", "\n"))
                )
                else v
                for v in row
            ]
        )
    return out.getvalue().encode("utf-8-sig")


def pdf_bytes(e):
    """MuPDF Story supplies automatic line wrapping and multipage text flow."""

    def text(value):
        # Explicit breaks let long IDs/hashes wrap without changing the JSON/CSV values.
        value = str(value if value is not None else "Unavailable")
        return re.sub(
            r"[^\s<>]{49,}",
            lambda m: "<wbr>".join(m[0][n : n + 48] for n in range(0, len(m[0]), 48)),
            escape(value),
        )

    def p(label, value):
        return f"<p><b>{escape(label)}:</b> {text(value)}</p>"

    def table(headers, rows):
        return "".join(
            '<p class="measure">'
            + " &nbsp; | &nbsp; ".join(
                "<b>" + escape(h) + ":</b> " + text(v) for h, v in zip(headers, row)
            )
            + "</p>"
            for row in rows
        )

    project = e["project"]
    states = {
        s: sum((i.get("review") or {}).get("decision", "needs_review") == s for i in e["issues"])
        for s in ("needs_review", "confirmed", "dismissed")
    }
    parts = [
        "<h1>" + text(e["title"]) + '</h1><p class="eyebrow">SURVEYSYNC / QA REVIEW</p>',
        p("Project", project["name"]),
        p("Prepared by", e["prepared_by"] or "Not supplied"),
        p("Generated UTC", e["generated_utc"]),
        p("Report ID", e["report_id"]),
        "<h2>Review summary</h2>",
        table(
            ["Records", "Findings", "Needs review", "Confirmed", "Dismissed"],
            [
                [
                    len(e["points"]),
                    len(e["issues"]),
                    states["needs_review"],
                    states["confirmed"],
                    states["dismissed"],
                ]
            ],
        ),
        p("Scope", e["scope"]),
        "<p>Advisory review record. A confirmed finding is not an approved coordinate change. No professional certification or seal is applied.</p>",
        p("CRS", project["crs"]),
        p("Horizontal units", project["horizontal_units"]),
        p("Vertical units", project["vertical_units"]),
        p("Minimum elevation jump", e["settings"]["jump"]),
        p("Maximum horizontal gap", e["settings"]["distance"]),
        p("Evidence snapshot", e["snapshot"]),
        p("Screening method", e["notice"]),
        "<h2>Findings and saved decisions</h2>",
    ]
    by_id = {r["point_uuid"]: r for r in e["points"]}
    if not e["issues"]:
        parts.append(
            "<p>No findings under these screening settings. This is not certification that the survey is error-free.</p>"
        )
    for n, issue in enumerate(e["issues"], 1):
        review = issue.get("review") or {}
        parts += [
            "<h3>"
            + text(f"{n}. {issue['kind'].replace('_', ' ')} / {issue['severity']}")
            + "</h3>",
            p("Finding ID", issue["issue_id"]),
            p("Explanation", issue["explanation"]),
            p("Decision", review.get("decision", "needs_review")),
            p("Reason", review.get("reason") or "No saved review"),
            p("Reviewed UTC", review.get("ts_utc") or "Not reviewed"),
            p("Evidence", json.dumps(issue["evidence"], ensure_ascii=False, sort_keys=True)),
        ]
        for uid in issue["point_uuids"]:
            r = by_id[uid]
            parts += [
                '<div class="record">',
                p("Point / record UUID", f"{r['point_id']} / {uid}"),
                table(
                    ["Northing", "Easting", "Elevation", "Vertical units"],
                    [[r["northing"], r["easting"], r["elevation"], r["vertical_units"]]],
                ),
                p("Description", r["description"]),
                p("Point CRS / horizontal units", f"{r['crs']} / {r['horizontal_units']}"),
                p("Source ID", r["source_id"] or "No retained source"),
                "</div>",
            ]
    parts += [
        "<h2>Previously exported elevation copies</h2>",
        p("Interpretation", e["correction_note"]),
        p("Older-snapshot exports excluded", e["historical_exports_excluded"]),
    ]
    if not e["correction_exports"]:
        parts.append("<p>No saved correction exports match this evidence snapshot.</p>")
    for event in e["correction_exports"]:
        parts += [
            "<h3>Separate correction export</h3>",
            p("Audit event", event["event_id"]),
            p("Exported UTC", event["ts_utc"]),
            p("Reason", event["reason"]),
        ]
        for change in event["changes"]:
            r = change["original"]
            parts += [
                '<div class="record">',
                p("Point / record UUID", f"{r['point_id']} / {r['point_uuid']}"),
                table(
                    ["Before", "Signed offset", "Exported elevation", "Vertical units"],
                    [
                        [
                            r["elevation"],
                            change["offset"],
                            change["corrected_elevation"],
                            r["vertical_units"],
                        ]
                    ],
                ),
                "</div>",
            ]
    parts += ["<h2>Source references</h2>", p("Verification status", e["source_note"])]
    if not e["sources"]:
        parts.append("<p>No retained sources are registered.</p>")
    for sid, source in e["sources"].items():
        parts += [
            "<h3>" + text(source.get("original_name", sid)) + "</h3>",
            p("Source ID", sid),
            p("Registered SHA-256", source.get("sha256", "Unavailable")),
            p("Project-relative stored path", source.get("stored_path", "Unavailable")),
        ]
    parts += [
        "<h2>Package contents and interpretation</h2>",
        "<p>findings.csv contains one row per finding and affected record. corrections.csv contains one row per record per export event. review_evidence.json retains exact values and full source metadata.</p>",
        p("CSV handling", e["csv_note"]),
        p("Prepared-by label", e["prepared_by_note"]),
    ]
    story = fitz.Story(
        html="".join(parts),
        user_css="body{font-family:sans-serif;font-size:9pt;color:#243447}h1{font-size:23pt;color:#103858}h2{font-size:15pt;color:#103858;margin-top:20pt}h3{font-size:11pt;margin-top:15pt}p{margin:5pt 0}.measure{margin:8pt 0;padding:7pt;border-left:2pt solid #48748a;font-size:9pt}.record{page-break-inside:avoid}h2,h3{page-break-after:avoid}.eyebrow{color:#48748a;font-size:10pt}",
    )
    output = io.BytesIO()
    writer = fitz.DocumentWriter(output)

    def rectfn(number, filled):
        if number >= 2000:
            raise ValueError("QA report exceeds 2,000 pages. No partial report was generated.")
        return fitz.Rect(0, 0, 612, 792), fitz.Rect(44, 48, 568, 740), None

    try:
        story.write(writer, rectfn)
    finally:
        writer.close()
    with fitz.open(stream=output.getvalue(), filetype="pdf") as doc:
        doc.set_metadata(
            {
                "title": e["title"],
                "author": e["prepared_by"],
                "subject": "Advisory survey QA review",
                "creator": "SurveySync " + __version__,
            }
        )
        for n, page in enumerate(doc, 1):
            page.insert_text(
                (44, 29), "SurveySync | QA review", fontsize=8, color=(0.2, 0.35, 0.45)
            )
            page.insert_text(
                (44, 766),
                f"{e['report_id'][:16]} | Page {n} of {len(doc)} | Advisory review",
                fontsize=8,
            )
        return doc.tobytes(garbage=4, deflate=True)


def report_archive(e):
    by_id = {p["point_uuid"]: p for p in e["points"]}
    findings = []
    for issue in e["issues"]:
        review = issue.get("review") or {}
        for uid in issue["point_uuids"]:
            p = by_id[uid]
            src = e["sources"].get(p["source_id"], {})
            findings.append(
                [
                    e["report_id"],
                    issue["issue_id"],
                    issue["kind"],
                    issue["severity"],
                    review.get("decision", "needs_review"),
                    review.get("reason", ""),
                    review.get("ts_utc", ""),
                    uid,
                    p["point_id"],
                    p["northing"],
                    p["easting"],
                    p["elevation"],
                    p["description"],
                    p["crs"],
                    p["horizontal_units"],
                    p["vertical_units"],
                    p["source_id"],
                    src.get("original_name", ""),
                    src.get("sha256", ""),
                    issue["explanation"],
                    json.dumps(issue["evidence"], ensure_ascii=False),
                ]
            )
    corrections = []
    for event in e["correction_exports"]:
        for c in event["changes"]:
            p = c["original"]
            corrections.append(
                [
                    e["report_id"],
                    event["event_id"],
                    event["ts_utc"],
                    event["reason"],
                    p["point_uuid"],
                    p["point_id"],
                    p["elevation"],
                    c["offset"],
                    c["corrected_elevation"],
                    p["vertical_units"],
                    p["source_id"],
                ]
            )
    files = {
        "QA_Review.pdf": pdf_bytes(e),
        "findings.csv": csv_bytes(
            [
                "report_id",
                "issue_id",
                "kind",
                "severity",
                "decision",
                "reason",
                "reviewed_utc",
                "point_uuid",
                "point_id",
                "northing",
                "easting",
                "elevation",
                "description",
                "crs",
                "horizontal_units",
                "vertical_units",
                "source_id",
                "source_name",
                "registered_source_sha256",
                "explanation",
                "evidence_json",
            ],
            findings,
        ),
        "corrections.csv": csv_bytes(
            [
                "report_id",
                "export_event_id",
                "exported_utc",
                "reason",
                "point_uuid",
                "point_id",
                "before_elevation",
                "signed_offset",
                "exported_elevation",
                "vertical_units",
                "source_id",
            ],
            corrections,
        ),
        "review_evidence.json": json.dumps(e, ensure_ascii=False, indent=2, allow_nan=False).encode(
            "utf-8"
        ),
    }
    files["SHA256SUMS.txt"] = "".join(
        f"{hashlib.sha256(v).hexdigest()}  {k}\n" for k, v in files.items()
    ).encode()
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return output.getvalue()
