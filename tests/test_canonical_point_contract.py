"""Canonical input failures found by full installed-update fixtures."""
from pathlib import Path
import pytest
from test_audit_reproductions import workspace
from surveysync.point_import import parse_canonical_points


@pytest.mark.parametrize('header', ['PointID','Point ID','point_id','POINT-ID','\ufeffPointID'])
def test_headers_keep_actual_identifiers_and_codes(workspace,tmp_path,header):
    client,context,_=workspace
    p=tmp_path/'points.csv'
    p.write_text(header+',Northing,Easting,Elevation,Code\n001A,1000,2000,10,CP A\n',encoding='utf-8')
    before=p.read_bytes()
    reply=client.post('/api/v9/points/import',json={'file_path':str(p)})
    assert reply.status_code==200,reply.text
    assert reply.json()['count']==1
    with context.current_project.db.connect() as conn:
        row=conn.execute('SELECT point_id,description FROM canonical_points').fetchone()
    assert tuple(row)==('001A','CP A') and p.read_bytes()==before


@pytest.mark.parametrize('bad', ['nan','inf','-inf','bad',''])
def test_bad_numeric_row_never_partially_imports(workspace,tmp_path,bad):
    client,context,_=workspace
    p=tmp_path/'bad.csv';p.write_text(f'point_id,northing,easting\n01,100,200\n02,{bad},201\n',encoding='utf-8')
    reply=client.post('/api/v9/points/import',json={'file_path':str(p)})
    assert reply.status_code==400,reply.text
    assert 'row 3' in reply.json()['detail']
    with context.current_project.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM canonical_points').fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM source_registry').fetchone()[0]==0


@pytest.mark.parametrize('header', ['PointID,point_id,Northing,Easting', 'PointID,Northing,N,Easting', 'PointID,,Easting'])
def test_ambiguous_headers_fail(tmp_path,header):
    p=tmp_path/'bad.csv';p.write_text(header+'\n1,2,3,4\n',encoding='utf-8')
    with pytest.raises(ValueError):parse_canonical_points(p)


def test_multiline_quoted_description_preserved(tmp_path):
    p=tmp_path/'quoted.csv';p.write_text('PointID,Northing,Easting,Elevation,Description\n001A,100,200,,"line one\nline two"\n',encoding='utf-8')
    result=parse_canonical_points(p)
    assert result==[{'point_id':'001A','northing':100.,'easting':200.,'elevation':None,'description':'line one\nline two'}]
