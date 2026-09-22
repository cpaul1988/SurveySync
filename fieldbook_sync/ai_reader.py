from __future__ import annotations
import logging

import base64
import io
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Sequence
from urllib.parse import quote

import requests
from PIL import Image, ImageOps

from .models import DipStatus, EvidenceBasis, FieldBookPage, PageEvidence, PipeMeasurement, UnmatchedEvidence
from .survey import normalize_point_id
from .evidence_pipeline import specialized_prompt_note
from surveysync.ai_runtime import foundry_vision_json, DEFAULT_FOUNDRY_VISION_MODEL


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
OLLAMA_BASE_URL = "http://127.0.0.1:11434"


PIPE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "dip": {"type": ["number", "null"]},
        "dip_raw": {"type": ["string", "null"]},
        "diameter_in": {"type": ["number", "null"]},
        "diameter_raw": {"type": ["string", "null"]},
        "material": {"type": ["string", "null"]},
        "azimuth_deg": {"type": ["number", "null"]},
        "azimuth_raw": {"type": ["string", "null"]},
        "leader_direction_deg": {"type": ["number", "null"]},
        "leader_direction_raw": {"type": ["string", "null"]},
        "leader_bbox": {"type": ["array", "null"], "items": {"type": "integer", "minimum": 0, "maximum": 1000}, "minItems": 4, "maxItems": 4},
        "connected_point_raw": {"type": ["string", "null"]},
        "notes": {"type": ["string", "null"]},
    },
    "required": [
        "dip", "dip_raw", "diameter_in", "diameter_raw",
        "material", "azimuth_deg", "azimuth_raw", "leader_direction_deg",
        "leader_direction_raw", "leader_bbox", "connected_point_raw", "notes",
    ],
}

BBOX_SCHEMA: Dict[str, Any] = {
    "type": ["array", "null"],
    "items": {"type": "integer", "minimum": 0, "maximum": 1000},
    "minItems": 4,
    "maxItems": 4,
}

ENTRY_PROPERTIES: Dict[str, Any] = {
    "point_id": {"type": "string"},
    "point_id_raw": {"type": ["string", "null"]},
    "point_id_confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "structure_label": {"type": ["string", "null"]},
    "dipped": {"type": "string", "enum": ["YES", "NO", "CNA", "CNL", "REVIEW"]},
    "basis": {"type": "string", "enum": ["MEASUREMENT", "EXPLICIT_YES", "EXPLICIT_NO", "EXPLICIT_CNA", "EXPLICIT_CNL", "AMBIGUOUS"]},
    "dipped_confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "evidence": {"type": ["string", "null"]},
    "pipes": {"type": "array", "items": PIPE_SCHEMA},
    "bbox": BBOX_SCHEMA,
    "field_note_template": {"type": "string", "enum": ["BRT_STANDARD", "OTHER", "UNKNOWN"]},
    "field_note_profile": {"type": "string"},
    "field_note_profile_confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "structure_bbox": BBOX_SCHEMA,
    "north_arrow_deg": {"type": ["number", "null"]},
    "notes": {"type": ["string", "null"]},
}
ENTRY_REQUIRED = list(ENTRY_PROPERTIES.keys())

EXTRACTION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": ENTRY_PROPERTIES,
                "required": ENTRY_REQUIRED,
            },
        },
        "unmatched": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "point_id_raw": {"type": ["string", "null"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason": {"type": "string"},
                    "bbox": BBOX_SCHEMA,
                },
                "required": ["point_id_raw", "confidence", "reason", "bbox"],
            },
        },
    },
    "required": ["entries", "unmatched"],
}

GEMINI_BATCH_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"page_id": {"type": "string"}, **ENTRY_PROPERTIES},
                "required": ["page_id", *ENTRY_REQUIRED],
            },
        },
        "unmatched": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "page_id": {"type": "string"},
                    "point_id_raw": {"type": ["string", "null"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason": {"type": "string"},
                    "bbox": BBOX_SCHEMA,
                },
                "required": ["page_id", "point_id_raw", "confidence", "reason", "bbox"],
            },
        },
    },
    "required": ["entries", "unmatched"],
}


