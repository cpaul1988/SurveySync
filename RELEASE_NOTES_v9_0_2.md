# SurveySync v9.0.2 Release Notes

## Evidence-first FieldBookSync analysis

SurveySync 9.0.2 changes FieldBookSync from a model-first reader into an evidence-first survey review pipeline. AI providers still help read difficult handwriting and page layouts, but authoritative PointID decisions remain tied to imported survey targets plus independent OCR evidence.

### New analysis flow

1. **Fast page/context pass** — when Windows AI Text Recognition is already ready, SurveySync uses it first to locate obvious exact PointIDs and classify page context without downloading anything or sending data to the cloud.
2. **Document OCR for unresolved/risky evidence** — PaddleOCR-VL 1.6 remains the document-specialized accuracy pass for PointIDs Windows did not confidently anchor, plus riskier contexts such as level-loop/control/index pages.
3. **Targeted vision only** — Qwen3-VL sees localized crops around relevant evidence instead of whole books whenever possible. Hardware-aware 2B/4B/8B model selection remains supported.
4. **Page-type-aware prompts** — utility/structure, level-loop, control/GNSS, topo, index, sketch, blank, and unknown pages receive conservative routing guidance. Level-loop/control/index numbers are explicitly prevented from being casually reinterpreted as sewer dips.
5. **Deterministic evidence scoring** — every interpreted entry gets an evidence score, decision, source-engine list, and validation flags. Model self-confidence by itself cannot make a result authoritative.
6. **Review routing** — high-quality independent agreement can mark semantic details `AUTO_ACCEPT`; conflicting, ambiguous, or AI-only evidence is routed to `REVIEW_DETAILS` or `MANUAL_REVIEW`.

### Windows AI behavior

Windows AI is still fully used when available. In Automatic mode it now acts as a fast local accelerator inside the preferred evidence-first pipeline instead of replacing the document-specialized models. A high-confidence Windows OCR hit can avoid redundant PointID searching only when the page is confidently classified as a utility/structure page. All unresolved or risky IDs continue through PaddleOCR-VL.

### Local and cloud providers

Automatic remains local-only. The preferred local stack is:

- Windows AI Text Recognition when ready (fast pass)
- PaddleOCR-VL 1.6 (document OCR / unresolved evidence)
- Qwen3-VL through the local runtime (targeted visual interpretation)
- Foundry Local / Windows local AI fallbacks when the preferred local stack is unavailable
- Manual Review when local evidence remains insufficient

Gemini, OpenAI, and Anthropic Claude remain explicit, opt-in cloud backup providers. Automatic never silently switches to a paid cloud provider.

### Review UI

The FieldBookSync review window now exposes the first evidence record's:

- Evidence decision
- Evidence score
- Evidence source engines
- Detected page type

alongside the existing field-book image/crop, OCR text, status, dip detail, deterministic QA, and manual editing tools.


### Reviewed PointID reassignment

The Structure Review window now lets the reviewer correct a wrong PointID directly against the imported survey point list. When a PointID is changed, SurveySync:

- transfers only the derived FieldBook interpretation to the selected survey point while keeping each point's authoritative coordinates/code/category in place;
- preserves the original OCR text and raw PointID observation instead of silently rewriting source evidence;
- records the original and corrected associations in one atomic audit-history event;
- supports one-step Undo/Redo of the complete two-point reassignment;
- resets the incorrectly assigned source point to its no-evidence baseline and marks the correction as reviewed; and
- refuses to overwrite a target point that already contains FieldBook evidence or reviewed manual edits.

Accept now saves any pending review edits first, so a corrected PointID, status, notes, and pipe edits are committed before the result is marked accepted.

### Preserved v9.0.1 improvements

v9.0.2 retains the unified one-button SurveySync updater, shared application ribbon, global themes/System-Light-Dark appearance, SurveySync globe branding, project-independent Feedback Wizard, local-first feedback retry behavior, and the v9.0.1 updater/reporting/import/export fixes.

### Packaging hotfix — PaddleOCR bridge
- Restored the required `paddle_bridge.py` runtime asset used by the FieldBookSync evidence-first OCR pipeline.
- Paddle health checks now verify both the isolated Paddle environment and the bridge before reporting the engine as ready.
- If the bridge is ever missing or damaged, Automatic mode can select another ready local engine instead of starting a job that must fail with OCR-001.
- Updated local-AI setup script branding to SurveySync 9.0.2 / FieldBookSync.

### Crew point-range finder
- Reworked Available Point Ranges into a crew-allocation tool instead of a raw numeric-gap dump.
- Every numeric PointID in the selected survey file(s) is treated as occupied and is never recommended for reuse.
- The first recommendation is a clean open-ended 1000-series above the highest occupied PointID (for example, `12000 and above`).
- Internal unused blocks are ranked by capacity so the largest useful crew ranges appear first.
- The default table omits tiny gaps under 100 points and reports how many were omitted; the ReportSync view can change the minimum crew-block size.
- Results are presented in a clean table with Available Point Range, Capacity, Priority, and Notes, and can be exported to CSV.
- FieldBookSync and ReportSync use the same canonical recommendation engine so the two modules cannot drift apart.
