"""Real qgis_process tab output must retain single-word algorithm labels."""
import pytest
from surveysync import gis_bridges as gis

@pytest.mark.parametrize("separator", ["\t", " ", "    "])
def test_single_word_qgis_labels_are_not_discarded(tmp_path,monkeypatch,separator):
    exe=tmp_path/"qgis_process";exe.write_text("fixture",encoding="utf-8")
    output="Provider: native\n"+f"native:centroids{separator}Centroids\nnative:buffer{separator}Buffer\n"+f"native:dissolve{separator}Dissolve features\n"
    monkeypatch.setattr(gis,"_run",lambda *a,**kw:{"return_code":0,"stdout":output,"stderr":""})
    result=gis.qgis_algorithms(executable=exe)
    assert result["algorithms"]==[
        {"id":"native:centroids","label":"Centroids"},
        {"id":"native:buffer","label":"Buffer"},
        {"id":"native:dissolve","label":"Dissolve features"}]