SYSTEM_PROMPT = """You are reading handwritten civil/survey field-book pages for storm and sewer structure QA/QC.
Your job is evidence extraction, not guessing.

Critical rules:
1. Only return a matched entry when the visible PointID can be matched EXACTLY to one of the target PointIDs supplied by the application.
2. Never fuzzy-match an uncertain handwritten PointID to the nearest target. If any digit is uncertain and it could correspond to a supplied target, place it in unmatched instead. Clearly readable IDs that are not in the supplied target list should be ignored, not reported as unmatched.
3. YES means there is visible evidence that the structure was dipped/opened/measured, such as one or more pipe dip/depth/invert measurements, or an explicit note that it was dipped. Set basis=MEASUREMENT or EXPLICIT_YES.
4. NO is allowed only when the page explicitly indicates the target structure was NOT dipped/not opened/no dips taken. Set basis=EXPLICIT_NO. Do not infer NO merely because measurements are absent.
5. CNA is a specific field-book dip status meaning COULD NOT ACCESS. Return dipped=CNA and basis=EXPLICIT_CNA only when CNA or an unambiguous written phrase such as "could not access" is visibly associated with the target structure. CNA is not the same as generic NO.
6. CNL is a specific field-book dip status meaning COULD NOT LOCATE. Return dipped=CNL and basis=EXPLICIT_CNL only when CNL or an unambiguous written phrase such as "could not locate" is visibly associated with the target structure. CNL is not the same as generic NO.
7. When CNA or CNL is present, do not invent a dip measurement. Leave pipe dip values null unless an actual measurement is also visibly written.
8. REVIEW means the PointID is certain enough to match, but the dipped status, measurement association, or handwriting is ambiguous. If the letters could plausibly be CNA/CNL but are not legible enough to distinguish them, use REVIEW rather than guessing. Set basis=AMBIGUOUS unless another basis is genuinely visible.
9. Extract pipe measurements when visible: dip/depth/invert value, pipe diameter, material, and written azimuth/bearing. Keep the raw handwritten text for numeric fields when possible.
10. Field-note formats vary by client, crew, and job type. Use the FIELD-NOTE PROFILE CONTEXT appended to this prompt. Set field_note_profile to the best matching profile ID only when the visible layout fits its grammar; otherwise use GENERIC_SURVEY_NOTES or UNKNOWN. field_note_profile_confidence is advisory only.
11. SurveySync BRT standard field notes commonly draw the surveyed structure as a circle, place a north arrow or N orientation mark inside/at the circle, write the structure PointID near the circle, and draw one leader for each pipe/connection. When that pattern is visibly present, set field_note_template=BRT_STANDARD and field_note_profile=BRT_STANDARD. Otherwise use OTHER or UNKNOWN; never force the template.
12. For a BRT_STANDARD sketch, treat each leader touching the structure circle as a separate pipe record. Associate only the handwriting spatially belonging to that leader with that pipe. Do not merge annotations from neighboring leaders.
13. If a leader visibly says "to 3394", "Az = to 3394", or equivalent, copy the destination identifier into connected_point_raw exactly as visible. Do not replace it with a guessed nearby PointID.
14. leader_direction_deg is the visual survey azimuth of the leader, clockwise from the page's drawn north arrow, only when that direction can be estimated reliably. It is separate from azimuth_deg, which is the written azimuth. If either is uncertain, use null. leader_bbox bounds the leader and its attached annotation block where practical.
15. structure_bbox bounds the structure circle/sketch where practical. north_arrow_deg is the visible north-arrow direction in page coordinates expressed clockwise from page-up (0=up, 90=right); it is only orientation metadata and is not itself a survey bearing.
16. Do not invent missing values. Use null.
16. bbox is optional and uses normalized page coordinates [x1,y1,x2,y2] from 0 to 1000 around the relevant handwritten block. If uncertain, use null.
17. Evidence must be a short description of what is visibly supporting the status; do not quote large portions of the page.
18. A point appearing elsewhere on the page without a clear structure/dip association should be REVIEW, not YES.
"""


def system_prompt(profile_context: str = "") -> str:
    context = str(profile_context or "").strip()
    return SYSTEM_PROMPT if not context else SYSTEM_PROMPT + "\n\n" + context


@dataclass(frozen=True)
class ProviderUsage:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


def _prepare_image_bytes(path: str, *, max_dim: int = 2600, quality: int = 86) -> bytes:
    """Normalize a rendered field-book page before cloud upload.

    FieldBook Sync already rendered PDFs locally. The provider receives a bounded JPEG
    rather than the original file, reducing request size while keeping handwriting legible.
    """
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        if max(image.size) > max_dim:
            scale = max_dim / max(image.size)
            image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))))
        if image.mode == "L":
            image = image.convert("RGB")
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()


def _prepare_image_data_url(path: str, mime_type: str) -> str:
    payload = base64.b64encode(_prepare_image_bytes(path, max_dim=3200, quality=90)).decode("ascii")
    return f"data:image/jpeg;base64,{payload}"


def _extract_openai_output_text(response_json: Dict[str, Any]) -> str:
    if isinstance(response_json.get("output_text"), str):
        return response_json["output_text"]
    chunks: List[str] = []
    for item in response_json.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content", []) or []:
            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    if chunks:
        return "\n".join(chunks)
    raise ValueError("OpenAI response did not contain output text.")


def _extract_gemini_text(response_json: Dict[str, Any]) -> str:
    chunks: List[str] = []
    for candidate in response_json.get("candidates", []) or []:
        content = candidate.get("content") or {}
        for part in content.get("parts", []) or []:
            text = part.get("text")
            if isinstance(text, str):
                chunks.append(text)
    if not chunks:
        feedback = response_json.get("promptFeedback") or {}
        reason = feedback.get("blockReason")
        if reason:
            raise ValueError(f"Gemini blocked the response ({reason}).")
        raise ValueError("Gemini response did not contain output text.")
    return "\n".join(chunks)


def _extract_anthropic_text(response_json: Dict[str, Any]) -> str:
    chunks: List[str] = []
    for content in response_json.get("content", []) or []:
        if content.get("type") == "text" and isinstance(content.get("text"), str):
            chunks.append(content["text"])
    if chunks:
        return "\n".join(chunks)
    raise ValueError("Anthropic response did not contain output text.")


