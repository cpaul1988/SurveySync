"""Project-bound revision and field review records; source coordinates are never edited."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED

from .point_import import parse_canonical_points
from .visual_qa import snapshot


def now():
    return datetime.now(timezone.utc).isoformat()


def root(project):
    p = project.paths.module_root / 'QASync' / 'ReviewWorkflow'
    p.mkdir(parents=True, exist_ok=True)
    return p


def state(project):
    path = root(project) / 'state.json'
    if not path.exists():
        return {'revisions': [], 'rechecks': [], 'reservations': [], 'evidence': [], 'reports': [], 'policy': {}, 'acknowledgment': None, 'workflow_revision': 0}
    return json.loads(path.read_text(encoding='utf-8'))


def save(project, value):
    path = root(project) / 'state.json'
    temp = path.with_name(uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False), encoding='utf-8')
    temp.replace(path)


def changed(value):
    value['workflow_revision'] = value.get('workflow_revision', 0) + 1
    value['acknowledgment'] = None


def returned_uuids(recheck):
    return {row['point_uuid'] for item in recheck['returns'] for row in item['records']}


def audit(project, action, item, details=None):
    project.db.audit('QASync', action, object_type='review_workflow', object_id=item, details=details or {})


def current(project, token):
    data = snapshot(project)
    if data['snapshot'] != token:
        raise ValueError('Project evidence changed. Refresh the review workspace and try again.')
    return data


def context(project, supplied):
    for k in ('crs', 'horizontal_units', 'vertical_units'):
        expected = project.manifest.get(k, '')
        if not expected or supplied.get(k) != expected:
            raise ValueError(f'{k} must explicitly match the active project ({expected or "unset"}). No coordinate conversion is assumed.')


def revision(project, token, text, supplied, matches=None):
    data = current(project, token)
    context(project, supplied)
    if len(text.encode('utf-8')) > 8_000_000:
        raise ValueError('Revision file exceeds 8 MB.')
    # Reuse the strict intake parser, but parse an in-memory file without saving source bytes.
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as folder:
        path = Path(folder) / 'revision.csv'
        path.write_text(text, encoding='utf-8')
        incoming = parse_canonical_points(path)
    if len(incoming) > 20000:
        raise ValueError('Revision exceeds 20,000 records.')
    old = defaultdict(list); new = defaultdict(list)
    for p in data['points']:
        old[p['point_id']].append(p)
    for row, p in enumerate(incoming, start=2):
        new[p['point_id']].append({**p, 'row': row})
    supplied_matches = matches or []
    pairs = {}; reverse = set()
    old_by_uuid = {p['point_uuid']: p for p in data['points']}
    new_by_row = {p['row']: p for p in (r for group in new.values() for r in group)}
    for match in supplied_matches:
        uid, row = match.get('point_uuid'), match.get('row')
        a, b = old_by_uuid.get(uid), new_by_row.get(row)
        if not a or not b or a['point_id'] != b['point_id'] or uid in pairs or row in reverse:
            raise ValueError('Explicit matches must pair one old UUID to one new row with the same PointID.')
        pairs[uid] = row; reverse.add(row)
    changes = []; ambiguous = []
    for pid in sorted(set(old) | set(new)):
        a, b = old[pid], new[pid]
        if len(a) > 1 or len(b) > 1:
            ambiguous.append({'point_id': pid, 'old_uuids': [p['point_uuid'] for p in a], 'new_rows': [p['row'] for p in b]})
        elif a and b and a[0]['point_uuid'] not in pairs:
            pairs[a[0]['point_uuid']] = b[0]['row']; reverse.add(b[0]['row'])
        for p in a:
            if p['point_uuid'] in pairs:
                q = new_by_row[pairs[p['point_uuid']]]
                dn = q['northing'] - p['northing'] if p['northing'] is not None else None
                de = q['easting'] - p['easting'] if p['easting'] is not None else None
                dz = q['elevation'] - p['elevation'] if q['elevation'] is not None and p['elevation'] is not None else None
                changes.append({'kind': 'changed' if any(p.get(k) != q.get(k) for k in ('northing','easting','elevation','description')) else 'unchanged', 'point_id': pid, 'old_uuid': p['point_uuid'], 'new_row': q['row'], 'old': {k:p.get(k) for k in ('northing','easting','elevation','description')}, 'new': {k:q.get(k) for k in ('northing','easting','elevation','description')}, 'dn': dn, 'de': de, 'dz': dz, 'distance': math.hypot(dn, de) if dn is not None and de is not None else None})
            elif len(a) == 1 and not b:
                changes.append({'kind': 'removed', 'point_id': pid, 'old_uuid': p['point_uuid'], 'old': {k:p.get(k) for k in ('northing','easting','elevation','description')}})
        if not a and len(b) == 1:
            q = b[0]; changes.append({'kind': 'added', 'point_id': pid, 'new_row': q['row'], 'new': {k:q.get(k) for k in ('northing','easting','elevation','description')}})
    unresolved = [{'point_id': x['point_id'], 'old_uuids': [u for u in x['old_uuids'] if u not in pairs], 'new_rows': [r for r in x['new_rows'] if r not in reverse]} for x in ambiguous]
    active = [r for r in state(project)['reservations'] if r['status'] == 'active']
    reservation_conflicts = [{'point_id': p['point_id'], 'row': p['row'], 'reservation_id': r['id'], 'crew': r['crew']} for group in new.values() for p in group if p['point_id'].isdecimal() for r in active if r['start'] <= int(p['point_id']) <= r['end']]
    record = {'reservation_conflicts': reservation_conflicts, 'id': uuid4().hex, 'created_utc': now(), 'snapshot': token, 'source_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(), 'context': supplied, 'changes': changes, 'ambiguous': unresolved, 'incoming_count': len(incoming)}
    s = state(project); s['revisions'].append(record); changed(s); save(project, s)
    audit(project, 'REVISION_COMPARED', record['id'], {'snapshot': token, 'source_sha256': record['source_sha256'], 'changes': len(changes), 'ambiguous': len(unresolved)})
    return record


def reserve(project, start, end, crew, note=''):
    if start < 0 or end < start or end > 999999999 or not crew.strip():
        raise ValueError('Enter a nonnegative ordered range and crew name.')
    s = state(project)
    overlaps = [r for r in s['reservations'] if r['status'] == 'active' and start <= r['end'] and end >= r['start']]
    if overlaps:
        raise ValueError('Range overlaps an active reservation: ' + ', '.join(r['id'] for r in overlaps))
    with project.db.connect() as conn:
        used = [r[0] for r in conn.execute('SELECT point_id FROM canonical_points')]
    occupied = [v for v in used if v.isdecimal() and start <= int(v) <= end]
    if occupied:
        raise ValueError('Range contains existing PointIDs: ' + ', '.join(occupied[:10]))
    r = {'id': uuid4().hex, 'start': start, 'end': end, 'crew': crew.strip(), 'note': note.strip(), 'status': 'active', 'created_utc': now()}
    s['reservations'].append(r); changed(s); save(project, s); audit(project, 'POINT_RANGE_RESERVED', r['id'], r)
    return r


def release(project, identifier):
    s = state(project)
    r = next((x for x in s['reservations'] if x['id'] == identifier and x['status'] == 'active'), None)
    if not r: raise ValueError('Active reservation not found.')
    r['status'] = 'released'; r['released_utc'] = now(); changed(s); save(project, s)
    audit(project, 'POINT_RANGE_RELEASED', identifier); return r


def recheck(project, token, issue_ids, crew, instructions):
    data = current(project, token)
    ids = {i['issue_id']: i for i in data['issues']}
    if not issue_ids or len(set(issue_ids)) != len(issue_ids) or any(i not in ids for i in issue_ids):
        raise ValueError('Select current, distinct QA findings.')
    if len(instructions.strip()) < 3 or not crew.strip(): raise ValueError('Crew and field instructions are required.')
    points = {p['point_uuid']: p for p in data['points']}
    records = [{k: points[u].get(k) for k in ('point_uuid','point_id','northing','easting','elevation','description')} for u in dict.fromkeys(u for i in issue_ids for u in ids[i]['point_uuids'])]
    r = {'id': uuid4().hex, 'created_utc': now(), 'snapshot': token, 'issue_ids': issue_ids, 'crew': crew.strip(), 'instructions': instructions.strip(), 'status': 'open', 'points': records, 'returns': []}
    s = state(project); s['rechecks'].append(r); changed(s); save(project, s); audit(project, 'FIELD_RECHECK_CREATED', r['id'], {'issues': issue_ids, 'crew': crew})
    return r


def return_observations(project, identifier, rows, note):
    s = state(project); r = next((x for x in s['rechecks'] if x['id'] == identifier), None)
    if not r: raise ValueError('Recheck not found.')
    points = {p['point_uuid']: p for p in r['points']}
    previously_returned = returned_uuids(r)
    if previously_returned == set(points): raise ValueError('Recheck is complete.')
    if not rows or len(rows) > len(points) or len({p.get('point_uuid') for p in rows}) != len(rows): raise ValueError('Return distinct requested records.')
    checked = []
    for row in rows:
        p = points.get(row.get('point_uuid'))
        if not p: raise ValueError('Returned UUID is not in this crew package.')
        if p['point_uuid'] in previously_returned: raise ValueError('This record already has a returned observation.')
        values = {}
        for key in ('northing','easting','elevation'):
            v = row.get(key)
            if v is not None and (not isinstance(v, (int,float)) or not math.isfinite(v)):
                raise ValueError('Returned coordinates must be finite numbers.')
            values[key] = v
        if all(value is None for value in values.values()): raise ValueError('Each returned record needs at least one observation.')
        checked.append({'point_uuid': p['point_uuid'], 'point_id': p['point_id'], 'observed': values, 'delta': {key: values[key] - p[key] if values[key] is not None and p[key] is not None else None for key in values}})
    item = {'received_utc': now(), 'note': note.strip(), 'records': checked}
    r['returns'].append(item)
    remaining = set(points) - returned_uuids(r)
    r['status'] = 'open' if remaining else 'returned'
    changed(s); save(project, s)
    audit(project, 'FIELD_RECHECK_RETURNED', identifier, {'count': len(checked), 'remaining_count': len(remaining), 'note': note})
    return r


def attach(project, token, issue_id, filename, content, media_type):
    data = current(project, token)
    if issue_id not in {i['issue_id'] for i in data['issues']}:
        raise ValueError('Finding is not in the current QA snapshot.')
    allowed = {'.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.pdf':'application/pdf'}
    ext = Path(filename).suffix.lower()
    if ext not in allowed or media_type != allowed[ext] or not content or len(content) > 10_000_000:
        raise ValueError('Attach a JPG, PNG, or PDF under 10 MB.')
    if not (content.startswith(b'\xff\xd8') if ext in ('.jpg','.jpeg') else content.startswith(b'\x89PNG\r\n\x1a\n') if ext == '.png' else content.startswith(b'%PDF-')):
        raise ValueError('Attachment content does not match its file type.')
    identifier = uuid4().hex
    folder = project.paths.attachments / 'ReviewWorkflow'; folder.mkdir(parents=True, exist_ok=True)
    path = folder / (identifier + ext)
    with path.open('xb') as out: out.write(content)
    item = {'id': identifier, 'issue_id': issue_id, 'snapshot': token, 'filename': Path(filename).name[:160], 'stored_path': str(path.relative_to(project.paths.root)), 'sha256': hashlib.sha256(content).hexdigest(), 'size': len(content), 'media_type': media_type, 'created_utc': now()}
    s = state(project); s['evidence'].append(item); changed(s); save(project, s); audit(project, 'FINDING_EVIDENCE_ATTACHED', identifier, {k:v for k,v in item.items() if k != 'stored_path'})
    return item


def readiness(project, token):
    data = current(project, token); s = state(project); policy = s['policy']
    unresolved = [i for i in data['issues'] if not i.get('review') or i['review'].get('decision') == 'needs_review']
    with project.db.connect() as conn:
        occupied = {r[0] for r in conn.execute('SELECT point_id FROM canonical_points') if r[0].isdecimal()}
    conflicts = [r['id'] for r in s['reservations'] if r['status'] == 'active' and any(r['start'] <= int(v) <= r['end'] for v in occupied)]
    conflicts += [c['reservation_id'] for c in (s['revisions'][-1].get('reservation_conflicts', []) if s['revisions'] and s['revisions'][-1]['snapshot'] == token else []) if any(r['id'] == c['reservation_id'] and r['status'] == 'active' for r in s['reservations'])]
    latest_revision = s['revisions'][-1] if s['revisions'] and s['revisions'][-1]['snapshot'] == token else None
    ambiguous = [a for a in (latest_revision or {}).get('ambiguous', []) if a['old_uuids'] or a['new_rows']]
    checks = {'revision_matches_resolved': not ambiguous, 'coordinate_context': bool(data['project']['crs'] and data['project']['horizontal_units'] and data['project']['vertical_units'] and not any(i['kind']=='coordinate_context' for i in data['issues'])), 'findings_reviewed': not unresolved, 'rechecks_returned': all(returned_uuids(r) == {p['point_uuid'] for p in r['points']} for r in s['rechecks']), 'range_conflicts': not conflicts, 'report_present': any(r['snapshot'] == token and r.get('workflow_revision', 0) == s.get('workflow_revision', 0) and Path(r['path']).is_file() and hashlib.sha256(Path(r['path']).read_bytes()).hexdigest() == r['sha256'] for r in s['reports']), 'reviewer_acknowledged': bool(s['acknowledgment'] and s['acknowledgment']['snapshot'] == token and s['acknowledgment'].get('workflow_revision', 0) == s.get('workflow_revision', 0))}
    required = {k: bool(policy.get(k, True)) for k in checks}
    return {'snapshot': token, 'ready': all(checks[k] for k in checks if required[k]), 'checks': checks, 'required': required, 'unresolved_issue_ids': [i['issue_id'] for i in unresolved], 'range_conflicts': conflicts, 'ambiguous_revision_ids': [a['point_id'] for a in ambiguous], 'acknowledgment': s['acknowledgment']}


def policy(project, values):
    allowed = {'coordinate_context','findings_reviewed','rechecks_returned','range_conflicts','report_present','reviewer_acknowledged','revision_matches_resolved','enforce_delivery'}
    if set(values) - allowed or any(type(v) is not bool for v in values.values()): raise ValueError('Invalid readiness policy.')
    s = state(project); s['policy'] = {**s['policy'], **values}; changed(s); save(project, s)
    audit(project, 'READINESS_POLICY_SAVED', project.manifest['project_id'], s['policy']); return s['policy']


def acknowledge(project, token, reviewer, note):
    current(project, token)
    if not reviewer.strip() or len(note.strip()) < 3: raise ValueError('Reviewer and acknowledgment note are required.')
    s = state(project); s['acknowledgment'] = {'snapshot': token, 'reviewer': reviewer.strip(), 'note': note.strip(), 'created_utc': now(), 'workflow_revision': s.get('workflow_revision', 0)}; save(project, s)
    audit(project, 'READINESS_ACKNOWLEDGED', token, s['acknowledgment']); return readiness(project, token)


def report(project, token, selected_ids):
    data = current(project, token); s = state(project)
    chosen = [e for e in s['evidence'] if e['id'] in selected_ids and e['snapshot'] == token]
    if len(chosen) != len(selected_ids) or len(set(selected_ids)) != len(selected_ids): raise ValueError('Select evidence from the current snapshot only.')
    summary = readiness(project, token)
    # Use a simple dedicated PDF page layout to keep reports independent of screen filters.
    import fitz
    doc = fitz.open(); lines = ['SurveySync Review Workflow', f"Project: {project.manifest['name']}", f'Snapshot: {token}', f'Generated: {now()}', '', 'Readiness checks:']
    lines += [f"{k}: {'PASS' if value else 'BLOCKED'} {'(required)' if summary['required'][k] else '(optional)'}" for k,value in summary['checks'].items()]
    lines += ['', f"Revisions: {len(s['revisions'])}", f"Field rechecks: {len(s['rechecks'])}", f"Reservations: {len(s['reservations'])}", f"Selected evidence: {len(chosen)}", '', 'Current findings:']
    lines += [f"{i['kind']} | {i['issue_id'][:12]} | {i['review']['decision'] if i.get('review') else 'unreviewed'}" for i in data['issues']]
    for start in range(0,len(lines),42):
        page = doc.new_page(); page.insert_text((44,50), '\n'.join(lines[start:start+42]), fontsize=10, fontname='cour')
    pdf = doc.tobytes(); doc.close()
    output = io.StringIO(newline=''); writer = csv.writer(output); writer.writerow(['Kind','PointID','OldUUID','NewRow','DeltaN','DeltaE','DeltaZ','Distance'])
    def csv_safe(value):
        text = '' if value is None else str(value)
        return "'" + text if text.lstrip().startswith(('=','+','-','@','\t','\r')) else text
    for r in s['revisions']:
        for c in r['changes']: writer.writerow([csv_safe(c.get(k,'')) for k in ('kind','point_id','old_uuid','new_row','dn','de','dz','distance')])
    payload = {'project': data['project'], 'snapshot': token, 'readiness': summary, 'revisions': s['revisions'], 'rechecks': s['rechecks'], 'reservations': s['reservations'], 'evidence': chosen, 'issues': data['issues']}
    for e in chosen:
        path = (project.paths.root / e['stored_path']).resolve()
        if not path.is_relative_to(project.paths.attachments.resolve()) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != e['sha256']:
            raise ValueError('Evidence missing or changed; report was not generated.')
    target = project.paths.reports / ('SurveySync_Review_' + uuid4().hex + '.zip')
    with ZipFile(target,'w',ZIP_DEFLATED) as z:
        z.writestr('Review.pdf',pdf); z.writestr('Revision_Changes.csv',output.getvalue()); z.writestr('Review_Evidence.json',json.dumps(payload,indent=2,allow_nan=False))
        for e in chosen:
            path = (project.paths.root / e['stored_path']).resolve()
            z.write(path, 'Attachments/' + e['id'] + Path(e['filename']).suffix.lower())
    item = {'id': uuid4().hex, 'snapshot': token, 'path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'created_utc': now(), 'workflow_revision': s.get('workflow_revision', 0)}
    s['reports'].append(item); save(project,s); audit(project,'REVIEW_REPORT_GENERATED',item['id'],item)
    return item


def crew_package(project, identifier):
    s = state(project); r = next((x for x in s['rechecks'] if x['id'] == identifier), None)
    if not r: raise ValueError('Recheck not found.')
    import fitz
    doc = fitz.open()
    lines = ['SurveySync Field Recheck', f"Crew: {r['crew']}", f"Request: {r['id']}", f"Instructions: {r['instructions']}", 'Record UUID | PointID | Northing | Easting | Elevation']
    lines += [f"{p['point_uuid']} | {p['point_id']} | {p['northing']} | {p['easting']} | {p['elevation']}" for p in r['points']]
    for start in range(0,len(lines),40): doc.new_page().insert_text((30,50),'\n'.join(lines[start:start+40]),fontsize=8,fontname='cour')
    output = io.StringIO(newline=''); w = csv.writer(output); w.writerow(['PointUUID','PointID','Northing','Easting','Elevation','ObservedNorthing','ObservedEasting','ObservedElevation','Notes'])
    for p in r['points']: w.writerow([p['point_uuid'],p['point_id'],p['northing'],p['easting'],p['elevation'],'','','',''])
    blob = io.BytesIO()
    with ZipFile(blob,'w',ZIP_DEFLATED) as z:
        z.writestr('Field_Recheck.pdf',doc.tobytes()); z.writestr('Field_Recheck.csv',output.getvalue()); z.writestr('Request.json',json.dumps(r,indent=2))
    doc.close(); return blob.getvalue()


def report_bytes(project, identifier):
    import re
    if not re.fullmatch(r'[0-9a-f]{32}', identifier):
        raise ValueError('Review report not found.')
    item = next((r for r in state(project)['reports'] if r['id'] == identifier), None)
    if item is None:
        raise ValueError('Review report not found.')
    path = Path(item['path']).resolve()
    if not path.is_relative_to(project.paths.reports.resolve()) or not path.is_file():
        raise ValueError('Review report is missing from this project.')
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != item['sha256']:
        raise ValueError('Review report changed since it was generated.')
    return content
