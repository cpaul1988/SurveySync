from __future__ import annotations

from pathlib import Path

import pytest

from surveysync.trimble_job import TrimbleJobError, parse_jobxml_points

UPSTREAM = "https://github.com/mrahnis/jxl2txt"


def test_namespaced_nested_jobxml_extracts_points_environment_and_gnss_metadata(tmp_path):
    path = tmp_path / "access_namespaced.jxl"
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<JOBFile
    xmlns="http://www.trimble.com/schema/JobXML/6_33"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.trimble.com/schema/JobXML/6_33 JobXMLSchema-6.33.xsd"
    jobName="Access Namespace"
    version="6.33"
    product="Trimble Access"
    productVersion="2026.10"
    TimeStamp="2026-09-26T12:34:56">
  <JobData>
    <Environment>
      <CoordinateSystemName>Texas South Central</CoordinateSystemName>
      <DistanceUnits>USSurveyFeet</DistanceUnits>
    </Environment>
    <FieldBook>
      <GNSSOccupationRecord>
        <PointName>5001</PointName>
        <StartDateTime>2026-09-26T08:00:00</StartDateTime>
        <Epochs>600</Epochs>
        <SatellitesUsed>18</SatellitesUsed>
        <PDOP>1.4</PDOP>
        <ReceiverModel>R12i</ReceiverModel>
      </GNSSOccupationRecord>
    </FieldBook>
    <Reductions>
      <Point PointName="5001" Code="CTRL">
        <Grid>
          <Northing>304725.100</Northing>
          <Easting>273455.200</Easting>
          <Height>152.700</Height>
        </Grid>
      </Point>
    </Reductions>
  </JobData>
</JOBFile>""",
        encoding="utf-8",
    )

    parsed = parse_jobxml_points(path)
    point = parsed["points"][0]
    metadata = parsed["metadata"]

    assert metadata["job_name"] == "Access Namespace"
    assert metadata["jobxml_version"] == "6.33"
    assert metadata["product"] == "Trimble Access"
    assert metadata["namespace_uri"].endswith("/JobXML/6_33")
    assert "JobXMLSchema-6.33.xsd" in metadata["schema_location"]
    assert metadata["point_source"] == "Reductions"
    assert metadata["xml_parse_mode"] == "strict"
    assert metadata["xml_recovery_used"] is False
    assert metadata["environment"]["DistanceUnits"] == "USSurveyFeet"

    assert point["point_id"] == "5001"
    assert point["code"] == "CTRL"
    assert point["northing"] == pytest.approx(304725.1)
    assert point["easting"] == pytest.approx(273455.2)
    assert point["elevation"] == pytest.approx(152.7)
    assert point["observed_utc"] == "2026-09-26T08:00:00"
    assert point["epoch_count"] == 600
    assert point["satellite_count"] == 18
    assert point["pdop"] == pytest.approx(1.4)
    assert point["receiver_model"] == "R12i"


def test_pointname_is_preferred_over_generic_name_and_inventory_supplements(tmp_path):
    path = tmp_path / "mixed_sections.jxl"
    path.write_text(
        """<JOBFile jobName="Mixed">
  <Reductions>
    <Point>
      <Name>generic-wrong-name</Name>
      <PointName>7001</PointName>
      <Code>EP</Code>
      <Grid><North>10</North><East>20</East><Elevation>5</Elevation></Grid>
    </Point>
  </Reductions>
  <InventoryData>
    <Point>
      <Name>7001</Name>
      <Code>OLD</Code>
      <Grid><North>999</North><East>999</East><Elevation>999</Elevation></Grid>
    </Point>
    <Point>
      <PointID>7002</PointID>
      <FeatureCode>CL</FeatureCode>
      <Grid><Northing>11</Northing><Easting>21</Easting><Elev>6</Elev></Grid>
    </Point>
  </InventoryData>