def _json_object_text(text: str) -> str:
    """Normalize a provider text response that is expected to contain one JSON object."""
    value = str(text or "").strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    start = value.find("{")
    end = value.rfind("}")
    if start >= 0 and end > start:
        value = value[start:end + 1]
    return value


def _anthropic_usage(response_json: Dict[str, Any]) -> ProviderUsage:
    meta = response_json.get("usage") or {}
    inp = int(meta.get("input_tokens", 0) or 0)
    out = int(meta.get("output_tokens", 0) or 0)
    return ProviderUsage(requests=1, input_tokens=inp, output_tokens=out, total_tokens=inp + out)


def _gemini_usage(response_json: Dict[str, Any]) -> ProviderUsage:
    meta = response_json.get("usageMetadata") or {}
    inp = int(meta.get("promptTokenCount", 0) or 0)
    out = int(meta.get("candidatesTokenCount", 0) or 0)
    total = int(meta.get("totalTokenCount", inp + out) or (inp + out))
    return ProviderUsage(requests=1, input_tokens=inp, output_tokens=out, total_tokens=total)


def _request_error(provider: str, response: requests.Response) -> RuntimeError:
    detail = ""
    try:
        data = response.json()
        error = data.get("error") or {}
        detail = error.get("message") or ""
        status = error.get("status") or ""
        if status and status not in detail:
            detail = f"{status}: {detail}".strip(": ")
    except Exception:
        detail = response.text[:700]
    if provider == "Gemini" and response.status_code == 429:
        return RuntimeError(
            "Gemini returned 429 RESOURCE_EXHAUSTED. The project's rate limit or free-tier quota may have been reached. "
            "No partial analysis results were committed. Wait for quota to reset, reduce the batch workload, or use Manual Review."
        )
    if provider == "Gemini" and response.status_code in {401, 403}:
        return RuntimeError(
            f"Gemini rejected the API key or project permission (HTTP {response.status_code}). "
            f"Check the key in Google AI Studio. {detail}".strip()
        )
    return RuntimeError(f"{provider} returned HTTP {response.status_code}: {detail or 'Unknown error'}")


def _parse_status_basis(item: Dict[str, Any]) -> tuple[DipStatus, EvidenceBasis]:
    try:
        status = DipStatus(item.get("dipped", "REVIEW"))
    except ValueError:
        status = DipStatus.REVIEW
    try:
        basis = EvidenceBasis(item.get("basis", "AMBIGUOUS"))
    except ValueError:
        basis = EvidenceBasis.AMBIGUOUS

    # Provider output is never allowed to create a decisive status without the
    # deterministic evidence-basis gate succeeding in application code.
    if status == DipStatus.YES and basis not in {EvidenceBasis.MEASUREMENT, EvidenceBasis.EXPLICIT_YES}:
        status = DipStatus.REVIEW
    if status == DipStatus.NO and basis != EvidenceBasis.EXPLICIT_NO:
        status = DipStatus.REVIEW
    if status == DipStatus.CNA and basis != EvidenceBasis.EXPLICIT_CNA:
        status = DipStatus.REVIEW
    if status == DipStatus.CNL and basis != EvidenceBasis.EXPLICIT_CNL:
        status = DipStatus.REVIEW
    return status, basis


def _entry_to_evidence(item: Dict[str, Any], *, page: FieldBookPage, target_set: set[str]) -> tuple[PageEvidence | None, UnmatchedEvidence | None]:
    point_id = normalize_point_id(item.get("point_id", ""))
    if point_id not in target_set:
        return None, UnmatchedEvidence(
            source_name=page.source_name,
            page_number=page.page_number,
            page_id=page.page_id,
            point_id_raw=item.get("point_id_raw") or item.get("point_id"),
            confidence=float(item.get("point_id_confidence", 0) or 0),
            reason="Model returned a PointID that was not an exact target; application blocked the match.",
            bbox=item.get("bbox"),
        )

    status, basis = _parse_status_basis(item)
    pipes = [PipeMeasurement.model_validate(p) for p in item.get("pipes", [])]
    return PageEvidence(
        matched_point_id=point_id,
        basis=basis,
        source_name=page.source_name,
        page_number=page.page_number,
        page_id=page.page_id,
        point_id_raw=item.get("point_id_raw"),
        point_id_confidence=float(item.get("point_id_confidence", 0) or 0),
        dipped=status,
        dipped_confidence=float(item.get("dipped_confidence", 0) or 0),
        evidence=item.get("evidence"),
        structure_label=item.get("structure_label"),
        pipes=pipes,
        bbox=item.get("bbox"),
        field_note_template=item.get("field_note_template") or "UNKNOWN",
        field_note_profile=item.get("field_note_profile") or item.get("field_note_template") or "UNKNOWN",
        field_note_profile_confidence=float(item.get("field_note_profile_confidence", 0) or 0),
        structure_bbox=item.get("structure_bbox"),
        north_arrow_deg=item.get("north_arrow_deg"),
        notes=item.get("notes"),
    ), None


