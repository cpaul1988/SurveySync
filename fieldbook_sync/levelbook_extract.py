from __future__ import annotations

import base64
import json
import math
import re
from pathlib import Path
from typing import Any

import requests

from .ai_reader import _prepare_image_bytes, _normalize_ollama_base_url
from .models import AppState
from .ocr_local import _extract_blocks, run_paddle_pages

LEVEL_SCHEMA = {
    "type": "object",
    "properties": {
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "page_id": {"type": "string"},
                    "point_id": {"type": ["string", "null"]},
                    "backsight": {"type": ["number", "null"]},
                    "foresight": {"type": ["number", "null"]},
                    "bs_upper": {"type": ["number", "null"]},
                    "bs_middle": {"type": ["number", "null"]},
                    "bs_lower": {"type": ["number", "null"]},
                    "fs_upper": {"type": ["number", "null"]},
                    "fs_middle": {"type": ["number", "null"]},
                    "fs_lower": {"type": ["number", "null"]},
                    "distance_bs": {"type": ["number", "null"]},
                    "distance_fs": {"type": ["number", "null"]},
                    "notes": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["page_id", "point_id", "backsight", "foresight", "bs_upper", "bs_middle", "bs_lower", "fs_upper", "fs_middle", "fs_lower", "distance_bs", "distance_fs", "notes", "confidence"],
                "additionalProperties": False,
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["rows", "warnings"],
    "additionalProperties": False,
}


def _numeric_tokens(text: str) -> set[str]:
    return {m.group(0).lstrip('+') for m in re.finditer(r"[-+]?\d+(?:\.\d+)?", text or "")}


def extract_level_book_candidate(
    state: AppState,
    app_root: Path,
    *,
    model: str,
    base_url: str,
    max_pages: int = 12,
) -> dict:
    """Create a review-only level-observation candidate from field-book images.

    Qwen performs layout interpretation while PaddleOCR provides an independent text
    evidence channel. The output is deliberately *not* inserted into the level
    adjustment engine automatically; a reviewer must confirm/edit the rows first.
    """
    pages=[p for p in state.fieldbook_pages if str(p.page_type or '').lower() in {"level_loop","leveling","level","control"}]
    if not pages:
        # Page classification is advisory; allow a small fallback set rather than
        # silently claiming there is no level data.
        pages=list(state.fieldbook_pages[:max_pages])
    pages=pages[:max_pages]
    if not pages: raise ValueError("No field-book pages are loaded.")

    payloads=run_paddle_pages(pages,app_root,performance_mode="auto")
    ocr_by_page={}
    for page,payload in zip(pages,payloads):
        blocks=_extract_blocks(payload)
        ocr_by_page[page.page_id]='\n'.join(str(b.get('block_content') or '') for b in blocks if str(b.get('block_content') or '').strip())

    ordered='\n'.join(f"Image {i+1}: PAGE_ID={p.page_id} | SOURCE={p.source_name} | PAGE={p.page_number}" for i,p in enumerate(pages))
    prompt=f"""You are extracting conventional differential/three-wire leveling observations from land-survey field-book pages.
Return ONLY JSON matching the schema. Images are in this exact order:\n{ordered}\n
Rules:
- Copy only values visibly written on the page. Never calculate elevations, HI, closure, or adjustments.
- Distinguish BS from FS and upper/middle/lower wire readings by the page layout/headings.
- If a value is ambiguous, use null and explain it in notes/warnings.
- Preserve BM/TP/station labels exactly when legible.
- Do not reinterpret sewer dips, coordinates, or unrelated numbers as leveling observations.
- Every row must use one PAGE_ID listed above.
- Confidence is 0..1 and reflects transcription certainty only.
This output is a review candidate, not an authoritative survey calculation."""
    images=[base64.b64encode(_prepare_image_bytes(p.enhanced_image_path or p.image_path,max_dim=2600,quality=90)).decode('ascii') for p in pages]
    body={"model":model,"messages":[{"role":"user","content":prompt,"images":images}],"stream":False,"think":False,"format":LEVEL_SCHEMA,"options":{"temperature":0},"keep_alive":"15m"}
    url=f"{_normalize_ollama_base_url(base_url)}/api/chat"
    try:r=requests.post(url,json=body,timeout=(10,300))
    except requests.RequestException as exc:raise RuntimeError(f"Local level-book vision request failed: {exc}") from exc
    if r.status_code>=400:
        try:detail=r.json().get('error') or r.text[:500]
        except Exception:detail=r.text[:500]
        raise RuntimeError(f"Qwen level-book extraction returned HTTP {r.status_code}: {detail}")
    data=r.json();text=str((data.get('message') or {}).get('content') or '').strip()
    if not text:raise RuntimeError("Qwen returned no level-book extraction content.")
    try:parsed=json.loads(text)
    except Exception as exc:raise RuntimeError(f"Qwen level-book result was not valid JSON: {exc}") from exc
    valid_pages={p.page_id for p in pages};rows=[];warnings=list(parsed.get('warnings') or [])
    for idx,row in enumerate(parsed.get('rows') or [],start=1):
        if not isinstance(row,dict):continue
        pid=str(row.get('page_id') or '')
        if pid not in valid_pages:
            warnings.append(f"Row {idx} used an unknown page id and was held for review.")
            continue
        ocr_text=ocr_by_page.get(pid,'');tokens=_numeric_tokens(ocr_text);numeric_fields=[];supported=0
        for key in ('backsight','foresight','bs_upper','bs_middle','bs_lower','fs_upper','fs_middle','fs_lower','distance_bs','distance_fs'):
            value=row.get(key)
            if value is None:continue
            numeric_fields.append(key)
            sval=(f"{float(value):.6f}").rstrip('0').rstrip('.')
            # Compare both canonical and literal decimal renderings because OCR may
            # omit trailing zeros.
            if sval in tokens or str(value) in tokens:supported+=1
        evidence_ratio=(supported/len(numeric_fields)) if numeric_fields else 0.0
        rows.append({**row,"sequence_no":len(rows)+1,"paddle_ocr_support_ratio":round(evidence_ratio,3),"review_required":True,"source":"Qwen3-VL + PaddleOCR-VL evidence"})
    return {"rows":rows,"warnings":warnings,"page_count":len(pages),"review_required":True,"calculation_performed":False,"ocr_pages":{k:v[:4000] for k,v in ocr_by_page.items()}}
