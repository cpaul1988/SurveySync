"""Strict canonical CSV intake; normalize headers, never survey identifiers."""
import csv
import io
from pathlib import Path

from .survey_validation import finite_number, normalize_header


def parse_canonical_points(path: Path) -> list[dict]:
    text = path.read_text(encoding='utf-8-sig')
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=',\t;')
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text, newline=''), dialect=dialect)
    fields = {}
    for field in reader.fieldnames or []:
        normalized = normalize_header(field)
        if not normalized or normalized in fields:
            raise ValueError('Point headers must be non-empty and unique.')
        fields[normalized] = field
    def pick(*names):
        matches = [fields[normalize_header(n)] for n in names if normalize_header(n) in fields]
        if len(matches) > 1:
            raise ValueError('Ambiguous point columns: ' + ', '.join(matches))
        return matches[0] if matches else None
    pid = pick('point_id', 'point', 'pt', 'name')
    north = pick('northing', 'north', 'n', 'y')
    east = pick('easting', 'east', 'e', 'x')
    elevation = pick('elevation', 'elev', 'z')
    description = pick('description', 'desc', 'code')
    if not pid or not north or not east:
        raise ValueError('Point file requires Point ID, Northing and Easting columns.')
    points = []
    for row in reader:
        if all(v is None or (isinstance(v, str) and not v.strip()) for v in row.values()):
            continue
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f'Point CSV row {reader.line_num} has an incorrect column count.')
        point_id = row[pid].strip()
        if not point_id:
            raise ValueError(f'Point CSV row {reader.line_num} is missing its PointID.')
        try:
            n = finite_number(row[north], 'Northing')
            e = finite_number(row[east], 'Easting')
            z = finite_number(row[elevation], 'Elevation') if elevation and row[elevation].strip() else None
        except ValueError as exc:
            raise ValueError(f'Point CSV row {reader.line_num} ({point_id}): {exc}') from exc
        points.append({'point_id': point_id, 'northing': n, 'easting': e, 'elevation': z,
                       'description': row[description] if description else ''})
    if not points:
        raise ValueError('Point file contains no survey points.')
    return points