def read_page_openai(
    *,
    image_path: str,
    mime_type: str,
    source_name: str,
    page_number: int,
    page_id: str,
    target_point_ids: Iterable[str],
    api_key: str,
    model: str = "gpt-5.6-luna",
    timeout_seconds: int = 180,
    profile_context: str = "",
    field_note_profile_override: str = "",
) -> tuple[List[PageEvidence], List[UnmatchedEvidence], ProviderUsage]:
    targets = [normalize_point_id(v) for v in target_point_ids if normalize_point_id(v)]
    if not targets:
        return [], [], ProviderUsage()
    target_set = set(targets)
    page = FieldBookPage(page_id=page_id, source_name=source_name, page_number=page_number, image_path=image_path, mime_type=mime_type)
    user_text = (
        f"Source: {source_name}, page {page_number}.\n"
        f"Target PointIDs for this analysis pass:\n{', '.join(targets)}\n"
        f"Field-note profile override: {field_note_profile_override or 'AUTO'}\n\n"
        "Inspect the page carefully and return only target entries actually visible on this page. "
        "Ignore clearly readable PointIDs that are not in this target list. Put only uncertain candidate PointIDs in unmatched."
    )
    body = {
        "model": model,
        "input": [
            {"role": "system", "content": system_prompt(profile_context)},
            {"role": "user", "content": [
                {"type": "input_text", "text": user_text},
                {"type": "input_image", "image_url": _prepare_image_data_url(image_path, mime_type), "detail": "auto"},
            ]},
        ],
        "text": {"format": {"type": "json_schema", "name": "fieldbook_page_extraction", "strict": True, "schema": EXTRACTION_SCHEMA}},
    }
    try:
        response = requests.post(
            OPENAI_RESPONSES_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach OpenAI: {exc}") from exc
    if response.status_code >= 400:
        raise _request_error("OpenAI", response)
    try:
        raw_output = response.json()
        parsed = json.loads(_extract_openai_output_text(raw_output))
    except Exception as exc:
        raise RuntimeError(f"OpenAI response could not be parsed as structured JSON: {exc}") from exc

    evidence: List[PageEvidence] = []
    unmatched: List[UnmatchedEvidence] = []
    for item in parsed.get("entries", []):
        ev, blocked = _entry_to_evidence(item, page=page, target_set=target_set)
        if ev:
            evidence.append(ev)
        if blocked:
            unmatched.append(blocked)
    for item in parsed.get("unmatched", []):
        unmatched.append(UnmatchedEvidence(
            source_name=source_name,
            page_number=page_number,
            page_id=page_id,
            point_id_raw=item.get("point_id_raw"),
            confidence=float(item.get("confidence", 0) or 0),
            reason=item.get("reason", "Uncertain handwritten PointID or association."),
            bbox=item.get("bbox"),
        ))
    usage_data = raw_output.get("usage") or {}
    usage = ProviderUsage(
        requests=1,
        input_tokens=int(usage_data.get("input_tokens", 0) or 0),
        output_tokens=int(usage_data.get("output_tokens", 0) or 0),
        total_tokens=int(usage_data.get("total_tokens", 0) or 0),
    )
    return evidence, unmatched, usage


def read_page_anthropic(
    *,
    image_path: str,
    mime_type: str,
    source_name: str,
    page_number: int,
    page_id: str,
    target_point_ids: Iterable[str],
    api_key: str,
    model: str = "claude-sonnet-5",
    timeout_seconds: int = 180,
    profile_context: str = "",
    field_note_profile_override: str = "",
) -> tuple[List[PageEvidence], List[UnmatchedEvidence], ProviderUsage]:
    """Read one rendered field-book page with Anthropic Claude vision.

    Claude is an explicitly selected cloud backup. The same exact PointID provenance
    validation used for other cloud providers is applied before any evidence is accepted.
    """
    targets = [normalize_point_id(v) for v in target_point_ids if normalize_point_id(v)]
    if not targets:
        return [], [], ProviderUsage()
    target_set = set(targets)
    page = FieldBookPage(page_id=page_id, source_name=source_name, page_number=page_number, image_path=image_path, mime_type=mime_type)
    user_text = (
        f"Source: {source_name}, page {page_number}.\n"
        f"Target PointIDs for this analysis pass:\n{', '.join(targets)}\n"
        f"Field-note profile override: {field_note_profile_override or 'AUTO'}\n\n"
        "Inspect the page carefully and return only target entries actually visible on this page. "
        "Ignore clearly readable PointIDs that are not in this target list. Put only uncertain candidate PointIDs in unmatched.\n\n"
        "Return ONLY one JSON object matching this schema exactly (no markdown fences):\n"
        + json.dumps(EXTRACTION_SCHEMA, separators=(",", ":"))
    )
    body = {
        "model": model,
        "max_tokens": 8192,
        "system": system_prompt(profile_context),
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64.b64encode(_prepare_image_bytes(image_path, max_dim=3200, quality=90)).decode("ascii"),
                    },
                },
                {"type": "text", "text": user_text},
            ],
        }],
    }
    try:
        response = requests.post(
            ANTHROPIC_MESSAGES_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_API_VERSION,
                "content-type": "application/json",
            },
            json=body,
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach Anthropic: {exc}") from exc
    if response.status_code >= 400:
        raise _request_error("Anthropic", response)
    try:
        raw_output = response.json()
        parsed = json.loads(_json_object_text(_extract_anthropic_text(raw_output)))
    except Exception as exc:
        raise RuntimeError(f"Anthropic response could not be parsed as structured JSON: {exc}") from exc

    evidence: List[PageEvidence] = []
    unmatched: List[UnmatchedEvidence] = []
    for item in parsed.get("entries", []):
        ev, blocked = _entry_to_evidence(item, page=page, target_set=target_set)
        if ev:
            evidence.append(ev)
        if blocked:
            unmatched.append(blocked)
    for item in parsed.get("unmatched", []):
        unmatched.append(UnmatchedEvidence(
            source_name=source_name,
            page_number=page_number,
            page_id=page_id,
            point_id_raw=item.get("point_id_raw"),
            confidence=float(item.get("confidence", 0) or 0),
            reason=item.get("reason", "Uncertain handwritten PointID or association."),
            bbox=item.get("bbox"),
        ))
    return evidence, unmatched, _anthropic_usage(raw_output)


