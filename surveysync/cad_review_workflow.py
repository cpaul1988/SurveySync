"""Snapshot-bound decisions and conservative drawing-revision comparisons."""

import csv
import io
import json
from html import escape
from zipfile import ZipFile, ZIP_DEFLATED
from . import cad_review as cad
from .cad_geometry import digest

STATUSES = ("needs_review", "confirmed", "dismissed")
ACTION = "CAD_FINDING_DECISION"


def finding_ids(data):
    return [digest([data["snapshot"], n, issue]) for n, issue in enumerate(data["qa"]["issues"])]


def state(project, data):
    with project.db.connect() as conn:
        rows = conn.execute(
            "SELECT event_id,ts_utc,actor,details_json FROM audit_events "
            "WHERE module=? AND action=? AND object_id=? ORDER BY rowid LIMIT 10001",
            ("BoundarySync", ACTION, data["review_id"]),
        ).fetchall()
    if len(rows) > 10000:
        raise ValueError("Drawing decision history exceeds 10,000 events. Start a new review.")
    history, decisions = [], {}
    identifiers = finding_ids(data)
    valid = set(identifiers)
    for row in rows:
        entry = dict(row)
        details = json.loads(entry.pop("details_json"))
        if details.get("snapshot") != data["snapshot"] or details.get("finding_id") not in valid:
            raise ValueError("Drawing decision evidence does not match this review.")
        entry.update(details)
        history.append(entry)
        decisions[entry["finding_id"]] = entry
    return {
        "token": digest(history),
        "decisions": decisions,
        "history": history,
        "finding_ids": identifiers,
    }


def decide(project, data, identifier, status, note, reviewer, token):
    note, reviewer = note.strip(), reviewer.strip()
    if (
        status not in STATUSES
        or not note
        or len(note) > 4000
        or not reviewer
        or len(reviewer) > 120
    ):
        raise ValueError(
            "Choose a status and supply a reviewer (120 characters) and reason (4,000 characters)."
        )
    with project.db.transaction():
        current = state(project, data)
        if current["token"] != token:
            raise ValueError("Another decision was saved. Reopen this review before saving.")
        if identifier not in current["finding_ids"]:
            raise ValueError("Finding does not belong to this drawing snapshot.")
        if len(current["history"]) >= 10000:
            raise ValueError("Drawing decision history limit reached.")
        project.db.audit(
            "BoundarySync",
            ACTION,
            actor=reviewer,
            object_type="cad_review",
            object_id=data["review_id"],
            details={
                "snapshot": data["snapshot"],
                "finding_id": identifier,
                "status": status,
                "note": note,
                "source_modified": False,
            },
        )
        return state(project, data)


def representation(entity):
    return {k: v for k, v in entity.items() if k not in ("entity_id", "handle")}


def compare(before, after):
    if before["review_id"] == after["review_id"]:
        raise ValueError("Choose two different retained drawings.")
    if before["project"] != after["project"] or before["point_snapshot"] != after["point_snapshot"]:
        raise ValueError(
            "Drawing contexts or point snapshots differ. Reimport both against the current project."
        )
    old = {e["entity_id"]: e for e in before["entities"]}
    new = {e["entity_id"]: e for e in after["entities"]}
    changes, unchanged = [], 0
    for key in sorted(old.keys() | new.keys()):
        a, b = old.get(key), new.get(key)
        # Expanded block child indices can move after edits; never match by index.
        if "/" in key:
            if a:
                changes.append(
                    {"kind": "before_only", "entity_id": key, "before": a, "after": None}
                )
            if b:
                changes.append({"kind": "after_only", "entity_id": key, "before": None, "after": b})
        elif a is None or b is None:
            changes.append(
                {
                    "kind": "after_only" if a is None else "before_only",
                    "entity_id": key,
                    "before": a,
                    "after": b,
                }
            )
        elif representation(a) == representation(b):
            unchanged += 1
        else:
            changes.append({"kind": "changed_candidate", "entity_id": key, "before": a, "after": b})
    return {
        "before": {k: before[k] for k in ("review_id", "snapshot", "source_name", "source_sha256")},
        "after": {k: after[k] for k in ("review_id", "snapshot", "source_name", "source_sha256")},
        "unchanged_representation_count": unchanged,
        "changes": changes,
        "before_unsupported": before["unsupported"],
        "after_unsupported": after["unsupported"],
        "scope": "Supported imported representations in project units only. Same top-level handles are candidates, not proven identity; handles may be reused. Block children are unmatched. Curves are sampled, text is an anchor, and omitted content is not compared. No decisions transfer and no source geometry is modified.",
    }


