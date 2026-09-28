"""Failure-path invariants for newly connected output and workflow operations."""
from pathlib import Path
import pytest
from test_v940_pointcloud_workflows import _project
from test_v940_crs_report_gis_bridges import _template
from surveysync import report_template_mapper as tm
from surveysync import workflow_engine as wf
from surveysync import gis_bridges as gb


def test_template_partial_write_removed_without_touching_input(tmp_path,monkeypatch):
    from openpyxl.workbook.workbook import Workbook
    project=_project(tmp_path);source=_template(tmp_path/'original.xlsx');before=source.read_bytes()
    saved=tm.register_excel_template(project,source);output=tmp_path/'partial.xlsx'
    def fail(self,stream):stream.write(b'incomplete');raise OSError('Injected disk failure')
    monkeypatch.setattr(Workbook,'save',fail)
    with pytest.raises(OSError):tm.render_excel_template(project,saved['template_id'],output_path=output)
    assert not output.exists() and source.read_bytes()==before


def test_exclusive_create_race_keeps_competing_empty_output(tmp_path,monkeypatch):
    project=_project(tmp_path);source=_template(tmp_path/'original.xlsx')
    saved=tm.register_excel_template(project,source);output=tmp_path/'competing.xlsx'
    original=Path.open
    def race(path,*args,**kwargs):
        if path==output and args and args[0]=='xb':
            with original(output,'wb'):pass
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',race)
    with pytest.raises(FileExistsError):tm.render_excel_template(project,saved['template_id'],output_path=output)
    assert output.is_file() and output.stat().st_size==0


def test_invalid_mapping_does_not_register_source(tmp_path):
    project=_project(tmp_path);source=_template(tmp_path/'original.xlsx')
    before=project.sources()
    with pytest.raises(tm.ReportTemplateError):
        tm.register_excel_template(project,source,mapping={'scalar_cells':[{'field':'project.name','sheet':'Missing','cell':'A1'}]})
    assert project.sources()==before and tm.list_templates(project)==[]


def test_large_yaml_refused_before_parser(tmp_path,monkeypatch):
    project=_project(tmp_path)
    monkeypatch.setattr(wf.yaml,'safe_load',lambda _:pytest.fail('Oversize data reached parser'))
    with pytest.raises(wf.WorkflowError):wf.import_workflows_yaml(project,'x'*(1024*1024+1))


@pytest.mark.parametrize('value',['x&other','x|other','%COMSPEC%','x\r\nother','x"other'])
def test_batch_argument_metacharacters_refused(value):
    with pytest.raises(gb.GisBridgeError):gb._run(['qgis.cmd','run','native:buffer','INPUT='+value],timeout_seconds=5)


def test_invalid_explicit_engine_does_not_fall_back(tmp_path,monkeypatch):
    monkeypatch.setattr(gb,'_qgis_candidates',lambda:pytest.fail('Explicit path silently fell back'))
    assert gb.find_qgis_process(tmp_path/'missing.exe') is None
