from __future__ import annotations

import csv
import io
import re
from collections import Counter
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, TextIO, Tuple

from .models import CodeProfile, MatchMode, SurveyImportIssue, SurveyPoint
from surveysync.reports import available_ranges as _shared_available_ranges
from surveysync.trimble_job import prepare_jobxml, parse_jobxml_points, numeric_point_ids as _trimble_numeric_point_ids, TrimbleJobError


HEADER_ALIASES = {
    "point_id": ("pointid", "point_id", "point", "pt", "pointno", "point_no", "pointnumber", "point_number"),
    "northing": ("northing", "north", "n", "y"),
    "easting": ("easting", "east", "e", "x"),
    "elevation": ("elevation", "elev", "height", "z", "el"),
    "code": ("code", "desc", "description", "featurecode", "feature_code"),
}

SUPPORTED_DELIMITERS = (",", "\t", ";", "|")


def normalize_point_id(value: object) -> str:
    text = str(value).strip()
    # Common spreadsheet/export artifact: integer IDs serialized as 1000.0.
    if re.fullmatch(r"[+-]?\d+\.0+", text):
        text = text.split(".", 1)[0]
    return text


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", value.strip().lower().replace(" ", "_"))


def _find_header_mapping(header: Sequence[str]) -> Optional[dict[str, int]]:
    normalized = [_normalize_header(h) for h in header]
    mapping: dict[str, int] = {}
    for target, aliases in HEADER_ALIASES.items():
        for i, col in enumerate(normalized):
            if col in aliases:
                mapping[target] = i
                break
    if {"point_id", "northing", "easting", "elevation", "code"}.issubset(mapping):
        return mapping
    return None


def _float_or_none(value: str) -> Optional[float]:
    text = value.strip()
    if text == "":
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _match_code(code: str, profile: CodeProfile) -> Optional[str]:
    candidate = code.strip().casefold()
    # More specific/longer rules first prevents a short CONTAINS rule stealing a match.
    rules = sorted((r for r in profile.codes if r.include), key=lambda r: len(r.code), reverse=True)
    for rule in rules:
        target = rule.code.strip().casefold()
        if not target:
            continue
        if rule.match == MatchMode.EXACT and candidate == target:
            return rule.category
        if rule.match == MatchMode.STARTS_WITH and candidate.startswith(target):
            return rule.category
        if rule.match == MatchMode.CONTAINS and target in candidate:
            return rule.category
    return None


def _delimiter_score(sample: str, delimiter: str) -> tuple[float, int, int]:
    """Score a delimiter by row consistency and whether it yields a recognizable header.

    csv.Sniffer is useful but can be brittle when descriptions contain punctuation or when the
    sample contains malformed lines. This deterministic score is used both to validate Sniffer's
    choice and as a fallback. Higher is better.
    """
    try:
        rows = []
        for row in csv.reader(io.StringIO(sample), delimiter=delimiter):
            if row and any(cell.strip() for cell in row):
                rows.append(row)
            if len(rows) >= 80:
                break
    except csv.Error:
        return (-1.0, 0, 0)
    if not rows:
        return (-1.0, 0, 0)
    counts = [len(r) for r in rows]
    multi = [c for c in counts if c > 1]
    if not multi:
        return (0.0, 1, len(rows))
    mode_count, mode_freq = Counter(multi).most_common(1)[0]
    consistency = mode_freq / max(1, len(multi))
    coverage = len(multi) / len(rows)
    expected_bonus = 0.35 if mode_count >= 5 else 0.0
    header_bonus = 0.8 if _find_header_mapping(rows[0]) else 0.0
    # Reward a stable multi-column shape much more than incidental punctuation.
    score = (consistency * 2.0) + coverage + expected_bonus + header_bonus
    return (score, mode_count, len(rows))


def detect_delimiter(sample: str) -> tuple[str, Optional[str]]:
    """Return (delimiter, warning). Never raises csv.Error.

    Strategy:
      1. Ask csv.Sniffer for a candidate.
      2. Independently score all supported delimiters.
      3. Prefer the highest-scoring delimiter, using Sniffer only as a tie-breaker.
      4. If no candidate looks convincingly tabular, fall back to comma and return a warning.
    """
    clean = sample.lstrip("\ufeff")
    sniffed: Optional[str] = None
    try:
        sniffed = csv.Sniffer().sniff(clean, delimiters="".join(SUPPORTED_DELIMITERS)).delimiter
    except csv.Error:
        sniffed = None

    scored = {d: _delimiter_score(clean, d) for d in SUPPORTED_DELIMITERS}
    best_score = max(v[0] for v in scored.values())
    best = [d for d, v in scored.items() if abs(v[0] - best_score) < 1e-9]
    if sniffed in best:
        delimiter = sniffed  # stable tie-breaker
    else:
        delimiter = best[0]

    score, columns, nonempty_rows = scored[delimiter]
    warning = None
    if score <= 0.75 or columns <= 1:
        delimiter = ","
        warning = (
            "Delimiter detection was uncertain; FieldBook Sync fell back to comma. "
            "Verify the imported columns if this is a non-comma field file."
        )
    elif sniffed and sniffed != delimiter:
        warning = (
            f"CSV Sniffer suggested {repr(sniffed)}, but row-consistency checks selected {repr(delimiter)}. "
            "The consistency-validated delimiter was used."
        )
    return delimiter, warning