def report(data, selections, review_state, comparison=None):
    base = cad.report(data, selections)
    payload = {
        "review_id": data["review_id"],
        "snapshot": data["snapshot"],
        "review_state": review_state,
        "comparison": comparison,
    }
    rows = []
    for n, issue in enumerate(data["qa"]["issues"]):
        identifier = review_state["finding_ids"][n]
        d = review_state["decisions"].get(identifier, {})
        rows.append(
            [
                identifier,
                issue["kind"],
                "; ".join(issue["entity_ids"]),
                d.get("status", "needs_review"),
                d.get("actor", ""),
                d.get("note", ""),
                d.get("ts_utc", ""),
            ]
        )
    headers = [
        "Finding ID",
        "Kind",
        "Entities",
        "Status",
        "Reviewer (self-entered)",
        "Reason",
        "UTC",
    ]

    def table(head, values):
        return (
            "<table><thead><tr>"
            + "".join("<th>" + escape(str(x)) + "</th>" for x in head)
            + "</tr></thead><tbody>"
            + "".join(
                "<tr>" + "".join("<td>" + escape(str(x)) + "</td>" for x in row) + "</tr>"
                for row in values
            )
            + "</tbody></table>"
        )

    extra = (
        "<h2>Finding decisions</h2><p>Confirmed means the finding is confirmed, not repaired. Dismissal does not change geometry or certify survey acceptance. Reviewer names are self-entered.</p>"
        + table(headers, rows)
    )
    extra += "<h2>Decision history</h2>" + table(
        ["UTC", "Finding", "Status", "Reviewer", "Reason"],
        [
            [h["ts_utc"], h["finding_id"], h["status"], h["actor"], h["note"]]
            for h in review_state["history"]
        ],
    )
    if comparison:
        extra += (
            "<h2>Drawing revision comparison</h2><p>"
            + escape(comparison["before"]["source_name"])
            + " → "
            + escape(comparison["after"]["source_name"])
            + "</p><p>"
            + escape(comparison["scope"])
            + "</p>"
        )
        extra += (
            "<p>Before SHA-256: "
            + escape(comparison["before"]["source_sha256"])
            + "<br>After SHA-256: "
            + escape(comparison["after"]["source_sha256"])
            + "</p>"
        )
        extra += table(
            ["Change", "Entity", "Before layer", "After layer"],
            [
                [
                    c["kind"],
                    c["entity_id"],
                    (c["before"] or {}).get("layer", ""),
                    (c["after"] or {}).get("layer", ""),
                ]
                for c in comparison["changes"]
            ],
        )
    else:
        extra += "<p>No revised-drawing comparison included.</p>"
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(
            [
                "'" + str(v) if str(v).startswith(("=", "+", "-", "@", "\t", "\r")) else v
                for v in row
            ]
        )
    out = io.BytesIO()
    with ZipFile(io.BytesIO(base)) as source, ZipFile(out, "w", ZIP_DEFLATED) as target:
        for name in source.namelist():
            value = source.read(name)
            if name == "CAD_Review.html":
                value = value.decode().replace("</body>", extra + "</body>").encode()
            target.writestr(name, value)
        target.writestr("CAD_Decisions.csv", stream.getvalue())
        target.writestr(
            "CAD_Workflow.json", json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False)
        )
    return out.getvalue()