def read_pages_gemini(
    *,
    pages: Sequence[FieldBookPage],
    target_point_ids: Iterable[str],
    api_key: str,
    model: str = "gemini-3.8-flash",
    timeout_seconds: int = 240,
    profile_context: str = "",
) -> tuple[List[PageEvidence], List[UnmatchedEvidence], ProviderUsage]:
    """Read several rendered field-book pages in one Gemini request.

    Batching is intentionally the default because free-tier projects are often limited
    by requests/day. Every returned page_id and PointID is validated against the exact
    application-owned batch before an evidence record can be created.
    """
    if not pages:
        return [], [], ProviderUsage()
    targets = [normalize_point_id(v) for v in target_point_ids if normalize_point_id(v)]
    if not targets:
        return [], [], ProviderUsage()
    target_set = set(targets)
    page_by_id = {p.page_id: p for p in pages}

    parts: List[Dict[str, Any]] = [{
        "text": (
            "Analyze the following field-book pages as a single batch. Each image is preceded by an authoritative PAGE_ID. "
            "Every returned entry and unmatched candidate MUST include exactly one of those PAGE_ID values.\n\n"
            f"Target PointIDs for this pass:\n{', '.join(targets)}\n\n"
            "Only report target entries actually visible. Do not fuzzy-match PointIDs."
        )
    }]
    for page in pages:
        parts.append({"text": f"PAGE_ID={page.page_id} | SOURCE={page.source_name} | PAGE_NUMBER={page.page_number} | FIELD_NOTE_OVERRIDE={page.field_note_profile_override or page.field_note_profile_book or 'AUTO'}"})
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(_prepare_image_bytes(page.image_path)).decode("ascii"),
            }
        })

    safe_model = model.strip().removeprefix("models/") or "gemini-3.8-flash"
    url = f"{GEMINI_BASE_URL}/models/{quote(safe_model, safe='.-_')}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": system_prompt(profile_context)}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": GEMINI_BATCH_SCHEMA,
            "temperature": 0.05,
            "maxOutputTokens": 8192,
        },
    }
    try:
        response = requests.post(
            url,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=body,
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach Gemini: {exc}") from exc
    if response.status_code >= 400:
        raise _request_error("Gemini", response)

    try:
        raw_output = response.json()
        parsed = json.loads(_extract_gemini_text(raw_output))
    except Exception as exc:
        raise RuntimeError(f"Gemini response could not be parsed as structured JSON: {exc}") from exc

    evidence: List[PageEvidence] = []
    unmatched: List[UnmatchedEvidence] = []
    for item in parsed.get("entries", []):
        page = page_by_id.get(str(item.get("page_id", "")))
        if page is None:
            # Never guess which page a model meant; page provenance is part of QA/QC.
            continue
        ev, blocked = _entry_to_evidence(item, page=page, target_set=target_set)
        if ev:
            evidence.append(ev)
        if blocked:
            unmatched.append(blocked)

    for item in parsed.get("unmatched", []):
        page = page_by_id.get(str(item.get("page_id", "")))
        if page is None:
            continue
        unmatched.append(UnmatchedEvidence(
            source_name=page.source_name,
            page_number=page.page_number,
            page_id=page.page_id,
            point_id_raw=item.get("point_id_raw"),
            confidence=float(item.get("confidence", 0) or 0),
            reason=item.get("reason", "Uncertain handwritten PointID or association."),
            bbox=item.get("bbox"),
        ))
    return evidence, unmatched, _gemini_usage(raw_output)



def _ollama_usage(response_json: Dict[str, Any]) -> ProviderUsage:
    inp = int(response_json.get("prompt_eval_count", 0) or 0)
    out = int(response_json.get("eval_count", 0) or 0)
    return ProviderUsage(requests=1, input_tokens=inp, output_tokens=out, total_tokens=inp + out)


def _normalize_ollama_base_url(base_url: str) -> str:
    return (base_url or OLLAMA_BASE_URL).strip().rstrip("/") or OLLAMA_BASE_URL


def list_ollama_models(*, base_url: str = OLLAMA_BASE_URL, timeout_seconds: int = 5) -> List[str]:
    """Return locally installed Ollama model names. No internet access is used."""
    url = f"{_normalize_ollama_base_url(base_url)}/api/tags"
    try:
        response = requests.get(url, timeout=timeout_seconds)
    except requests.ConnectTimeout as exc:
        raise RuntimeError("Ollama service connection timed out while checking installed models.") from exc
    except requests.ConnectionError as exc:
        raise RuntimeError("Ollama service is unavailable at 127.0.0.1:11434. Start Ollama and try again.") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"Ollama model inventory request failed: {exc}") from exc
    if response.status_code >= 400:
        raise RuntimeError(f"Ollama returned HTTP {response.status_code} while listing models: {response.text[:500]}")
    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError(f"Ollama returned an invalid model-list response: {exc}") from exc
    names = []
    for item in payload.get("models", []) or []:
        name = str(item.get("name") or item.get("model") or "").strip()
        if name:
            names.append(name)
    return sorted(set(names), key=str.lower)


