# Theme-only client branding — 9.4.0 Beta.4

SurveySync's globe is the product identity. EDSI is an optional companion mark,
not a replacement identity and not a default logo for FieldBookSync.

## Behavior

All 13 non-EDSI themes show the SurveySync globe alone. EDSI Adaptive (`edsi`),
EDSI Dark (`edsidark`), and EDSI Light (`edsilight`) show the existing EDSI artwork
beside the globe. Both shells use the same rule in `theme-branding.css`, loaded
after their shared presentation stylesheet. CSS follows the existing shared
`data-product-theme` attribute, so switching themes removes/adds client marks
immediately, including dialogs already open. No page reload is required.

The treatment covers product headers, workspace sidebars, Home's product
lockup, splash markup, About, and release notes. Small module/workflow icons
remain module-specific. The installer, Windows executable, shortcut and favicon
retain the SurveySync globe; their identity does not change with an in-app theme.

FieldBookSync no longer assigns the sidebar/splash image from `meta.icon` when
changing themes. Theme metadata is still available for the theme chooser, but
cannot independently replace a product mark. Saved theme preferences and project
branding/report profiles are retained, not reset or repurposed. Switching to
FieldBook Classic or any other non-EDSI theme removes EDSI branding from the app.

Dark content and the always-dark menubar use a light monochrome EDSI mark.
The original image bytes are unmodified and the globe is never inverted.
On narrow screens the compact companion fits beside the globe; full-width
sidebar layouts give the pair its own row above the module name.

## Validation

`tests/test_theme_branding.py` checks both shells, canonical images, served
assets, dynamic dialog markup, and the exact opt-in theme selectors.
`scripts/theme_branding_smoke.py` uses the live app to exercise all 16 themes
through the Options controls in each shell, client-to-normal switching,
persistence, cross-window synchronization, all module routes, live dialogs,
light/dark appearance, and narrow layouts. Screenshots and results are kept
in the existing `surveysync-ui-evidence` CI artifact. Installer compilation is
still gated by the full release suite. An automated browser run is not a native
installed-Windows acceptance signoff.

## Pre-build feedback

The connected Intake was checked through row 1001 on 2026-09-27 UTC. It still
contains 16 reports, latest FBR-0016 dated 2026-09-22. This change addresses CP's
current-chat branding feedback. No tracker or project records were changed.
