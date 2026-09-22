from __future__ import annotations

from .models import AppState


def search_project(state: AppState, query: str, limit: int = 50) -> list[dict]:
    q = (query or "").strip().casefold()
    if not q:
        return []
    hits: list[dict] = []
    for r in state.results:
        hay = " ".join([r.point_id, r.code, r.category, r.notes, r.status.value, r.dip_status.value]).casefold()
        if q in hay:
            pages = sorted({e.page_number for e in r.evidence_records})
            hits.append({"type":"result","title":r.point_id,"subtitle":f"{r.code} · {r.status.value} · Dip {r.dip_status.value} · {len(r.pipes)} pipe(s)","point_id":r.point_id,"pages":pages})
    for c in state.ocr_candidates:
        if q in c.point_id.casefold() or q in c.raw_text.casefold():
            hits.append({"type":"fieldbook","title":c.point_id,"subtitle":f"Field-book page {c.page_number} · {c.engine}","point_id":c.point_id,"page_id":c.page_id,"page_number":c.page_number})
    for e in state.network_edges:
        hay = f"{e.from_point} {e.to_point} {e.status}".casefold()
        if q in hay:
            hits.append({"type":"network","title":f"{e.from_point} → {e.to_point}","subtitle":f"Connection {e.score:.0f}% · {e.status}","point_id":e.from_point})
    return hits[:limit]