def ollama_running_models(*, base_url: str = OLLAMA_BASE_URL, timeout_seconds: int = 5) -> List[Dict[str, Any]]:
    """Return currently loaded Ollama models with an estimated CPU/GPU split."""
    url = f"{_normalize_ollama_base_url(base_url)}/api/ps"
    try:
        response = requests.get(url, timeout=timeout_seconds)
    except requests.RequestException:
        return []
    if response.status_code >= 400:
        return []
    try:
        payload = response.json()
    except Exception:
        return []
    result: List[Dict[str, Any]] = []
    for item in payload.get("models", []) or []:
        size = int(item.get("size") or 0)
        size_vram = int(item.get("size_vram") or 0)
        gpu = round((size_vram / size) * 100.0, 1) if size > 0 else 0.0
        gpu = max(0.0, min(100.0, gpu))
        result.append({
            "name": str(item.get("name") or item.get("model") or ""),
            "size_bytes": size,
            "size_vram_bytes": size_vram,
            "gpu_percent": gpu,
            "cpu_percent": round(100.0 - gpu, 1),
            "context_length": int(item.get("context_length") or 0),
            "expires_at": item.get("expires_at"),
        })
    return result


def warm_ollama_model(
    *,
    model: str,
    base_url: str = OLLAMA_BASE_URL,
    timeout_seconds: int = 180,
    progress_callback: Callable[[Dict[str, Any]], None] | None = None,
) -> ProviderUsage:
    """Load the selected model before document analysis using a tiny local request."""
    model = (model or "").strip()
    if not model:
        raise RuntimeError("Ollama model name is blank.")
    started = time.monotonic()
    if progress_callback:
        progress_callback({"state": "loading", "elapsed_seconds": 0.0, "model": model})
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with only READY."}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_predict": 8},
        "keep_alive": "15m",
    }
    url = f"{_normalize_ollama_base_url(base_url)}/api/chat"
    try:
        response = requests.post(url, json=body, timeout=(10, timeout_seconds))
    except requests.ReadTimeout as exc:
        raise RuntimeError(f"Ollama model '{model}' did not finish loading within {timeout_seconds} seconds.") from exc
    except requests.ConnectTimeout as exc:
        raise RuntimeError("Ollama service connection timed out during model warm-up.") from exc
    except requests.ConnectionError as exc:
        raise RuntimeError("Ollama service is unavailable during model warm-up. Start Ollama and try again.") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"Ollama warm-up request failed: {exc}") from exc
    if response.status_code >= 400:
        detail = response.text[:700]
        try:
            detail = response.json().get("error") or detail
        except Exception:
            logging.getLogger(__name__).warning("Recovery fallback in ai_reader; operation did not complete.", exc_info=True)
        low = str(detail).lower()
        if response.status_code == 404 or "not found" in low:
            raise RuntimeError(f"Ollama model '{model}' is not installed. Run: ollama pull {model}")
        if "memory" in low or "out of memory" in low:
            raise RuntimeError(f"Ollama ran out of memory while loading model '{model}': {detail}")
        raise RuntimeError(f"Ollama returned HTTP {response.status_code} during model warm-up: {detail}")
    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError(f"Ollama warm-up returned invalid JSON: {exc}") from exc
    usage = _ollama_usage(payload)
    if progress_callback:
        progress_callback({
            "state": "ready",
            "elapsed_seconds": time.monotonic() - started,
            "model": model,
            "output_tokens": usage.output_tokens,
        })
    return usage

