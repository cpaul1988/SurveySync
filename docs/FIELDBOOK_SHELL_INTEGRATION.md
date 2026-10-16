# FieldBookSync shared shell and project binding

## User workflow

Open/create a SurveySync project once. The project card above the FieldBook tools is the same component used by ControlSync. FieldBookSync retains its field-note functions but supplies only workspace content to the main application. Module tabs preserve the live FieldBook document, selected review filter, selected files and open review work. New/Open shortcuts resolve to SurveySync project management; explicit .fbs snapshot import/export remains module-specific.

An actual project change replaces the content pane. The user is warned when it contains entered values, chosen files or an open dialog. This warning is intentionally conservative; values already saved by an operation may still be present in the form. Active processing or in-flight storage use also causes the backend to refuse a project switch. Ordinary module navigation does not switch projects or cancel analysis.

## Architecture

`surveysync/static/fieldbook_host.js` manages one same-origin iframe per project ID/root, not a page navigation. The server returns the project context at `GET /api/v9/fieldbook/context`. The child sends an explicit ready/error handshake, supports retry without resetting saved data, inherits the parent's resolved CSS variables and forwards native dialogs through the parent's pywebview bridge. Duplicate legacy menus/sidebar are hidden in embedded mode. The shared Tools menu exposes module commands that would otherwise be hidden with the legacy menu.

`fieldbook_sync/static/shell_bridge.js` captures the view's token at creation. It scopes same-origin API fetches and XHR uploads with `X-SurveySync-Project`, and download URLs with `ss_project`. The token derives from project ID plus normalized root; it is a consistency guard, not an authentication credential. Top-level legacy /fieldbook links redirect to the shared shell, preserving feedback actions. A child handshake is accepted only from the current iframe's Window.

`surveysync/fieldbook_session.py` coordinates short locks and request leases. The ASGI wrapper retains a lease through the final streaming response. Project replacement requires exclusive access and refuses concurrent operations. It checks the actual runtime root, stored project ID and bound identity against the canonical project. Background workers are checked separately because an HTTP request can finish before its work does.

`fieldbook_sync/project_binding.py` builds and validates a candidate runtime before retiring the previous ledger. Reopening the same ID/root preserves the runtime. AppStorage mirrors canonical identity on every save. Explicit snapshot imports can adopt the destination identity; ordinary load/recovery rejects a conflicting stored ID. Previous module titles are retained as `legacy_project_name`; no source coordinate transformation is implied by display consistency.

## Support and failure handling

The no-project token admits support initialization and feedback but refuses data modifications/exports. Feedback and application exit must remain usable when the module is incorrectly bound. Feedback retry threads capture the original root before starting and never consult a newly selected runtime for report writes. Deferred startup probes target the runtime that launched them rather than a later project.

No installer or update channel is promoted by this feature. See RELEASE_NOTES_v9_5_3.md, QA_REPORT_v9_5_3.md, and the exact candidate CI evidence.
