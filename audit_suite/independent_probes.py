"""Audit released code; never modify application source, feeds, or real projects."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'audit-evidence'
OUT.mkdir(exist_ok=True)
RESULTS = []


def probe(name, func):
    try:
        detail = func()
        RESULTS.append({'name': name, 'status': 'PASS', 'detail': detail})
    except Exception as exc:
        RESULTS.append({'name': name, 'status': 'FAIL', 'detail': str(exc), 'trace': traceback.format_exc()})


def check_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(f'{message}: expected {expected!r}, actual {actual!r}')
    return {'actual': actual, 'expected': expected}


def main():
    with tempfile.TemporaryDirectory(prefix='ss940-audit-') as tmp:
        base = Path(tmp)
        os.environ['SURVEYSYNC_CONFIG_ROOT'] = str(base / 'config')
        os.environ['SURVEYSYNC_FIELD_ROOT'] = str(base / 'field')
        from fastapi.testclient import TestClient
        from fieldbook_sync import app as f
        from surveysync import router as r
        from surveysync.landxml_io import export_landxml
        from surveysync.leveling import parse_level_csv, solve_level_run
        from surveysync.field_to_finish import parse_coded_points
        from surveysync.traverse import parse_traverse_csv
        from surveysync.cogo_extended import polygon_area_perimeter
        from fieldbook_sync.models import ResultRecord, PipeMeasurement, NetworkEdge
        r.config_store = r.ConfigStore(base / 'config')
        r.current_project = None
        f.runtime = f.Runtime(base / 'field')
        client = TestClient(f.app, raise_server_exceptions=False)
        res = client.post('/api/v9/project/create', json={'parent_folder': str(base / 'projects'), 'name': 'Audit only', 'crs': 'EPSG:2278', 'horizontal_units': 'us_survey_feet', 'vertical_units': 'us_survey_feet'})
        check_equal(res.status_code, 200, 'Create isolated project')

        def repeat_landxml():
            file = base / 'points.xml'
            export_landxml(output_path=file, points=[{'point_id': '101', 'northing': 1000., 'easting': 2000., 'elevation': 10.}], parcels=[], alignments=[])
            first = client.post('/api/v9/landxml/import', json={'file_path': str(file)})
            second = client.post('/api/v9/landxml/import', json={'file_path': str(file)})
            check_equal(first.status_code, 200, 'First LandXML import')
            return check_equal(second.status_code, 200, 'Second LandXML import: ' + second.text)
        probe('A01 repeated LandXML import', repeat_landxml)

        def header(parser, name, text):
            file = base / name
            file.write_text(text, encoding='utf-8')
            return {'rows': len(parser(file))}
        probe('A02 level PointID header', lambda: header(parse_level_csv, 'level.csv', 'PointID,BS,FS\nTP1,1.5,1.0\n'))
        probe('A03 linework PointID header', lambda: header(parse_coded_points, 'coded.csv', 'PointID,Northing,Easting,Elevation,Code\n1,1000,2000,20,500-BS\n2,1010,2000,20,500-ES\n'))

        def fieldbook_rows():
            result = solve_level_run([{'point_id': 'BM_START', 'backsight': 1.5}, {'point_id': 'TP1', 'foresight': 1., 'backsight': 2.}, {'point_id': 'BM_END', 'foresight': 1.2}], start_elevation=100., known_end_elevation=101.3, adjustment_method='none')
            return check_equal([round(x['raw_elevation'], 6) for x in result['results']], [100., 100.5, 101.3], 'Point elevations in separate BS/FS fieldbook layout')
        probe('A04 separate fieldbook BS/FS point elevations', fieldbook_rows)

        def invalid(parser, filename, text):
            try:
                value = header(parser, filename, text)
            except ValueError:
                return 'Invalid number rejected'
            raise AssertionError('Nonfinite survey input was accepted: ' + str(value))
        for bad in ('nan', 'inf', '-inf'):
            probe('A05 level rejects ' + bad, lambda bad=bad: invalid(parse_level_csv, 'invalid-level.csv', f'Point,BS,FS\nTP1,{bad},1.0\n'))
        for bad in ('nan', 'inf'):
            probe('A05 traverse rejects ' + bad, lambda bad=bad: invalid(parse_traverse_csv, 'invalid-traverse.csv', f'From,To,Azimuth,Distance\n1,2,0,{bad}\n'))

        def traverse_json():
            file = base / 'traverse.csv'
            file.write_text('From,To,Azimuth,Distance\n1,2,0,100\n')
            imported = client.post('/api/v9/traverse/import', json={'file_path': str(file), 'start_n': 0., 'start_e': 0., 'end_n': 100., 'end_e': 0., 'adjustment_method': 'none'})
            check_equal(imported.status_code, 200, 'Traverse import')
            solved = client.post('/api/v9/traverse/solve', json={'run_id': imported.json()['run_id'], 'adjustment_method': 'none'})
            return check_equal(solved.status_code, 200, 'Exactly closing valid traverse: ' + solved.text)
        probe('A06 exact traverse JSON response', traverse_json)

        def mixed_grade():
            r.current_project.manifest['vertical_units'] = 'meters'
            f.runtime.storage.state.results = [ResultRecord(point_id='1', code='351', northing=0, easting=0, elevation=12, pipes=[PipeMeasurement(invert_elevation=10.)]), ResultRecord(point_id='2', code='351', northing=100, easting=0, elevation=11, pipes=[PipeMeasurement(invert_elevation=9.)])]
            f.runtime.storage.state.network_edges = [NetworkEdge(from_point='1', to_point='2', from_pipe_index=1, to_pipe_index=1, distance=100.)]
            value = client.post('/api/v9/utility/analyze', json={})
            check_equal(value.status_code, 200, 'Utility API')
            return check_equal(round(value.json()['grades'][0]['grade_percent'], 6), 3.280833, '1 metre drop over 100 US survey feet')
        probe('A07 mixed-unit utility grade', mixed_grade)

        js = (ROOT / 'surveysync/static/app.js').read_text(encoding='utf-8')
        command = next(x for x in js.splitlines() if x.startswith('function runCommand(cmd)'))
        stub = "let activeModule='Home';let switched='';function closeMenus(){};function switchView(v){switched=v};function $(s){return {classList:{toggle(){}},dataset:{module:'Home'},focus(){},click(){}}};function $$(s){return [$(s)]};const document={};const window={};\n"
        def dom_test(cmd):
            run = subprocess.run(['node', '-e', stub + command + '\nrunCommand(' + json.dumps(cmd) + ');'], text=True, capture_output=True)
            if run.returncode:
                raise AssertionError(run.stderr)
            return 'Command completed'
        for cmd in ('project-data', 'data-inspector', 'support-center', 'project-info', 'project-qa'):
            probe('A08 shell command ' + cmd, lambda cmd=cmd: dom_test(cmd))

        def native_exit():
            stub2 = "let activeModule='Home';function closeMenus(){};let called=false;const window={pywebview:{api:{exit_app:()=>{called=true}}},close:()=>{}};const pywebview=window.pywebview;\n"
            run = subprocess.run(['node', '-e', stub2 + command + "\nrunCommand('exit-app');if(!called)throw Error('Native exit_app was not called');"], text=True, capture_output=True)
            if run.returncode:
                raise AssertionError(run.stderr)
            return 'Native exit_app called'
        probe('A09 native File Exit bridge binding', native_exit)

        def polygon():
            n, e = 10_000_000., 3_000_000.
            points = [{'northing': n+dn, 'easting': e+de} for dn, de in ((0,0),(0,.1),(.2,.1),(.2,0))]
            value = polygon_area_perimeter(points=points)
            if abs(value['area']-.02)>1e-7 or abs(value['centroid_northing']-(n+.1))>1e-5:
                raise AssertionError('Expected area ~0.02, centroid (10000000.1,3000000.05); got ' + json.dumps(value))
            return value
        probe('A10 polygon numeric conditioning at large coordinates', polygon)
        client.close()
    (OUT / 'independent-probes.json').write_text(json.dumps(RESULTS, indent=2), encoding='utf-8')
    print(json.dumps(RESULTS, indent=2))
    if any(x['status']=='FAIL' for x in RESULTS):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
