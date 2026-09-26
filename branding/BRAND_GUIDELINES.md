# SurveySync Brand Guidelines — 9.4

## Identity

**SurveySync**  
Tagline: **UNIFYING GLOBAL DATA**

The 9.4 product identity uses the user-supplied September 26, 2026 SurveySync asset pack as the canonical source.

## Palette

- Surveying Navy: `#0F203C` — primary brand/UI chrome
- Topographic Gold: `#C19D65` — contours, highlights and active accents
- Canvas Cream: `#F6F4EE` — workspace/document backgrounds
- Charcoal Slate: `#1A2433` — secondary text/structure
- Navy Deep: `#0A1628`
- Navy Light: `#1A3358`
- Gold Dark: `#9A7840`

## Typography

- Wordmark: Playfair Display Bold
- Runtime serif fallback: DM Serif Display / Georgia / serif
- Tagline and UI: Inter
- Runtime sans fallback: Barlow / Helvetica / Arial / sans-serif

SurveySync must not ship font files from the asset package. Use installed/web-safe fallbacks when the preferred families are unavailable.

## Primary usage

- Windows launcher / installer / shortcut: topographic globe application icon.
- Top-left product brand: globe + pole star + satellite emblem.
- Splash/About/first-run branding: horizontal SurveySync lockup.
- Compact project/file surfaces: SurveySync monogram when an appropriate derivative is available.
- Detailed globe should not be reduced below 48 px; use simplified 32/16 masters for small UI surfaces.

## Workflow icon mapping

- Job/project setup: `01-job-setup`
- GNSS / RTK / local frame: `02-gnss-rtk`
- Total station: `03-total-station`
- Leveling: `04-leveling`
- Feature codes / field-note profile: `05-feature-codes`
- Stakeout / alignment stake points: `06-stakeout`
- Point database / Data Inspector: `07-point-database`
- Traverse / COGO network: `08-traverse`
- Topo / surfaces / contours: `09-surfaces-contours`
- BoundarySync / parcels: `10-boundary-parcels`
- Field/cloud sync: `11-fieldsync`
- ReportSync / deliverables: `12-reports-export`

## Asset QA note

The supplied `png/workflow-icons/48/02-gnss-rtk.png` is empty. The SVG master, 24 px PNG and 192 px PNG are valid. Regenerate the 48 px derivative from the SVG master during 9.4 asset preparation rather than shipping the empty file.
