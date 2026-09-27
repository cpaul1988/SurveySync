# Trimble JobXML Compatibility

## Purpose

SurveySync reads Trimble JobXML (`.jxl` / `.xml`) directly and uses the
official Trimble ASCII File Generator only when a proprietary binary `.job`
must first be converted to JobXML.

The 9.4 compatibility pass is informed by the BSD-3-Clause project
[jxl2txt](https://github.com/mrahnis/jxl2txt), which demonstrates tolerant
JobXML handling and XSLT-driven field variability. SurveySync does not replace
its parser with jxl2txt or an XSLT-only pipeline.

## Compatibility behavior

SurveySync now regression-tests and supports:

- JobXML namespace/version changes without hard-coded schema URIs;
- `Reductions`, `InventoryData`, `FieldBook`, and `Environment` sections
  nested beneath wrapper elements;
- UTF-8, UTF-8 BOM, UTF-16 BOM, and declared legacy Windows encodings;
- point identity supplied by `PointName`, `PointID`, `PointId`, or `Name`;
- attribute-based point name/code/method/classification fields;
- `North/Northing`, `East/Easting`, and common elevation aliases;
- Reductions-first behavior with InventoryData supplementation;
- FieldBook GNSS occupation metadata merged back onto reduced points;
- namespace-qualified `xsi:schemaLocation` and root product/version metadata.

## Safe recovery policy

jxl2txt uses libxml2 recovery mode. SurveySync intentionally uses a narrower
recovery policy.

Strict XML parsing always runs first. If it fails, SurveySync may perform only
safe text-level recovery for:

1. illegal XML control characters embedded in field text;
2. bare ampersands in field text, converted to `&amp;`.

SurveySync records this in metadata:

- `xml_parse_mode`;
- `xml_recovery_used`;
- `xml_recovery_actions`;
- `strict_parse_error`.

SurveySync does **not** attempt to repair mismatched tags, missing closing
elements, or other structural corruption. Structurally damaged JobXML remains a
hard error.

## Point-name precedence

Some vendor records contain a generic `Name` element before the actual survey
point identifier. SurveySync therefore uses this preference order:

1. `PointName`
2. `PointID`
3. `PointId`
4. `Name`

This prevents an unrelated generic name from replacing the actual point ID.

## Binary .JOB files

SurveySync does not reverse-engineer Trimble's proprietary binary `.job`
format.

The supported path is:

`Trimble .job -> official Trimble ASCII File Generator -> JobXML -> SurveySync`

The original `.job` remains preserved as project source evidence.

## Regression matrix

`tests/test_v940_jxl_regression.py` covers:

- namespaced and nested JobXML;
- GNSS metadata extraction;
- attribute-based point data;
- InventoryData supplementation;
- UTF-16;
- text-level XML recovery;
- structural-corruption rejection;
- rejection of valid non-JobXML files;
- BSD attribution.

These synthetic cases improve parser resilience but do not replace testing with
real Trimble Access/TBC exports from the controller and office versions used in
production.

## Upstream reference

Project: https://github.com/mrahnis/jxl2txt

License: BSD 3-Clause

Copyright (c) 2015, Michael A. Rahnis
