## Beta.3 — FieldBookSync-standard interface and installed UI repair

This candidate responds to CP's installed Beta.2 screenshots and request to make Home and the other modules look and feel like FieldBookSync.

- Both shells load `fieldbook-standard.css` after their existing styles. FieldBookSync palettes, body typography, cards, navigation, controls, spacing, and light/dark settings form the shared presentation layer. Saved preferences remain authoritative; no client branding or project data is reset.
- Home has the same compact project toolbar, workspace sidebar, metric cards, and workflow entry cards. Module-specific tools and data operations remain.
- Corrects the Element-versus-NodeList icon initialization error. Static serving accepts nested workflow-icon paths while rejecting traversal and resolved symlink escapes. Decorative icon failure cannot stop startup.
- Release notes load independently of project/status requests, identify `9.4.0-beta.3`, time out with Retry, and remain unread until Continue.
- Globe-derived transparent web/Windows icons and real 24-bit installer BMPs are regenerated together before compilation. Large and small wizard graphics have high-resolution alternatives. Dark-mode wordmarks use light lettering without inverting the globe.
- Removes a duplicate operations-router inclusion. The main router still registers the original operations router; no operations endpoints are removed.

Validation before submission: 387 tests passed, 1 skipped locally; JavaScript syntax, static quality, and documentation checks passed. Browser CI adds actual screenshots for 11 modules in light and dark mode, first-launch/acknowledgment/retry checks, image decoding, and responsive Home checks. CI and installed Windows acceptance are separate; a generated image or unit test is not proof that the installed wizard was visually checked.

Pre-build feedback: connected Intake sheet read through row 1001; 16 reports, latest FBR-0016 dated 2026-09-22. This candidate also incorporates the current chat's UI and branding reports. No tracker records were changed.

Branch: `v9.4.0-beta3-unified-ui`. Beta.2 and Stable artifacts remain unchanged until the normal tagged release workflow is explicitly run.