</JOBFile>""",
        encoding="utf-8",
    )

    parsed = parse_jobxml_points(path)

    assert [row["point_id"] for row in parsed["points"]] == ["7001", "7002"]
    assert parsed["points"][0]["northing"] == pytest.approx(10.0)
    assert parsed["points"][1]["code"] == "CL"
    assert parsed["metadata"]["reduction_point_count"] == 1
    assert parsed["metadata"]["inventory_point_count"] == 1
    assert parsed["metadata"]["duplicate_point_ids"] == []


def test_utf16_jobxml_is_read_without_conversion_or_recovery(tmp_path):
    path = tmp_path / "utf16_export.jxl"
    text = """<?xml version="1.0" encoding="utf-16"?>
<JOBFile JobName="UTF16 Export" Version="5.3" Product="Trimble Survey Controller">
  <InventoryData>
    <Point Name="8001" Code="SSMH" SurveyMethod="KeyedIn">
      <Grid><North>1000.5</North><East>2000.25</East><Elevation>12.75</Elevation></Grid>
    </Point>
  </InventoryData>
</JOBFile>"""
    path.write_bytes(text.encode("utf-16"))

    parsed = parse_jobxml_points(path)

    assert parsed["metadata"]["job_name"] == "UTF16 Export"
    assert parsed["metadata"]["jobxml_version"] == "5.3"
    assert parsed["metadata"]["product"] == "Trimble Survey Controller"
    assert parsed["metadata"]["xml_parse_mode"] == "strict"
    assert parsed["points"][0]["point_id"] == "8001"
    assert parsed["points"][0]["survey_method"] == "KeyedIn"


def test_safe_recovery_handles_bad_field_text_but_reports_recovery(tmp_path):
    path = tmp_path / "recoverable_text.jxl"
    raw = (
        b'<?xml version="1.0" encoding="utf-8"?>\n'
        b'<JOBFile jobName="Recovered"><Reductions><Point>'
        b'<Name>9001</Name><Code>EP & CL\x0b</Code>'
        b'<Grid><North>1</North><East>2</East><Elevation>3</Elevation></Grid>'
        b'</Point></Reductions></JOBFile>'
    )
    path.write_bytes(raw)

    parsed = parse_jobxml_points(path)
    metadata = parsed["metadata"]

    assert parsed["points"][0]["code"] == "EP & CL"
    assert metadata["xml_parse_mode"] == "recovered_text"
    assert metadata["xml_recovery_used"] is True
    assert "escaped_bare_ampersands" in metadata["xml_recovery_actions"]
    assert "removed_illegal_xml_control_characters" in metadata["xml_recovery_actions"]
    assert metadata["strict_parse_error"]


def test_structurally_corrupt_jobxml_remains_fail_closed(tmp_path):
    path = tmp_path / "broken_structure.jxl"
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<JOBFile><Reductions><Point><Name>1</Name><Grid><North>1</North><East>2</East></Point></Reductions></JOBFile>""",
        encoding="utf-8",
    )

    with pytest.raises(TrimbleJobError, match="could not be parsed"):
        parse_jobxml_points(path)


def test_non_jobxml_root_is_rejected_even_when_xml_is_valid(tmp_path):
    path = tmp_path / "other.xml"
    path.write_text(
        "<LandXML><CgPoints><CgPoint name='1'>1 2 3</CgPoint></CgPoints></LandXML>",
        encoding="utf-8",
    )

    with pytest.raises(TrimbleJobError, match="not recognized as Trimble JobXML"):
        parse_jobxml_points(path)


def test_jxl2txt_reference_and_bsd_attribution_are_documented():
    notices = Path("THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    docs = Path("docs/JOBXML_COMPATIBILITY.md").read_text(encoding="utf-8")

    assert "mrahnis/jxl2txt" in notices
    assert "Copyright (c) 2015, Michael A. Rahnis" in notices
    assert "BSD 3-Clause" in notices
    assert UPSTREAM in docs
    assert "safe text-level recovery" in docs
    assert "official Trimble ASCII File Generator" in docs
