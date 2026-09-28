"""Report content, pagination and project/export isolation against real databases."""
import csv
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile

import fitz
import unicodedata
from test_audit_reproductions import workspace
from test_visual_qa import seed, get, payload


def unpack(response):
    assert response.status_code == 200, response.text
    with ZipFile(io.BytesIO(response.content)) as z:
        files = {n:z.read(n) for n in z.namelist()}
    for line in files['SHA256SUMS.txt'].decode().splitlines():
        digest, name = line.split('  ')
        assert hashlib.sha256(files[name]).hexdigest() == digest
    return files, json.loads(files['review_evidence.json'])


def test_complete_report_reviews_separate_exports_and_source_preservation(workspace, tmp_path):
    client,project,headers,path=seed(workspace,tmp_path)
    original=path.read_bytes(); d=get(client,headers)
    issue=d['issues'][0]
    assert client.post('/api/v9/visual-qa/review',headers=headers,json={**payload(d),'issue_id':issue['issue_id'],'decision':'confirmed'}).status_code==200
    for offset in (-4, -3):
        assert client.post('/api/v9/visual-qa/export',headers=headers,json={**payload(d),'confirmed':True,'changes':[{'point_uuid':d['points'][1]['point_uuid'],'offset':offset}]}).status_code==200
    files,e=unpack(client.post('/api/v9/visual-qa/report',headers=headers,json={**payload(d),'title':'BRT <QA> Review','prepared_by':'Ron & CP'}))
    assert e['issues'][0]['review']['decision']=='confirmed'
    rows=list(csv.DictReader(io.StringIO(files['corrections.csv'].decode('utf-8-sig'))))
    assert [r['exported_elevation'] for r in rows]==['10.0','11.0']
    assert len({r['export_event_id'] for r in rows})==2
    findings=list(csv.DictReader(io.StringIO(files['findings.csv'].decode('utf-8-sig'))))
    assert len(findings)==sum(len(i['point_uuids']) for i in d['issues'])
    with fitz.open(stream=files['QA_Review.pdf'],filetype='pdf') as pdf:
        text=unicodedata.normalize('NFKC', ''.join(p.get_text() for p in pdf))
        assert 'BRT <QA> Review' in text and 'Ron & CP' in text
        assert 'confirmed' in text and '001A' in text
        assert 'separate' in text and 'Registered SHA-256' in text
        assert all('Page '+str(n) in p.get_text() for n,p in enumerate(pdf,1))
    assert get(client,headers)['snapshot']==d['snapshot']
    assert path.read_bytes()==original
    assert project.db.verify_audit_chain()['ok']


def test_stale_wrong_project_and_whitespace_title_rejected(workspace,tmp_path):
    client,project,headers,_=seed(workspace,tmp_path);d=get(client,headers)
    assert client.post('/api/v9/visual-qa/report',json=payload(d)).status_code==409
    assert client.post('/api/v9/visual-qa/report',headers={'X-SurveySync-Project':'other'},json=payload(d)).status_code==409
    assert client.post('/api/v9/visual-qa/report',headers=headers,json={**payload(d),'title':'   '}).status_code==400
    with project.db.connect() as c:c.execute('UPDATE canonical_points SET elevation=20')
    assert client.post('/api/v9/visual-qa/report',headers=headers,json=payload(d)).status_code==409


def test_native_unique_export_and_audit_failure_cleanup(workspace,tmp_path,monkeypatch):
    client,project,headers,_=seed(workspace,tmp_path);d=get(client,headers)
    body={**payload(d),'save_locally':True}
    a=client.post('/api/v9/visual-qa/report',headers=headers,json=body)
    b=client.post('/api/v9/visual-qa/report',headers=headers,json=body)
    assert a.status_code==b.status_code==200
    first,second=Path(a.json()['path']),Path(b.json()['path'])
    assert first!=second and first.is_file() and second.is_file()
    assert first.is_relative_to(project.paths.exports)
    before={p.name:p.read_bytes() for p in first.parent.iterdir()}
    def fail(*args,**kwargs):raise OSError('Synthetic audit failure')
    monkeypatch.setattr(project.db,'audit',fail)
    assert client.post('/api/v9/visual-qa/report',headers=headers,json=body).status_code==400
    assert {p.name:p.read_bytes() for p in first.parent.iterdir()}==before


def test_stale_history_not_reused_and_csv_formula_text_safe(workspace,tmp_path):
    client,project,headers,_=seed(workspace,tmp_path);d=get(client,headers)
    assert client.post('/api/v9/visual-qa/export',headers=headers,json={**payload(d),'confirmed':True,'changes':[{'point_uuid':d['points'][0]['point_uuid'],'offset':1}]}).status_code==200
    with project.db.connect() as c:c.execute("UPDATE canonical_points SET point_id='=2+2' WHERE point_id='003'")
    d=get(client,headers)
    files,e=unpack(client.post('/api/v9/visual-qa/report',headers=headers,json=payload(d)))
    assert e['historical_exports_excluded']==1 and e['correction_exports']==[]
    assert "'=2+2" in files['findings.csv'].decode('utf-8-sig')
    assert e['points'][2]['point_id']=='=2+2'


def test_empty_report_and_explicit_size_limit(workspace,tmp_path,monkeypatch):
    from surveysync import visual_qa_report as reports
    client,project,headers,_=seed(workspace,tmp_path);d=get(client,headers)
    monkeypatch.setattr(reports,'MAX_REPORT_ROWS',1)
    r=client.post('/api/v9/visual-qa/report',headers=headers,json=payload(d))
    assert r.status_code==400 and 'No partial' in r.text
    with project.db.connect() as c:c.execute('DELETE FROM canonical_points')
    files,e=unpack(client.post('/api/v9/visual-qa/report',headers=headers,json=payload(get(client,headers))))
    assert e['issues']==[]
    with fitz.open(stream=files['QA_Review.pdf'],filetype='pdf') as pdf:
        assert 'No findings' in unicodedata.normalize('NFKC', ''.join(p.get_text() for p in pdf))


def test_long_unicode_reason_duplicate_ids_and_pdf_bounds(workspace,tmp_path):
    client,project,headers,_=seed(workspace,tmp_path)
    with project.db.connect() as c:
        c.execute("UPDATE canonical_points SET point_id='001A', description=?", ("X"*300,))
    d=get(client,headers)
    issue=next(i for i in d['issues'] if i['kind']=='duplicate_id')
    reason=('Independent review José: observations checked. '*35)+'FINAL_REVIEW_MARKER'
    assert client.post('/api/v9/visual-qa/review',headers=headers,json={**payload(d),'issue_id':issue['issue_id'],'decision':'dismissed','reason':reason}).status_code==200
    files,e=unpack(client.post('/api/v9/visual-qa/report',headers=headers,json=payload(d)))
    rows=list(csv.DictReader(io.StringIO(files['findings.csv'].decode('utf-8-sig'))))
    assert len({r['point_uuid'] for r in rows if r['kind']=='duplicate_id'})==3
    with fitz.open(stream=files['QA_Review.pdf'],filetype='pdf') as pdf:
        text=unicodedata.normalize('NFKC',''.join(p.get_text() for p in pdf))
        assert 'FINAL_REVIEW_MARKER' in text and 'José' in text
        for page in pdf:
            for word in page.get_text('words'):
                assert word[0]>=40 and word[2]<=573 and word[1]>=18 and word[3]<=772