def read_pages_ollama(
    *,
    pages: Sequence[FieldBookPage],
    target_point_ids: Iterable[str],
    model: str = "qwen3-vl:4b-instruct",
    base_url: str = OLLAMA_BASE_URL,
    timeout_seconds: int = 300,
    profile_context: str = "",
    progress_callback: Callable[[Dict[str, Any]], None] | None = None,
) -> tuple[List[PageEvidence], List[UnmatchedEvidence], ProviderUsage]:
    """Read rendered field-book pages with a local Ollama vision model.

    v8.1.21 consumes Ollama's streaming response so long local inference continues to
    produce coordinator progress instead of looking like a dead worker.
    """
    if not pages:
        return [], [], ProviderUsage()
    targets = [normalize_point_id(v) for v in target_point_ids if normalize_point_id(v)]
    if not targets:
        return [], [], ProviderUsage()
    target_set = set(targets)
    page_by_id = {p.page_id: p for p in pages}

    ordered_pages = "\n".join(
        f"Image {i + 1}: PAGE_ID={page.page_id} | SOURCE={page.source_name} | PAGE_NUMBER={page.page_number} "
        f"| PAGE_TYPE={page.page_type or 'unknown'} | FIELD_NOTE_OVERRIDE={page.field_note_profile_override or page.field_note_profile_book or 'AUTO'} | ROUTING_NOTE={specialized_prompt_note(page.page_type or 'unknown')}"
        for i, page in enumerate(pages)
    )
    content = (
        system_prompt(profile_context)
        + "\nReturn ONLY JSON matching the supplied response schema.\n\n"
        + "Analyze the attached field-book page image(s). The images are attached in exactly this order:\n"
        + ordered_pages
        + "\n\nEvery returned entry and unmatched candidate MUST use exactly one PAGE_ID listed above. "
          "Do not invent a page ID and do not fuzzy-match PointIDs.\n\n"
        + f"Target PointIDs for this pass:\n{', '.join(targets)}"
    )
    images = [base64.b64encode(_prepare_image_bytes(p.image_path, max_dim=2600, quality=88)).decode("ascii") for p in pages]
    model_name = model.strip() or "qwen3-vl:4b-instruct"
    body = {
        "model": model_name,
        "messages": [{"role": "user", "content": content, "images": images}],
        "stream": True,
        "think": False,
        "format": GEMINI_BATCH_SCHEMA,
        "options": {"temperature": 0, "top_p": 0.9},
        "keep_alive": "15m",
    }
    url = f"{_normalize_ollama_base_url(base_url)}/api/chat"
    started = time.monotonic()
    if progress_callback:
        progress_callback({"state": "requesting", "elapsed_seconds": 0.0, "model": model_name, "chunks": 0})
    try:
        response = requests.post(url, json=body, stream=True, timeout=(10, timeout_seconds))
    except requests.ReadTimeout as exc:
        raise RuntimeError(f"Ollama inference timed out for model '{model_name}' after {timeout_seconds} seconds without output.") from exc
    except requests.ConnectTimeout as exc:
        raise RuntimeError("Ollama service connection timed out before inference began.") from exc
    except requests.ConnectionError as exc:
        raise RuntimeError("Ollama service is unavailable. Start Ollama and retry the analysis.") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"Ollama inference request failed: {exc}") from exc
    if response.status_code >= 400:
        detail = response.text[:700]
        try:
            detail = response.json().get("error") or detail
        except Exception:
            logging.getLogger(__name__).warning("Recovery fallback in ai_reader; operation did not complete.", exc_info=True)
        low = str(detail).lower()
        if response.status_code == 404 or "not found" in low:
            raise RuntimeError(f"Ollama model '{model_name}' is not installed. Run: ollama pull {model_name}")
        if "memory" in low or "out of memory" in low:
            raise RuntimeError(f"Ollama ran out of memory while running model '{model_name}': {detail}")
        raise RuntimeError(f"Ollama returned HTTP {response.status_code}: {detail}")

    chunks: List[str] = []
    final_payload: Dict[str, Any] = {}
    chunk_count = 0
    # Compatibility with simple response wrappers and older Ollama proxies that
    # buffer the whole response even when stream=true.
    if not hasattr(response, "iter_lines"):
        try:
            final_payload = response.json()
            message = final_payload.get("message") or {}
            piece = message.get("content")
            if isinstance(piece, str):
                chunks.append(piece)
            chunk_count = 1
        except Exception as exc:
            raise RuntimeError(f"Ollama response could not be read: {exc}") from exc
    try:
        line_iter = response.iter_lines(decode_unicode=True) if hasattr(response, "iter_lines") else []
        for raw_line in line_iter:
            if not raw_line:
                continue
            payload = json.loads(raw_line)
            if payload.get("error"):
                detail = str(payload.get("error"))
                if "memory" in detail.lower():
                    raise RuntimeError(f"Ollama ran out of memory while running model '{model_name}': {detail}")
                raise RuntimeError(f"Ollama inference failed: {detail}")
            message = payload.get("message") or {}
            piece = message.get("content")
            if isinstance(piece, str) and piece:
                chunks.append(piece)
            chunk_count += 1
            if progress_callback:
                progress_callback({
                    "state": "generating",
                    "elapsed_seconds": time.monotonic() - started,
                    "model": model_name,
                    "chunks": chunk_count,
                    "output_chars": sum(len(x) for x in chunks),
                })
            if payload.get("done"):
                final_payload = payload
                break
    except requests.ReadTimeout as exc:
        raise RuntimeError(f"Ollama inference timed out for model '{model_name}' after {timeout_seconds} seconds without a streamed update.") from exc
    except requests.ConnectionError as exc:
        raise RuntimeError("Ollama connection was interrupted during inference. Completed OCR checkpoints were preserved.") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ollama streaming response contained invalid JSON: {exc}") from exc

    text = "".join(chunks).strip()
    if not text:
        raise RuntimeError("Ollama/Qwen response contained no generated content.")
    try:
        parsed = json.loads(text)
    except Exception as exc:
        raise RuntimeError(f"Ollama/Qwen response could not be parsed as structured JSON: {exc}") from exc
    usage = _ollama_usage(final_payload)
    if progress_callback:
        progress_callback({
            "state": "complete",
            "elapsed_seconds": time.monotonic() - started,
            "model": model_name,
            "chunks": chunk_count,
            "output_tokens": usage.output_tokens,
        })

    evidence: List[PageEvidence] = []
    unmatched: List[UnmatchedEvidence] = []
    for item in parsed.get("entries", []) or []:
        page = page_by_id.get(str(item.get("page_id", "")))
        if page is None:
            continue
        ev, blocked = _entry_to_evidence(item, page=page, target_set=target_set)
        if ev:
            evidence.append(ev)
        if blocked:
            unmatched.append(blocked)
    for item in parsed.get("unmatched", []) or []:
        page = page_by_id.get(str(item.get("page_id", "")))
        if page is None:
            continue
        unmatched.append(UnmatchedEvidence(
            source_name=page.source_name,
            page_number=page.page_number,
            page_id=page.page_id,
            point_id_raw=item.get("point_id_raw"),
            confidence=float(item.get("confidence", 0) or 0),
            reason=item.get("reason", "Uncertain handwritten PointID or association."),
            bbox=item.get("bbox"),
        ))
    return evidence, unmatched, usage


