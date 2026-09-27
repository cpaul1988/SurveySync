"""Preserve shot identity and selection order independently of generated UUIDs."""
import json
from .survey_validation import finite_number


def solver_rows(db, control_id, method, observation_ids):
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM control_observations WHERE control_id=? AND include=1 ORDER BY observed_utc, observation_id", (control_id,))]
    if observation_ids is not None:
        by_id = {r["observation_id"]: r for r in rows}
        if len(set(observation_ids)) != len(observation_ids) or any(i not in by_id for i in observation_ids):
            raise ValueError("Selected control observations are duplicated, missing or excluded.")
        rows = [by_id[i] for i in observation_ids]
    elif method == "ron_spreadsheet" and any(r.get("method") == "RON_3_POINT_WORKBOOK" for r in rows):
        orders = [json.loads(r.get("metadata_json") or "{}").get("selection_index") for r in rows]
        if any(not isinstance(i, int) for i in orders) or len(set(orders)) != len(orders):
            raise ValueError("Legacy manual shots have ambiguous ordering; reselect the original three PointIDs.")
        rows = [r for _, r in sorted(zip(orders, rows), key=lambda pair: pair[0])]
    for row in rows:
        for key in ("northing", "easting", "elevation"):
            if row.get(key) is not None:
                row[key] = finite_number(row[key], key)
    return rows
