# SurveySync 9.4 Brand Asset Integration

Canonical source: user-supplied `surveysync-assets.zip`, September 26, 2026.

## Next-build runtime mapping

| SurveySync surface | Canonical supplied asset |
|---|---|
| Windows Setup icon | `ico/surveysync-globe.ico` |
| SurveySync.exe / desktop shortcut | `ico/surveysync-globe.ico` |
| Browser favicon | `ico/surveysync-globe.ico` or simple 16/32 SVG derivative |
| Product top-left emblem | `svg/logos/surveysync-emblem.svg` |
| Splash/About header | `svg/logos/surveysync-logo-horizontal.svg` |
| Compact product mark | SurveySync globe derivative; do not substitute the S/monogram in active runtime branding |
| Alternate launcher concept | `ico/surveysync-satellite.ico` |
| Module/workflow cards | `svg/workflow-icons/01-*.svg` through `12-*.svg` |
| Color/theme tokens | `tokens.json` |

## Existing files to replace or supersede

- `branding/SurveySync.ico`
- `branding/SurveySync_globe_512.png`
- `branding/app_icon_256.png`
- `branding/brand_header.png`
- `surveysync/static/favicon.ico`
- `surveysync/static/surveysync_globe.svg`
- legacy SurveySync logo image surfaces when they are still referenced

## QA requirements

- Verify multi-resolution Windows icon rendering at 16, 24, 32, 48, 64, 128 and 256 px.
- Use the globe at every active SurveySync product-icon size; small Windows frames are downsampled from the canonical globe artwork.
- Regenerate the empty 48 px GNSS PNG from its valid SVG master.
- Verify light/dark/system themes do not lose the navy/gold identity or reduce contrast.
- Verify installer, Start Menu shortcut, desktop shortcut, taskbar/WebView and file association use the new icon.
- Keep EDSI/client branding profiles separate from SurveySync product ownership/branding.