def _parse_survey_text(stream: TextIO, source_file: str, profile: CodeProfile) -> Tuple[List[SurveyPoint], List[SurveyImportIssue]]:
    # Read a bounded sample only, then seek back. This keeps large survey files streaming.
    sample = stream.read(65536)
    if not sample.strip():
        return [], [SurveyImportIssue(source_file=source_file, source_row=0, message="File is empty.")]
    delimiter, warning = detect_delimiter(sample)
    stream.seek(0)

    reader = csv.reader(stream, delimiter=delimiter)
    try:
        first = next(reader)
    except StopIteration:
        return [], [SurveyImportIssue(source_file=source_file, source_row=0, message="No rows found.")]
    except csv.Error as exc:
        return [], [SurveyImportIssue(source_file=source_file, source_row=0, message=f"Could not parse the first survey row: {exc}")]

    header_map = _find_header_mapping(first)
    first_is_header = header_map is not None
    if header_map is None:
        header_map = {"point_id": 0, "northing": 1, "easting": 2, "elevation": 3, "code": 4}

    points: List[SurveyPoint] = []
    issues: List[SurveyImportIssue] = []
    if warning:
        issues.append(SurveyImportIssue(source_file=source_file, source_row=0, message=warning))

    def process_row(row: list[str], row_number: int) -> None:
        if not row or all(not cell.strip() for cell in row):
            return
        needed = max(header_map.values()) + 1
        if len(row) < needed:
            issues.append(SurveyImportIssue(
                source_file=source_file,
                source_row=row_number,
                message=f"Expected at least {needed} columns but found {len(row)}.",
                raw=delimiter.join(row),
            ))
            return

        point_id = normalize_point_id(row[header_map["point_id"]])
        code = row[header_map["code"]].strip()
        if not point_id:
            issues.append(SurveyImportIssue(source_file=source_file, source_row=row_number, message="Missing PointID.", raw=delimiter.join(row)))
            return
        if not code:
            issues.append(SurveyImportIssue(source_file=source_file, source_row=row_number, message=f"Point {point_id} has no code.", raw=delimiter.join(row)))
            return

        category = _match_code(code, profile)
        if category is None:
            return

        northing = _float_or_none(row[header_map["northing"]])
        easting = _float_or_none(row[header_map["easting"]])
        elevation = _float_or_none(row[header_map["elevation"]])
        if northing is None or easting is None:
            issues.append(SurveyImportIssue(
                source_file=source_file,
                source_row=row_number,
                message=f"Point {point_id} has invalid Northing/Easting; retained for field-book matching but GIS export may be incomplete.",
                raw=delimiter.join(row),
            ))
        if elevation is None and row[header_map["elevation"]].strip():
            issues.append(SurveyImportIssue(
                source_file=source_file,
                source_row=row_number,
                message=f"Point {point_id} has an invalid elevation value.",
                raw=delimiter.join(row),
            ))

        points.append(SurveyPoint(
            point_id=point_id,
            northing=northing,
            easting=easting,
            elevation=elevation,
            code=code,
            category=category,
            source_file=source_file,
            source_row=row_number,
        ))

    if not first_is_header:
        process_row(first, 1)

    start = 2
    try:
        for row_number, row in enumerate(reader, start=start):
            process_row(row, row_number)
    except csv.Error as exc:
        issues.append(SurveyImportIssue(
            source_file=source_file,
            source_row=getattr(reader, "line_num", 0) or 0,
            message=f"Malformed CSV near this row: {exc}. Rows parsed before the error were retained.",
        ))

    return points, issues



def extract_numeric_point_ids(stream: TextIO) -> tuple[list[int], int]:
    """Extract numeric PointIDs from a raw survey text stream without applying code-profile filters.

    The dedicated point-range tool needs every numeric point number in the uploaded survey,
    not only the structure codes selected by the active profile. A recognizable PointID header
    is preferred; otherwise the first column is used, matching the normal headerless survey
    import convention. Non-numeric/alphanumeric PointIDs are ignored and counted.
    """
    sample = stream.read(65536)
    if not sample.strip():
        return [], 0
    delimiter, _ = detect_delimiter(sample)
    stream.seek(0)
    reader = csv.reader(stream, delimiter=delimiter)
    try:
        first = next(reader)
    except (StopIteration, csv.Error):
        return [], 0

    normalized = [_normalize_header(h) for h in first]
    point_col = 0
    has_header = False
    for i, col in enumerate(normalized):
        if col in HEADER_ALIASES["point_id"]:
            point_col = i
            has_header = True
            break

    ids: list[int] = []
    skipped = 0

    def consume(row: Sequence[str]) -> None:
        nonlocal skipped
        if not row or point_col >= len(row):
            return
        raw = normalize_point_id(row[point_col])
        if not raw:
            return
        if re.fullmatch(r"\d+", raw):
            ids.append(int(raw))
        else:
            skipped += 1

    if not has_header:
        consume(first)
    for row in reader:
        consume(row)
    return ids, skipped