def read_pages_foundry(
    *,
    pages: Sequence[FieldBookPage],
    target_point_ids: Iterable[str],
    model: str = DEFAULT_FOUNDRY_VISION_MODEL,
    timeout_seconds: int = 360,
    profile_context: str = "",
) -> tuple[List[PageEvidence], List[UnmatchedEvidence], ProviderUsage]:
    """Read field-book pages with Microsoft Foundry Local vision.

    The Foundry runtime and model execute on the user's PC. SurveySync validates every
    returned PointID and PAGE_ID exactly the same way as its other AI providers.
    """
    if not pages:
        return [], [], ProviderUsage()
    targets = [normalize_point_id(v) for v in target_point_ids if normalize_point_id(v)]
    if not targets:
        return [], [], ProviderUsage()
    target_set = set(targets)
    page_by_id = {p.page_id: p for p in pages}
    ordered_pages = "\n".join(
        f"Image {i + 1}: PAGE_ID={page.page_id} | SOURCE={page.source_name} | PAGE_NUMBER={page.page_number} "
        f"| PAGE_TYPE={page.page_type or 'unknown'} | FIELD_NOTE_OVERRIDE={page.field_note_profile_override or page.field_note_profile_book or 'AUTO'} | ROUTING_NOTE={specialized_prompt_note(page.page_type or 'unknown')}"
        for i, page in enumerate(pages)
    )
    prompt = (
        system_prompt(profile_context)
        + "\nReturn ONLY one JSON object. Do not wrap it in markdown. The JSON must have keys entries and unmatched. "
          "Every entry and unmatched object MUST include PAGE_ID from the list below.\n\n"
        + "Attached images are in exactly this order:\n"
        + ordered_pages
        + "\n\nTarget PointIDs for this pass:\n"
        + ", ".join(targets)
        + "\n\nEach entries item must contain page_id plus all fields required by the SurveySync extraction schema. "
          "Each unmatched item must contain page_id, point_id_raw, confidence, reason, bbox."
    )
    result = foundry_vision_json(
        [p.image_path for p in pages], prompt=prompt, model_alias=model, timeout_seconds=timeout_seconds
    )
    parsed = result["data"]
    evidence: List[PageEvidence] = []
    unmatched: List[UnmatchedEvidence] = []
    for item in parsed.get("entries", []) or []:
        page = page_by_id.get(str(item.get("page_id", "")))
        if page is None:
            continue
        ev, blocked = _entry_to_evidence(item, page=page, target_set=target_set)
        if ev:
            ev.primary_engine = f"Microsoft Foundry Local ({result.get('model') or model})"
            evidence.append(ev)
        if blocked:
            unmatched.append(blocked)
    for item in parsed.get("unmatched", []) or []:
        page = page_by_id.get(str(item.get("page_id", "")))
        if page is None:
            continue
        unmatched.append(UnmatchedEvidence(
            source_name=page.source_name,
            page_number=page.page_number,
            page_id=page.page_id,
            point_id_raw=item.get("point_id_raw"),
            confidence=float(item.get("confidence", 0) or 0),
            reason=item.get("reason", "Uncertain handwritten PointID or association."),
            bbox=item.get("bbox"),
        ))
    raw = result.get("raw") or {}
    usage_data = raw.get("usage") or {}
    usage = ProviderUsage(
        requests=1,
        input_tokens=int(usage_data.get("input_tokens", 0) or 0),
        output_tokens=int(usage_data.get("output_tokens", 0) or 0),
        total_tokens=int(usage_data.get("total_tokens", 0) or 0),
    )
    return evidence, unmatched, usage

def list_gemini_models(*, api_key: str, timeout_seconds: int = 30) -> List[str]:
    """Return vision-capable generateContent model names available to this Gemini key."""
    try:
        response = requests.get(
            f"{GEMINI_BASE_URL}/models",
            headers={"x-goog-api-key": api_key},
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach Gemini: {exc}") from exc
    if response.status_code >= 400:
        raise _request_error("Gemini", response)
    names: List[str] = []
    for model in (response.json().get("models") or []):
        methods = set(model.get("supportedGenerationMethods") or [])
        name = str(model.get("name") or "").removeprefix("models/")
        if name and "generateContent" in methods and "embedding" not in name.lower():
            names.append(name)
    return sorted(set(names))


# Backward-compatible alias used by older tests/extensions.
def read_page(**kwargs):
    evidence, unmatched, _usage = read_page_openai(**kwargs)
    return evidence, unmatched
