"""Real optional LAS/LAZ and QGIS/GRASS execution on synthetic local data only."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'remaining-evidence'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--gis',action='store_true');args=parser.parse_args()
    OUT.mkdir(exist_ok=True)
    result={'status':'FAIL','checks':[]}
    try:
        import laspy
        import numpy as np
        from surveysync.pointcloud import inspect_point_cloud, sample_points, runtime_status
        with tempfile.TemporaryDirectory(prefix='ss-optional-') as directory:
            tmp=Path(directory)
            header=laspy.LasHeader(point_format=3,version='1.2');header.scales=[.001,.001,.001];header.offsets=[3000000,10000000,0]
            points=laspy.LasData(header);points.x=np.array([3000000.,3000001.,3000002.]);points.y=np.array([10000000.,10000001.,10000002.]);points.z=np.array([10.,11.,12.]);points.classification=np.array([2,6,9],dtype=np.uint8)
            assert runtime_status()['laz_backend_ready'], 'LAZ decoder is required for this optional test'
            for extension in ('las','laz'):
                path=tmp/('known.'+extension);points.write(path);before=hashlib.sha256(path.read_bytes()).hexdigest()
                inspection=inspect_point_cloud(path);sample=sample_points(path,max_points=2)
                assert inspection['metadata']['point_count']==3
                assert sample['sample_count']==2 and sample['points'][0]=={'x':3000000.,'y':10000000.,'z':10.,'classification':2}
                assert hashlib.sha256(path.read_bytes()).hexdigest()==before
                result['checks'].append({'format':extension,'real_library':'laspy '+laspy.__version__,'metadata_reader':inspection['metadata']['reader'],'sample_verified':True})
            if args.gis:
                from surveysync.project import SurveyProject
                from surveysync.gis_bridges import bridge_status,qgis_algorithms,run_qgis_algorithm,run_grass_module
                qgis=shutil.which('qgis_process');grass=shutil.which('grass')
                assert qgis and grass, 'Actual optional GIS executables required'
                project=SurveyProject.create(tmp/'projects','Optional runtime QA',crs='EPSG:3857',horizontal_units='meters',vertical_units='meters')
                status=bridge_status(qgis,grass);result['engines']=status
                algorithms=qgis_algorithms(executable=qgis)
                assert any(a['id']=='native:centroids' for a in algorithms['algorithms']), algorithms
                source=tmp/'square.geojson';source.write_text(json.dumps({'type':'FeatureCollection','features':[{'type':'Feature','properties':{'id':'source001'},'geometry':{'type':'Polygon','coordinates':[[[0,0],[2,0],[2,2],[0,2],[0,0]]]}}]}),encoding='utf-8')
                before=source.read_bytes();output=tmp/'centroid.geojson'
                qresult=run_qgis_algorithm(project,'native:centroids',{'INPUT':str(source),'ALL_PARTS':False,'OUTPUT':str(output)},executable=qgis)
                assert qresult['return_code']==0,qresult
                assert json.loads(output.read_text())['features'][0]['geometry']['coordinates'][:2]==[1.,1.]
                assert source.read_bytes()==before
                result['checks'].append({'qgis':'native:centroids','result':qresult,'verified_centroid':[1.,1.]})
                gresult=run_grass_module(project,'g.region',{'n':2,'s':0,'e':2,'w':0,'res':1},flags=['g'],executable=grass)
                assert gresult['return_code']==0,gresult
                values=dict(line.split('=',1) for line in gresult['stdout'].splitlines() if '=' in line)
                assert float(values['rows'])==2 and float(values['cols'])==2,values
                result['checks'].append({'grass':'g.region','result':gresult,'verified_rows_cols':[2,2]})
        result['status']='PASS'
    except Exception as exc:
        result['failure']=f'{type(exc).__name__}: {exc}';raise
    finally:
        (OUT/('optional-gis-results.json' if args.gis else 'optional-cloud-results.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