def extract_numeric_point_ids_file(path: Path) -> tuple[list[int], int]:
    path = Path(path)
    if path.suffix.lower() in {".job", ".jxl", ".xml"}:
        try:
            jobxml_path, _conversion = prepare_jobxml(path, path.parent / ".surveysync_trimble")
            parsed = parse_jobxml_points(jobxml_path)
            return _trimble_numeric_point_ids(parsed.get("points", []))
        except TrimbleJobError as exc:
            raise ValueError(str(exc)) from exc
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
        return extract_numeric_point_ids(stream)


def available_point_ranges(point_ids: Iterable[int]) -> list[tuple[int, Optional[int]]]:
    """Return unused ranges using SurveySync's canonical gap-walk algorithm.

    ``None`` as the final end value preserves the FieldBookSync convention that
    point numbers above the highest occupied PointID remain available.
    """
    used = sorted({int(v) for v in point_ids if int(v) >= 0})
    if not used:
        return []
    ranges = _shared_available_ranges(used, include_open_ended=True)
    return [(int(r["start"]), None if r["end"] is None else int(r["end"])) for r in ranges]


def parse_survey_bytes(raw: bytes, source_file: str, profile: CodeProfile) -> Tuple[List[SurveyPoint], List[SurveyImportIssue]]:
    text = raw.decode("utf-8-sig", errors="replace")
    return _parse_survey_text(io.StringIO(text), source_file, profile)


def _parse_trimble_survey_file(path: Path, source_file: str, profile: CodeProfile) -> Tuple[List[SurveyPoint], List[SurveyImportIssue]]:
    try:
        jobxml_path, conversion = prepare_jobxml(path, Path(path).parent / ".surveysync_trimble")
        parsed = parse_jobxml_points(jobxml_path)
    except TrimbleJobError as exc:
        raise ValueError(str(exc)) from exc

    points: List[SurveyPoint] = []
    issues: List[SurveyImportIssue] = []
    duplicates = set((parsed.get("metadata") or {}).get("duplicate_point_ids") or [])
    if conversion.get("converted"):
        issues.append(SurveyImportIssue(
            source_file=source_file,
            source_row=0,
            message="Trimble .job was converted to a derived JobXML copy with Trimble ASCII File Generator; the original upload remains unchanged.",
        ))
    for row_number, row in enumerate(parsed.get("points") or [], start=1):
        point_id = normalize_point_id(row.get("point_id", ""))
        code = str(row.get("code") or "").strip()
        if not point_id:
            continue
        if point_id in duplicates:
            issues.append(SurveyImportIssue(source_file=source_file, source_row=row_number, message=f"Trimble JobXML contains duplicate PointID {point_id}; duplicate review is required."))
        if not code:
            issues.append(SurveyImportIssue(source_file=source_file, source_row=row_number, message=f"Point {point_id} has no Trimble feature code and was not selected as a FieldBook target."))
            continue
        category = _match_code(code, profile)
        if category is None:
            continue
        points.append(SurveyPoint(
            point_id=point_id,
            northing=row.get("northing"),
            easting=row.get("easting"),
            elevation=row.get("elevation"),
            code=code,
            category=category,
            source_file=source_file,
            source_row=row_number,
        ))
    return points, issues


def parse_survey_file(path: Path, source_file: str, profile: CodeProfile) -> Tuple[List[SurveyPoint], List[SurveyImportIssue]]:
    """Parse a survey file without buffering the whole upload in memory.

    Trimble Access JOB files are converted with Trimble's official ASCII File
    Generator to a temporary JobXML representation; SurveySync does not decode the
    proprietary JOB binary directly.
    """
    path = Path(path)
    if path.suffix.lower() in {".job", ".jxl", ".xml"}:
        return _parse_trimble_survey_file(path, source_file, profile)
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
        return _parse_survey_text(stream, source_file, profile)


def merge_survey_points(groups: Iterable[List[SurveyPoint]]) -> Tuple[List[SurveyPoint], List[SurveyImportIssue]]:
    merged: dict[str, SurveyPoint] = {}
    issues: List[SurveyImportIssue] = []
    for points in groups:
        for point in points:
            existing = merged.get(point.point_id)
            if existing is None:
                merged[point.point_id] = point
                continue
            same = (
                existing.northing == point.northing
                and existing.easting == point.easting
                and existing.elevation == point.elevation
                and existing.code.strip().casefold() == point.code.strip().casefold()
            )
            if not same:
                issues.append(SurveyImportIssue(
                    source_file=point.source_file,
                    source_row=point.source_row,
                    message=(
                        f"Duplicate PointID {point.point_id} conflicts with {existing.source_file} row {existing.source_row}. "
                        "The first occurrence was retained and this point should be reviewed."
                    ),
                ))
    return list(merged.values()), issues
